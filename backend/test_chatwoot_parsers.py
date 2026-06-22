"""
Testes dos parsers do webhook Chatwoot (Fase 3).
Payloads baseados em eventos reais capturados (conta 2, inbox 65).
Funções puras — não tocam banco.
"""

from app.services.webhook_lead_context import _chatwoot_ids
from app.workers.webhook_processor import (
    _chatwoot_chat_id,
    _chatwoot_label_change,
    _chatwoot_message_content,
)

MSG_TEXT = {
    "event": "message_created",
    "account": {"id": 2},
    "inbox": {"id": 65},
    "content": "oi",
    "message_type": "incoming",
    "source_id": "wamid.AAA",
    "conversation": {"id": 2113, "inbox_id": 65, "contact_inbox": {"source_id": "554197889864"}},
    "sender": {"phone_number": "+554197889864", "name": "Augusto", "identifier": "554197889864@s.whatsapp.net"},
}

MSG_IMG = {
    "event": "message_created",
    "account": {"id": 2},
    "inbox": {"id": 65},
    "content": None,
    "message_type": "incoming",
    "conversation": {"id": 2000, "inbox_id": 65},
    "sender": {"phone_number": "+554195802989", "identifier": "554195802989@s.whatsapp.net"},
    "attachments": [{"file_type": "image", "data_url": "https://cw/File.jpg"}],
}

MSG_AUDIO = {
    "event": "message_created",
    "account": {"id": 2},
    "inbox": {"id": 65},
    "content": None,
    "message_type": "incoming",
    "conversation": {"id": 2000, "inbox_id": 65},
    "sender": {"phone_number": "+554195802989", "identifier": "554195802989@s.whatsapp.net"},
    "attachments": [{"file_type": "audio", "data_url": "https://cw/File.ogg"}],
}

CONV_LABEL_ADD = {
    "event": "conversation_updated",
    "inbox_id": 65,
    "id": 2113,
    "messages": [{"account_id": 2}],
    "labels": ["01-interessado", "02-demo-agendada"],
    "meta": {"sender": {"identifier": "554197889864@s.whatsapp.net"}},
    "changed_attributes": [
        {"updated_at": {"previous_value": "a", "current_value": "b"}},
        {"label_list": {"previous_value": ["01-interessado"], "current_value": ["01-interessado", "02-demo-agendada"]}},
    ],
}

CONV_NOISE = {
    "event": "conversation_updated",
    "inbox_id": 65,
    "id": 2113,
    "messages": [{"account_id": 2}],
    "changed_attributes": [{"waiting_since": {"previous_value": None, "current_value": "x"}}],
}


def test_ids_from_message_created():
    assert _chatwoot_ids(MSG_TEXT) == ("2", "65")


def test_ids_from_conversation_updated_without_account_obj():
    # conversation_updated nao traz "account"; account_id vem de messages[].account_id
    assert _chatwoot_ids(CONV_LABEL_ADD) == ("2", "65")


def test_content_text():
    assert _chatwoot_message_content(MSG_TEXT) == ("text", "oi", None, None, None)


def test_content_image_by_attachment_filetype():
    # content_type do Chatwoot continua "text"; tipo real vem de attachments[].file_type
    assert _chatwoot_message_content(MSG_IMG) == ("image", None, "https://cw/File.jpg", None, None)


def test_content_audio_by_attachment_filetype():
    assert _chatwoot_message_content(MSG_AUDIO) == ("audio", None, "https://cw/File.ogg", None, None)


def test_chat_id_prefers_identifier():
    chat_id = _chatwoot_chat_id(MSG_TEXT["sender"], MSG_TEXT["conversation"]["contact_inbox"])
    assert chat_id == "554197889864@s.whatsapp.net"


def test_label_change_diff():
    current, previous = _chatwoot_label_change(CONV_LABEL_ADD)
    assert current == ["01-interessado", "02-demo-agendada"]
    assert previous == ["01-interessado"]
    added = [lbl for lbl in current if lbl not in previous]
    assert added[-1] == "02-demo-agendada"


def test_conversation_updated_without_label_change_is_noop():
    assert _chatwoot_label_change(CONV_NOISE) == (None, None)
