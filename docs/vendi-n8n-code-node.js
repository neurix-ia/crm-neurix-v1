/**
 * Trecho para colar no n8n (Code node) antes do HTTP Request → CRM.
 * Entrada: Consolidar Registro / Preparar Registro Final / Normalizar Dados.
 *
 * Ajuste TENANT_ID via $env.VENDI_TENANT_ID.
 */

function digitsOnly(v) {
  return String(v || "").replace(/\D/g, "");
}

const base = $("Preparar Registro Final").first().json;
const typed = digitsOnly(base.cliente_whatsapp_digitado || "");
const fromAudio = digitsOnly(base.cliente_whatsapp_falado || "");
let phone_final = fromAudio || typed;
let match_status;
if (typed && fromAudio) {
  match_status = typed === fromAudio || (typed.length >= 8 && fromAudio.includes(typed.slice(-8)))
    ? "match"
    : "mismatch";
  if (base.numero_confere) match_status = "match";
} else if (fromAudio) match_status = "audio_only";
else if (typed) match_status = "typed_only";
else match_status = "no_phone";

if (!phone_final) phone_final = typed || fromAudio || "";

return [
  {
    json: {
      tenant_id: $env.VENDI_TENANT_ID,
      seller_name: base.vendedor || "vendedor",
      seller_user_id: null,
      phone_typed: typed || null,
      phone_from_audio: fromAudio || null,
      phone_final,
      match_status,
      transcript: base.transcricao || null,
      photo_url: null,
      audio_url: null,
      pao_italiano_qtd: Number(base.pao_italiano_qtd || 0),
      pao_integral_qtd: Number(base.pao_integral_qtd || 0),
      sold_at: base.timestamp_venda || new Date().toISOString(),
      geolocation: null,
      metadata: {
        source: "n8n-vendi",
        placa: base.placa || null,
        twenty_person_id: base.twenty_person_id || null,
      },
      client_display_name: null,
    },
  },
];
