/**
 * Trecho para colar no n8n (Code node) antes do HTTP Request → CRM.
 * Entrada esperada: campos do webhook vendi + transcript + URLs já resolvidas.
 *
 * Ajuste TENANT_ID / mapeamento de campos conforme o workflow real.
 */

function digitsOnly(v) {
  return String(v || "").replace(/\D/g, "");
}

function extractPhoneFromTranscript(text) {
  if (!text) return "";
  const m = String(text).match(/(?:\+?55\s*)?(?:\(?\d{2}\)?\s*)?(?:9?\d{4})[\s-]?\d{4}/);
  return m ? digitsOnly(m[0]) : "";
}

const item = $input.first().json;
const typed = digitsOnly(item.cliente_whatsapp_digitado || item.phone_typed || "");
const fromAudio = digitsOnly(item.phone_from_audio || extractPhoneFromTranscript(item.transcript));
let phone_final = digitsOnly(item.phone_final || "");
let match_status = item.match_status;

if (!phone_final) {
  phone_final = fromAudio || typed;
}

if (!match_status) {
  if (typed && fromAudio) match_status = typed === fromAudio ? "match" : "mismatch";
  else if (fromAudio) match_status = "audio_only";
  else if (typed) match_status = "typed_only";
  else match_status = "no_phone";
}

return [
  {
    json: {
      tenant_id: item.tenant_id || $env.VENDI_TENANT_ID,
      seller_name: item.vendedor || item.seller_name || "vendedor",
      seller_user_id: item.seller_user_id || null,
      phone_typed: typed || null,
      phone_from_audio: fromAudio || null,
      phone_final,
      match_status,
      transcript: item.transcript || null,
      photo_url: item.photo_url || null,
      audio_url: item.audio_url || null,
      pao_italiano_qtd: Number(item.pao_italiano_qtd || 0),
      pao_integral_qtd: Number(item.pao_integral_qtd || 0),
      sold_at: item.timestamp || item.sold_at || new Date().toISOString(),
      geolocation: item.geolocalizacao || item.geolocation || null,
      metadata: { source: "n8n-vendi" },
      client_display_name: item.client_display_name || null,
    },
  },
];
