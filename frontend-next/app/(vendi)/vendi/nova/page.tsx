"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { getAuthMe, getVendiWebhookUrl } from "@/lib/api";

type Qtys = { italiano: number; integral: number };

function blobToBase64(blob: Blob): Promise<string> {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onloadend = () => {
            const result = String(reader.result || "");
            const parts = result.split(",");
            resolve(parts[1] || "");
        };
        reader.onerror = reject;
        reader.readAsDataURL(blob);
    });
}

/** Reduz foto da câmera para payload menor no webhook n8n. */
async function compressImageFile(file: File, maxSide = 1280, quality = 0.72): Promise<Blob> {
    const bitmap = await createImageBitmap(file);
    const scale = Math.min(1, maxSide / Math.max(bitmap.width, bitmap.height));
    const w = Math.max(1, Math.round(bitmap.width * scale));
    const h = Math.max(1, Math.round(bitmap.height * scale));
    const canvas = document.createElement("canvas");
    canvas.width = w;
    canvas.height = h;
    const ctx = canvas.getContext("2d");
    if (!ctx) {
        bitmap.close();
        return file;
    }
    ctx.drawImage(bitmap, 0, 0, w, h);
    bitmap.close();
    const blob = await new Promise<Blob | null>((resolve) =>
        canvas.toBlob((b) => resolve(b), "image/jpeg", quality)
    );
    return blob || file;
}

export default function VendiNovaVendaPage() {
    const router = useRouter();
    const [vendedor, setVendedor] = useState("");
    const [authReady, setAuthReady] = useState(false);
    const [whatsapp, setWhatsapp] = useState("");
    const [quantidades, setQuantidades] = useState<Qtys>({ italiano: 0, integral: 0 });
    const [gravando, setGravando] = useState(false);
    const [timer, setTimer] = useState("00:00");
    const [recStatus, setRecStatus] = useState("Toque pra começar a gravar");
    const [fotoPreview, setFotoPreview] = useState<string | null>(null);
    const [hasAudio, setHasAudio] = useState(false);
    const [sending, setSending] = useState(false);
    const [toast, setToast] = useState<{ msg: string; error?: boolean } | null>(null);

    const mediaRecorder = useRef<MediaRecorder | null>(null);
    const mediaStream = useRef<MediaStream | null>(null);
    const audioChunks = useRef<Blob[]>([]);
    const audioBlob = useRef<Blob | null>(null);
    const fotoBlob = useRef<Blob | null>(null);
    const recStart = useRef<number | null>(null);
    const timerInterval = useRef<ReturnType<typeof setInterval> | null>(null);
    const fotoInputRef = useRef<HTMLInputElement>(null);

    useEffect(() => {
        (async () => {
            try {
                const me = await getAuthMe();
                setVendedor(me.full_name || me.email || "Vendedor");
                setAuthReady(true);
            } catch {
                router.replace("/login?redirect=/vendi/nova");
            }
        })();
    }, [router]);

    const showToast = (msg: string, error = false) => {
        setToast({ msg, error });
        setTimeout(() => setToast(null), 4000);
    };

    const alterarQtd = (tipo: keyof Qtys, delta: number) => {
        setQuantidades((q) => ({ ...q, [tipo]: Math.max(0, q[tipo] + delta) }));
    };

    const pararGravacao = useCallback(() => {
        if (mediaRecorder.current && mediaRecorder.current.state !== "inactive") {
            mediaRecorder.current.stop();
            mediaStream.current?.getTracks().forEach((t) => t.stop());
        }
        setGravando(false);
        if (timerInterval.current) clearInterval(timerInterval.current);
        setRecStatus("Gravação encerrada. Toque pra gravar de novo");
    }, []);

    const toggleGravacao = async () => {
        if (!gravando) {
            try {
                mediaStream.current = await navigator.mediaDevices.getUserMedia({ audio: true });
            } catch {
                showToast("Não consegui acessar o microfone", true);
                return;
            }
            audioChunks.current = [];
            const mr = new MediaRecorder(mediaStream.current);
            mediaRecorder.current = mr;
            mr.ondataavailable = (e) => {
                if (e.data.size > 0) audioChunks.current.push(e.data);
            };
            mr.onstop = () => {
                audioBlob.current = new Blob(audioChunks.current, { type: "audio/webm" });
                setHasAudio(audioBlob.current.size > 0);
            };
            mr.start();
            setGravando(true);
            recStart.current = Date.now();
            setRecStatus("Gravando... toque pra parar");
            timerInterval.current = setInterval(() => {
                const s = Math.floor((Date.now() - (recStart.current || Date.now())) / 1000);
                const mm = String(Math.floor(s / 60)).padStart(2, "0");
                const ss = String(s % 60).padStart(2, "0");
                setTimer(`${mm}:${ss}`);
            }, 500);
        } else {
            pararGravacao();
        }
    };

    const onFoto = async (file: File | undefined) => {
        if (!file) return;
        try {
            const compressed = await compressImageFile(file);
            fotoBlob.current = compressed;
            const reader = new FileReader();
            reader.onload = (e) => setFotoPreview(String(e.target?.result || ""));
            reader.readAsDataURL(compressed);
        } catch {
            showToast("Não consegui processar a foto. Tenta de novo.", true);
        }
    };

    const resetVenda = () => {
        audioBlob.current = null;
        fotoBlob.current = null;
        audioChunks.current = [];
        setHasAudio(false);
        setGravando(false);
        setQuantidades({ italiano: 0, integral: 0 });
        setTimer("00:00");
        setRecStatus("Toque pra começar a gravar");
        setWhatsapp("");
        setFotoPreview(null);
        if (fotoInputRef.current) fotoInputRef.current.value = "";
    };

    const enviar = async () => {
        if (gravando) {
            pararGravacao();
            // espera onstop gravar o blob
            await new Promise((r) => setTimeout(r, 350));
        }
        const numero = whatsapp.trim();
        const temProduto = quantidades.italiano + quantidades.integral > 0;
        if (numero.replace(/\D/g, "").length < 8 || !temProduto) {
            showToast("Informe WhatsApp do cliente e pelo menos 1 produto", true);
            return;
        }
        setSending(true);
        try {
            const payload = {
                vendedor,
                cliente_whatsapp_digitado: numero,
                pao_italiano_qtd: quantidades.italiano,
                pao_integral_qtd: quantidades.integral,
                foto_base64: fotoBlob.current ? await blobToBase64(fotoBlob.current) : "",
                foto_mime: "image/jpeg",
                audio_base64: audioBlob.current ? await blobToBase64(audioBlob.current) : null,
                audio_mime: audioBlob.current ? audioBlob.current.type || "audio/webm" : null,
                timestamp: new Date().toISOString(),
                geolocalizacao: null as null,
            };
            const resp = await fetch(getVendiWebhookUrl(), {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
            });
            if (!resp.ok) {
                const body = await resp.text().catch(() => "");
                throw new Error(body || `HTTP ${resp.status}`);
            }
            showToast("Venda registrada!");
            resetVenda();
        } catch (e) {
            const detail = e instanceof Error && e.message ? e.message.slice(0, 120) : "";
            showToast(detail ? `Erro ao enviar: ${detail}` : "Erro ao enviar. Tenta de novo.", true);
        } finally {
            setSending(false);
        }
    };

    if (!authReady) {
        return (
            <div className="min-h-screen flex items-center justify-center bg-[#1a1410] text-[#f5ece0]">
                Carregando…
            </div>
        );
    }

    const canSend =
        whatsapp.trim().replace(/\D/g, "").length >= 8 && quantidades.italiano + quantidades.integral > 0;

    return (
        <div className="min-h-screen bg-[#1a1410] text-[#f5ece0] flex flex-col font-sans">
            <div className="flex-1 flex flex-col p-5 max-w-lg mx-auto w-full">
                <div className="flex justify-between items-center mb-5">
                    <div className="text-sm text-[#b8a892]">👤 {vendedor}</div>
                    <div className="flex gap-3 items-center">
                        <Link href="/vendi" className="text-sm text-[#d98e3c]">
                            painel
                        </Link>
                        <button
                            type="button"
                            className="text-sm text-[#d98e3c]"
                            onClick={() => {
                                localStorage.removeItem("access_token");
                                localStorage.removeItem("refresh_token");
                                router.push("/login");
                            }}
                        >
                            sair
                        </button>
                    </div>
                </div>

                <h1 className="text-xl font-bold m-0">Nova venda</h1>
                <p className="text-sm text-[#b8a892] mb-6">
                    Áudio e foto são opcionais e em qualquer ordem. Precisa de WhatsApp + pelo menos 1 produto.
                </p>

                <button
                    type="button"
                    onClick={() => void toggleGravacao()}
                    className="flex flex-col items-center gap-3 py-7 px-4 rounded-2xl bg-[#2a221a] mb-4 active:bg-[#35291c]"
                >
                    <div
                        className={`w-[76px] h-[76px] rounded-full bg-[#c0392b] flex items-center justify-center text-3xl ${
                            gravando ? "animate-pulse" : ""
                        }`}
                    >
                        🎙️
                    </div>
                    <div className="text-xl font-bold tabular-nums">{timer}</div>
                    <div className="text-sm text-[#b8a892]">
                        {recStatus}
                        {hasAudio && !gravando ? " · áudio ok" : ""}
                    </div>
                </button>

                <label className="text-xs text-[#b8a892] mb-1 block">WhatsApp do cliente</label>
                <input
                    type="tel"
                    inputMode="tel"
                    value={whatsapp}
                    onChange={(e) => setWhatsapp(e.target.value)}
                    placeholder="(41) 99999-9999"
                    className="w-full p-3.5 rounded-[10px] border border-[#4a3f30] bg-[#2a221a] text-[#f5ece0] text-base mb-3 outline-none"
                />

                <label className="text-xs text-[#b8a892] mb-1 block">Foto da placa (opcional)</label>
                <button
                    type="button"
                    onClick={() => fotoInputRef.current?.click()}
                    className={`border-2 border-dashed border-[#4a3f30] rounded-xl text-center text-[#b8a892] mb-1 w-full ${
                        fotoPreview ? "p-2" : "p-5"
                    }`}
                >
                    {fotoPreview ? (
                        // eslint-disable-next-line @next/next/no-img-element
                        <img src={fotoPreview} alt="Placa" className="max-w-full rounded-lg mx-auto block" />
                    ) : (
                        "📷 Toque pra tirar a foto da placa"
                    )}
                </button>
                <input
                    ref={fotoInputRef}
                    type="file"
                    accept="image/*"
                    capture="environment"
                    className="hidden"
                    onChange={(e) => void onFoto(e.target.files?.[0])}
                />
                <p className="text-xs text-[#b8a892] mb-4">
                    Pode tirar a foto antes ou depois do áudio — não interrompe a gravação.
                </p>

                <label className="text-xs text-[#b8a892] mb-2 block">Produtos</label>
                {(
                    [
                        ["italiano", "🍞 Pão Italiano"],
                        ["integral", "🌾 Pão Integral"],
                    ] as const
                ).map(([key, label]) => (
                    <div
                        key={key}
                        className={`flex items-center justify-between bg-[#2a221a] rounded-xl px-3.5 py-3 mb-2 ${
                            quantidades[key] > 0 ? "border border-[#d98e3c]" : ""
                        }`}
                    >
                        <div className="font-semibold text-[15px]">{label}</div>
                        <div className="flex items-center gap-1">
                            <button
                                type="button"
                                onClick={() => alterarQtd(key, -1)}
                                className="w-10 h-10 rounded-full border border-[#4a3f30] bg-[#1a1410] text-xl font-bold"
                            >
                                −
                            </button>
                            <span className="min-w-[32px] text-center text-lg font-bold">{quantidades[key]}</span>
                            <button
                                type="button"
                                onClick={() => alterarQtd(key, 1)}
                                className="w-10 h-10 rounded-full bg-[#d98e3c] text-[#1a1410] text-xl font-bold border border-[#d98e3c]"
                            >
                                +
                            </button>
                        </div>
                    </div>
                ))}

                <button
                    type="button"
                    disabled={!canSend || sending}
                    onClick={() => void enviar()}
                    className="w-full mt-4 py-4 rounded-[10px] bg-[#d98e3c] text-[#1a1410] text-base font-semibold disabled:opacity-40"
                >
                    {sending ? "Enviando…" : "Registrar venda"}
                </button>
            </div>

            {toast && (
                <div
                    className={`fixed bottom-5 left-5 right-5 text-center font-semibold py-3.5 rounded-[10px] z-50 ${
                        toast.error ? "bg-[#c0392b]" : "bg-[#4a9c5d]"
                    } text-white`}
                >
                    {toast.msg}
                </div>
            )}
        </div>
    );
}
