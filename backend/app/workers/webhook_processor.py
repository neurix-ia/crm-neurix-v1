"""
Webhook Processor Worker — Consumes events from the Redis queue.
Processes Uazapi (WhatsApp) events: saves messages (text + media), detects keywords, moves leads.

Sprint 9: instância → inbox → funnel; sem inbox resolvido não cria lead órfão (AC12);
UNIQUE (inbox_id, whatsapp_chat_id); cliente CRM por telefone normalizado.
"""

import asyncio
import json
import redis.asyncio as aioredis
from app.config import get_settings
from app.services.keyword_engine import keyword_engine
from app.services.lead_finalized_spawn import maybe_spawn_inbound_whatsapp_lead_if_finalized
from app.services.phone_normalize import digits_only, format_brazil_phone_display
from app.services.webhook_lead_context import (
    _chatwoot_ids,
    ensure_stage_for_label,
    find_inbox_by_chatwoot,
    find_inbox_by_instance_name,
    find_inbox_by_instance_token,
    find_inbox_for_tenant,
    find_legacy_tenant_id_for_token,
    get_first_stage_slug_for_funnel,
    resolve_or_create_crm_client,
)


def _resolve_uazapi_instance_token(payload: dict, event: dict) -> str:
    """Uazapi envia o token em campos diferentes (body vs header); webhooks de teste às vezes só têm instanceName."""
    for key in ("token", "instanceToken", "instance_token"):
        v = payload.get(key)
        if v:
            return str(v).strip()
    v = event.get("instance_token")
    if v:
        return str(v).strip()
    return ""


def _extract_content_type(message_data: dict) -> tuple[str, str, str | None, str | None, str | None]:
    """
    Extract content type, text content, and media info from a Uazapi message.
    Returns: (content_type, content_text, media_url, media_mimetype, media_filename)
    """
    msg = message_data.get("message", {})

    # Text message
    if "conversation" in msg:
        return "text", msg["conversation"], None, None, None
    if "extendedTextMessage" in msg:
        return "text", msg["extendedTextMessage"].get("text", ""), None, None, None

    # Image
    if "imageMessage" in msg:
        img = msg["imageMessage"]
        media_url = message_data.get("fileURL") or img.get("url")
        return "image", img.get("caption", ""), media_url, img.get("mimetype"), None

    # Video
    if "videoMessage" in msg:
        vid = msg["videoMessage"]
        media_url = message_data.get("fileURL") or vid.get("url")
        return "video", vid.get("caption", ""), media_url, vid.get("mimetype"), None

    # Audio / Voice note
    if "audioMessage" in msg:
        aud = msg["audioMessage"]
        media_url = message_data.get("fileURL") or aud.get("url")
        return "audio", "", media_url, aud.get("mimetype"), None

    # Document
    if "documentMessage" in msg:
        doc = msg["documentMessage"]
        media_url = message_data.get("fileURL") or doc.get("url")
        return "document", doc.get("caption", ""), media_url, doc.get("mimetype"), doc.get("fileName")

    # Sticker
    if "stickerMessage" in msg:
        stk = msg["stickerMessage"]
        media_url = message_data.get("fileURL") or stk.get("url")
        return "sticker", "", media_url, stk.get("mimetype"), None

    # Reaction
    if "reactionMessage" in msg:
        react = msg["reactionMessage"]
        return "reaction", react.get("text", ""), None, None, None

    # Location
    if "locationMessage" in msg:
        loc = msg["locationMessage"]
        content = f"{loc.get('degreesLatitude', 0)},{loc.get('degreesLongitude', 0)}"
        return "location", content, None, None, None

    # Contact
    if "contactMessage" in msg:
        contact = msg["contactMessage"]
        return "contact", contact.get("displayName", ""), None, None, None

    # Fallback
    return "text", str(msg), None, None, None


async def log_error_to_redis(redis_client, msg: str):
    import time

    err_event = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(err_event)
    try:
        await redis_client.lpush("neurix:webhook_errors", err_event)
        await redis_client.ltrim("neurix:webhook_errors", 0, 49)  # keep last 50
    except Exception:
        pass


async def log_structured_webhook(redis_client, payload: dict):
    """Log JSON estruturado para diagnóstico (AC12)."""
    line = json.dumps(payload, ensure_ascii=False)
    await log_error_to_redis(redis_client, line)


def _lead_select_cols() -> str:
    return "id, stage, tenant_id, inbox_id, funnel_id"


def _find_existing_lead_for_inbox(
    supabase_client,
    *,
    inbox_row: dict,
    chat_id: str,
) -> dict | None:
    """Prioriza (inbox_id, chat_id); senão legado mesmo tenant (inbox_id nulo)."""
    inbox_id = str(inbox_row["id"])
    tenant_id = str(inbox_row["tenant_id"])
    try:
        r = (
            supabase_client.table("leads")
            .select(_lead_select_cols())
            .eq("inbox_id", inbox_id)
            .eq("whatsapp_chat_id", chat_id)
            .limit(1)
            .execute()
        )
        if r.data:
            return r.data[0]
    except Exception:
        pass
    try:
        r2 = (
            supabase_client.table("leads")
            .select(_lead_select_cols())
            .eq("tenant_id", tenant_id)
            .eq("whatsapp_chat_id", chat_id)
            .execute()
        )
        for row in r2.data or []:
            if row.get("inbox_id") is None:
                return row
    except Exception:
        pass
    return None


def _find_existing_lead_legacy_only(
    supabase_client,
    *,
    tenant_id: str,
    chat_id: str,
) -> dict | None:
    try:
        r = (
            supabase_client.table("leads")
            .select(_lead_select_cols())
            .eq("tenant_id", tenant_id)
            .eq("whatsapp_chat_id", chat_id)
            .execute()
        )
        for row in r.data or []:
            if row.get("inbox_id") is None:
                return row
    except Exception:
        pass
    return None


async def process_uazapi_event(event: dict, supabase_client, redis_client):
    """Process a single Uazapi webhook event."""
    payload = event.get("payload", {})
    await log_error_to_redis(
        redis_client,
        f"START process_uazapi_event. EventType: {payload.get('EventType')}",
    )

    # ── Handle New Uazapi Format ──
    if payload.get("EventType") == "messages":
        message_data = payload.get("message", {})
        chat_id = message_data.get("chatid", "")
        msg_id = message_data.get("messageid", "")
        is_from_me = message_data.get("fromMe", False)

        await log_error_to_redis(
            redis_client,
            f"Parsed message fields: chat_id={chat_id}, is_from_me={is_from_me}, isGroup={message_data.get('isGroup')}",
        )

        # Ignore invalid or group chats
        if not chat_id or "@g.us" in chat_id or message_data.get("isGroup"):
            await log_error_to_redis(redis_client, "RETURN: Invalid chat or group chat")
            return

        content_type = message_data.get("type", "text")
        content_text = message_data.get("text", message_data.get("content", ""))
        media_url = None  # Needs adaptation if Uazapi v2 sends file urls differently
        media_mimetype = message_data.get("mediaType", None)
        media_filename = None

        sender_name = message_data.get("senderName", "")
        sender_phone = chat_id.replace("@s.whatsapp.net", "").replace("@g.us", "")

    # ── Handle Old Baileys Format ──
    elif payload.get("event") == "messages.upsert":
        await log_error_to_redis(redis_client, "Parsed as old Baileys format.")
        message_data = payload.get("data", {})
        chat_id = message_data.get("key", {}).get("remoteJid", "")
        msg_id = message_data.get("key", {}).get("id", "")
        is_from_me = message_data.get("key", {}).get("fromMe", False)

        if not chat_id or "@g.us" in chat_id:
            await log_error_to_redis(redis_client, "RETURN: Invalid chat or group chat (Old Format)")
            return

        content_type, content_text, media_url, media_mimetype, media_filename = _extract_content_type(message_data)

        sender_name = message_data.get("pushName", "")
        sender_phone = chat_id.replace("@s.whatsapp.net", "").replace("@g.us", "")
    else:
        # Unknown event type
        await log_error_to_redis(
            redis_client,
            f"RETURN: Unknown event type: {payload.get('EventType')} / {payload.get('event')}",
        )
        return

    # Get caption if available
    caption = None
    if content_type in ("image", "video", "document"):
        caption = content_text or None
        if not content_text:
            content_text = f"[{content_type.upper()}]"

    instance_token = _resolve_uazapi_instance_token(payload, event)
    inst_name = payload.get("instanceName") or payload.get("instance_name") or ""

    await log_error_to_redis(
        redis_client,
        f"Inbox resolve: token={bool(instance_token)}, instanceName={inst_name}",
    )

    inbox_row = find_inbox_by_instance_token(supabase_client, instance_token or "")
    if not inbox_row and inst_name:
        inbox_row = find_inbox_by_instance_name(supabase_client, str(inst_name))
    legacy_tenant_id: str | None = None
    if not inbox_row and instance_token:
        legacy_tenant_id = find_legacy_tenant_id_for_token(supabase_client, instance_token)
    if not inbox_row and legacy_tenant_id:
        inbox_row = find_inbox_for_tenant(supabase_client, legacy_tenant_id)

    await log_error_to_redis(
        redis_client,
        f"Inbox resolved: inbox={inbox_row['id'] if inbox_row else None}, legacy_tenant={legacy_tenant_id}",
    )

    lead_id = None
    lead_data: dict | None = None

    if inbox_row:
        lead_data = _find_existing_lead_for_inbox(supabase_client, inbox_row=inbox_row, chat_id=chat_id)
        if lead_data and not is_from_me:
            lead_data = maybe_spawn_inbound_whatsapp_lead_if_finalized(
                supabase_client,
                inbox_row=inbox_row,
                chat_id=chat_id,
                lead_data=lead_data,
            )
        if lead_data:
            lead_id = lead_data["id"]
    elif legacy_tenant_id:
        lead_data = _find_existing_lead_legacy_only(
            supabase_client,
            tenant_id=legacy_tenant_id,
            chat_id=chat_id,
        )
        if lead_data:
            lead_id = lead_data["id"]

    if not lead_data and not is_from_me:
        await log_error_to_redis(redis_client, "No lead data. Evaluating new lead creation (inbox obrigatório).")

        if not inbox_row:
            await log_structured_webhook(
                redis_client,
                {
                    "event": "webhook_skip_no_inbox",
                    "reason": "AC12_no_inbox_resolved",
                    "chat_id": chat_id,
                    "has_instance_token": bool(instance_token),
                    "legacy_tenant_found": bool(legacy_tenant_id),
                },
            )
            await log_error_to_redis(
                redis_client,
                "AC12: evento sem caixa (inbox) resolvível — não criar lead sem inbox_id/funnel_id.",
            )
        elif inbox_row:
            tenant_id = str(inbox_row["tenant_id"])
            funnel_id = str(inbox_row["funnel_id"])
            inbox_id = str(inbox_row["id"])

            stage_slug = get_first_stage_slug_for_funnel(
                supabase_client,
                tenant_id=tenant_id,
                funnel_id=funnel_id,
            )

            formatted_phone = ""
            if sender_phone:
                p = digits_only(sender_phone)
                # Legado: 55+DDD+8 dígitos sem o 9 inicial do celular
                if len(p) == 12 and p.startswith("55") and len(p) > 4 and p[4] in "6789":
                    p = p[:4] + "9" + p[4:]
                formatted_phone = format_brazil_phone_display(p) or p

            client_id = resolve_or_create_crm_client(
                supabase_client,
                tenant_id=tenant_id,
                sender_phone_raw=sender_phone,
                sender_name=sender_name,
            )

            new_lead: dict = {
                "tenant_id": tenant_id,
                "inbox_id": inbox_id,
                "funnel_id": funnel_id,
                "whatsapp_chat_id": chat_id,
                "contact_name": sender_name or sender_phone or "Desconhecido",
                "company_name": sender_name or sender_phone or "Novo Lead",
                "phone": formatted_phone or None,
                "stage": stage_slug,
                "value": 0,
            }
            if client_id:
                new_lead["client_id"] = client_id

            await log_error_to_redis(redis_client, f"Inserting lead: {new_lead}")
            try:
                lead_insert = supabase_client.table("leads").insert(new_lead).execute()
                if lead_insert.data:
                    lead_id = lead_insert.data[0]["id"]
                    lead_data = lead_insert.data[0]
                    await log_error_to_redis(
                        redis_client,
                        f"Created new Lead from Uazapi (inbox={inbox_id}): {lead_id}",
                    )
            except Exception as e:
                await log_error_to_redis(redis_client, f"Failed to create new lead: {e}")
                await log_structured_webhook(
                    redis_client,
                    {
                        "event": "webhook_lead_insert_failed",
                        "error": str(e),
                        "inbox_id": inbox_id,
                        "chat_id": chat_id,
                    },
                )
    elif is_from_me:
        await log_error_to_redis(redis_client, "is_from_me is True. Not creating lead.")
    else:
        await log_error_to_redis(redis_client, "Lead already exists!")

    # Save the message to chat_messages table
    try:
        message_record = {
            "whatsapp_chat_id": chat_id,
            "whatsapp_message_id": msg_id,
            "lead_id": lead_id,
            "tenant_id": lead_data.get("tenant_id") if lead_data else None,
            "direction": "outgoing" if is_from_me else "incoming",
            "content_type": content_type,
            "content": content_text,
            "media_url": media_url,
            "media_mimetype": media_mimetype,
            "media_filename": media_filename,
            "caption": caption,
            "sender_name": sender_name,
            "sender_phone": sender_phone,
            "metadata": {"type": "v2_webhook"},
        }
        # Remove None values
        message_record = {k: v for k, v in message_record.items() if v is not None}
        supabase_client.table("chat_messages").insert(message_record).execute()
    except Exception as e:
        await log_error_to_redis(redis_client, f"Failed to save message: {e}")

    # Only analyze incoming text messages for keyword detection
    if is_from_me or content_type != "text" or not content_text:
        return

    if not lead_id or not lead_data:
        return

    # Load rules from DB and run keyword engine
    try:
        rules = await keyword_engine.load_rules_from_db(supabase_client)
        suggested_stage = keyword_engine.analyze_message(content_text, rules)

        if not suggested_stage:
            return

        current_stage = (lead_data.get("stage") or "").strip()
        if suggested_stage != current_stage:
            supabase_client.table("leads").update({"stage": suggested_stage}).eq("id", lead_data["id"]).execute()
            await log_error_to_redis(
                redis_client,
                f"Lead {lead_data['id']} moved: {current_stage} -> {suggested_stage}",
            )
    except Exception as e:
        await log_error_to_redis(redis_client, f"Failed keyword engine / moving lead: {e}")


def _verify_chatwoot_signature(secret: str, timestamp: str, raw_body: str, signature: str) -> bool:
    import hashlib
    import hmac

    try:
        mac = hmac.new(secret.encode(), f"{timestamp}.{raw_body}".encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(f"sha256={mac}", signature or "")
    except Exception:
        return False


def _chatwoot_message_content(payload: dict):
    """(content_type, content, media_url, media_mimetype, media_filename) — midia vem em attachments[]."""
    content = payload.get("content")
    atts = payload.get("attachments")
    if not atts:
        conv = payload.get("conversation") or {}
        msgs = conv.get("messages") if isinstance(conv, dict) else None
        if isinstance(msgs, list) and msgs:
            atts = msgs[0].get("attachments")
    if isinstance(atts, list) and atts:
        att = atts[0]
        ft = str(att.get("file_type") or "").lower()
        mapping = {"image": "image", "audio": "audio", "video": "video", "file": "document"}
        return mapping.get(ft, "document"), content, att.get("data_url"), None, None
    return "text", content, None, None, None


def _chatwoot_chat_id(sender: dict, contact_inbox) -> str:
    ident = sender.get("identifier") if isinstance(sender, dict) else None
    if ident:
        return str(ident)
    src = None
    if isinstance(contact_inbox, dict):
        src = contact_inbox.get("source_id")
    if not src and isinstance(sender, dict) and sender.get("phone_number"):
        src = digits_only(str(sender.get("phone_number")))
    return f"{src}@s.whatsapp.net" if src else ""


def _chatwoot_label_change(payload: dict):
    ca = payload.get("changed_attributes")
    if isinstance(ca, list):
        for item in ca:
            if isinstance(item, dict) and "label_list" in item:
                ll = item.get("label_list") or {}
                return (ll.get("current_value") or [], ll.get("previous_value") or [])
    return (None, None)


async def _chatwoot_handle_message(payload, inbox_row, supabase_client, redis_client):
    conv = payload.get("conversation") or {}
    conversation_id = conv.get("id") or payload.get("conversation_id")
    message_type = str(payload.get("message_type") or "incoming")
    is_outgoing = message_type == "outgoing"
    sender = payload.get("sender") or {}
    sender_phone = str(sender.get("phone_number") or "").lstrip("+")
    sender_name = str(sender.get("name") or "")
    contact_inbox = conv.get("contact_inbox") if isinstance(conv, dict) else None
    chat_id = _chatwoot_chat_id(sender, contact_inbox)
    source_id = payload.get("source_id")
    whatsapp_message_id = str(source_id or payload.get("id") or "")
    content_type, content, media_url, media_mimetype, media_filename = _chatwoot_message_content(payload)
    caption = content if content_type != "text" else None

    if not chat_id:
        await log_error_to_redis(redis_client, "Chatwoot: sem chat_id; ignorando mensagem.")
        return

    if whatsapp_message_id:
        try:
            ex = (
                supabase_client.table("chat_messages")
                .select("id")
                .eq("whatsapp_message_id", whatsapp_message_id)
                .limit(1)
                .execute()
            )
            if ex.data:
                return
        except Exception:
            pass

    lead_data = _find_existing_lead_for_inbox(supabase_client, inbox_row=inbox_row, chat_id=chat_id)
    lead_id = lead_data["id"] if lead_data else None

    if not lead_data and not is_outgoing:
        tenant_id = str(inbox_row["tenant_id"])
        funnel_id = str(inbox_row["funnel_id"])
        inbox_id = str(inbox_row["id"])
        stage_slug = get_first_stage_slug_for_funnel(supabase_client, tenant_id=tenant_id, funnel_id=funnel_id)
        formatted_phone = ""
        if sender_phone:
            pdig = digits_only(sender_phone)
            formatted_phone = format_brazil_phone_display(pdig) or pdig
        client_id = resolve_or_create_crm_client(
            supabase_client, tenant_id=tenant_id, sender_phone_raw=sender_phone, sender_name=sender_name
        )
        new_lead = {
            "tenant_id": tenant_id,
            "inbox_id": inbox_id,
            "funnel_id": funnel_id,
            "whatsapp_chat_id": chat_id,
            "contact_name": sender_name or sender_phone or "Desconhecido",
            "company_name": sender_name or sender_phone or "Novo Lead",
            "phone": formatted_phone or None,
            "stage": stage_slug,
            "value": 0,
        }
        if client_id:
            new_lead["client_id"] = client_id
        try:
            ins = supabase_client.table("leads").insert(new_lead).execute()
            if ins.data:
                lead_data = ins.data[0]
                lead_id = lead_data["id"]
                await log_error_to_redis(redis_client, f"Chatwoot: lead criado (inbox={inbox_id}): {lead_id}")
        except Exception as e:
            await log_error_to_redis(redis_client, f"Chatwoot: falha ao criar lead: {e}")

    message_record = {
        "whatsapp_chat_id": chat_id,
        "whatsapp_message_id": whatsapp_message_id or None,
        "lead_id": lead_id,
        "tenant_id": lead_data.get("tenant_id") if lead_data else str(inbox_row["tenant_id"]),
        "direction": "outgoing" if is_outgoing else "incoming",
        "content_type": content_type,
        "content": content,
        "media_url": media_url,
        "media_mimetype": media_mimetype,
        "media_filename": media_filename,
        "caption": caption,
        "sender_name": sender_name,
        "sender_phone": sender_phone,
        "external_provider": "chatwoot",
        "external_conversation_id": str(conversation_id) if conversation_id is not None else None,
        "metadata": {"source": "chatwoot", "message_type": message_type},
    }
    message_record = {k: v for k, v in message_record.items() if v is not None}
    try:
        supabase_client.table("chat_messages").insert(message_record).execute()
    except Exception as e:
        await log_error_to_redis(redis_client, f"Chatwoot: falha ao salvar mensagem: {e}")


async def _chatwoot_handle_conversation(payload, inbox_row, supabase_client, redis_client):
    evt = payload.get("event")
    if evt == "conversation_created":
        current = payload.get("labels") or []
        previous = []
    else:
        current, previous = _chatwoot_label_change(payload)
        if current is None:
            return
    added = [lbl for lbl in current if lbl not in previous]
    if added:
        target_label = added[-1]
    elif len(current) == 1:
        target_label = current[0]
    else:
        return

    meta = payload.get("meta") or {}
    sender = meta.get("sender") or {}
    contact_inbox = payload.get("contact_inbox")
    chat_id = _chatwoot_chat_id(sender, contact_inbox)
    if not chat_id:
        return
    lead_data = _find_existing_lead_for_inbox(supabase_client, inbox_row=inbox_row, chat_id=chat_id)
    if not lead_data:
        await log_error_to_redis(
            redis_client, f"Chatwoot: etiqueta '{target_label}' sem lead correspondente ({chat_id})."
        )
        return

    tenant_id = str(inbox_row["tenant_id"])
    funnel_id = str(inbox_row["funnel_id"])
    stage_name = ensure_stage_for_label(supabase_client, tenant_id=tenant_id, funnel_id=funnel_id, label=target_label)
    current_stage = (lead_data.get("stage") or "").strip()
    if stage_name and stage_name != current_stage:
        try:
            supabase_client.table("leads").update({"stage": stage_name}).eq("id", lead_data["id"]).execute()
            await log_error_to_redis(
                redis_client, f"Chatwoot: lead {lead_data['id']} movido {current_stage} -> {stage_name}"
            )
        except Exception as e:
            await log_error_to_redis(redis_client, f"Chatwoot: falha ao mover lead: {e}")


async def process_chatwoot_event(event, supabase_client, redis_client):
    """Processa um evento do webhook do Chatwoot (message_created / conversation_updated)."""
    payload = event.get("payload", {})
    evt = payload.get("event")
    account_id, cw_inbox_id = _chatwoot_ids(payload)
    inbox_row = find_inbox_by_chatwoot(supabase_client, account_id, cw_inbox_id)
    if not inbox_row:
        await log_structured_webhook(
            redis_client,
            {
                "event": "chatwoot_skip_no_inbox",
                "account_id": account_id,
                "chatwoot_inbox_id": cw_inbox_id,
                "cw_event": evt,
            },
        )
        return

    cfg = inbox_row.get("chatwoot_settings") or {}
    secret = cfg.get("webhook_secret") if isinstance(cfg, dict) else None
    if secret and event.get("signature") and event.get("timestamp") and event.get("raw_body") is not None:
        if not _verify_chatwoot_signature(secret, event["timestamp"], event["raw_body"], event["signature"]):
            await log_error_to_redis(redis_client, "Chatwoot: assinatura HMAC invalida — evento ignorado.")
            return

    if evt == "message_created":
        await _chatwoot_handle_message(payload, inbox_row, supabase_client, redis_client)
    elif evt in ("conversation_updated", "conversation_created"):
        await _chatwoot_handle_conversation(payload, inbox_row, supabase_client, redis_client)
    else:
        await log_error_to_redis(redis_client, f"Chatwoot: evento ignorado: {evt}")


async def worker_loop():
    """Main worker loop — continuously reads from Redis queue."""
    settings = get_settings()
    redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)

    from supabase import create_client

    supabase_client = create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)

    await log_error_to_redis(redis_client, "Webhook processor worker started properly.")

    while True:
        try:
            result = await redis_client.blpop("neurix:webhook_queue", timeout=5)
            if result is None:
                continue

            _, raw_event = result
            event = json.loads(raw_event)
            source = event.get("source", "unknown")

            if source == "uazapi":
                await process_uazapi_event(event, supabase_client, redis_client)
            elif source == "chatwoot":
                await process_chatwoot_event(event, supabase_client, redis_client)
            elif source == "invoice":
                pass
            else:
                await log_error_to_redis(redis_client, f"Unknown webhook source: {source}")

        except Exception as e:
            await log_error_to_redis(redis_client, f"Worker loop error: {e}")
            await asyncio.sleep(2)


if __name__ == "__main__":
    asyncio.run(worker_loop())
