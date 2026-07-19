"use client";

import { useState, useEffect, useRef } from "react";
import { supabase } from "@/lib/supabase";
import { getApiUrl } from "@/lib/api";

interface WhatsAppMessage {
    id: string;
    messageid?: string;
    content: any;
    body?: string;
    text?: string;
    messageType: string;
    status: string;
    owner: string;
    messageTimestamp: number;
    fromMe?: boolean;
    key?: {
        fromMe: boolean;
        id: string;
    };
    pushName?: string;
}

interface WhatsAppChatProps {
    leadId: string;
    leadName: string;
    onClose: () => void;
}

export default function WhatsAppChat({ leadId, leadName, onClose }: WhatsAppChatProps) {
    const [messages, setMessages] = useState<WhatsAppMessage[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState("");
    const [inputText, setInputText] = useState("");
    const [sending, setSending] = useState(false);
    const [showAttachMenu, setShowAttachMenu] = useState(false);
    const [uploadingFile, setUploadingFile] = useState(false);
    const messagesEndRef = useRef<HTMLDivElement>(null);
    const fileInputRef = useRef<HTMLInputElement>(null);
    const attachMenuRef = useRef<HTMLDivElement>(null);

    useEffect(() => {
        loadHistory();
    }, [leadId]);

    useEffect(() => {
        if (messagesEndRef.current) {
            messagesEndRef.current.scrollIntoView({ behavior: "auto" });
        }
    }, [messages]);

    // Close attach menu on outside click
    useEffect(() => {
        function handleOutsideClick(e: MouseEvent) {
            if (attachMenuRef.current && !attachMenuRef.current.contains(e.target as Node)) {
                setShowAttachMenu(false);
            }
        }
        document.addEventListener("mousedown", handleOutsideClick);
        return () => document.removeEventListener("mousedown", handleOutsideClick);
    }, []);

    async function loadHistory() {
        setLoading(true);
        setError("");
        try {
            const { data: { session } } = await supabase.auth.getSession();
            const token = session?.access_token;
            if (!token) throw new Error("Não autenticado");

            const res = await fetch(getApiUrl(`/api/leads/${leadId}/chat-history`), {
                headers: { "Authorization": `Bearer ${token}` }
            });

            if (!res.ok) {
                const errData = await res.json().catch(() => ({}));
                throw new Error(errData.detail || "Erro ao carregar histórico");
            }

            const data = await res.json();
            const msgs = data.messages || [];
            if (msgs.length > 1 && msgs[0].messageTimestamp > msgs[msgs.length - 1].messageTimestamp) {
                msgs.reverse();
            }
            setMessages(msgs);
        } catch (err: any) {
            console.error("Erro ao carregar chat:", err);
            setError(err.message);
        } finally {
            setLoading(false);
        }
    }

    async function handleSend(e: React.FormEvent) {
        e.preventDefault();
        if (!inputText.trim() || sending) return;

        setSending(true);
        const textToSend = inputText;
        setInputText("");

        try {
            const { data: { session } } = await supabase.auth.getSession();
            const token = session?.access_token;

            const res = await fetch(getApiUrl(`/api/leads/${leadId}/messages/send`), {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "Authorization": `Bearer ${token}`
                },
                body: JSON.stringify({ text: textToSend })
            });

            if (!res.ok) {
                const errData = await res.json().catch(() => ({}));
                throw new Error(errData.detail || "Erro ao enviar mensagem");
            }

            await loadHistory();
        } catch (err: any) {
            console.error("Erro ao enviar:", err);
            alert(err.message);
            setInputText(textToSend);
        } finally {
            setSending(false);
        }
    }

    async function handleFileUpload(e: React.ChangeEvent<HTMLInputElement>) {
        const file = e.target.files?.[0];
        if (!file) return;

        setUploadingFile(true);
        setShowAttachMenu(false);

        try {
            const { data: { session } } = await supabase.auth.getSession();
            const token = session?.access_token;
            if (!token) throw new Error("Não autenticado");

            // Upload to Supabase Storage
            const ext = file.name.split('.').pop();
            const fileName = `chat-uploads/${Date.now()}-${Math.random().toString(36).slice(2)}.${ext}`;
            const { data: uploadData, error: uploadError } = await supabase.storage
                .from('uploads')
                .upload(fileName, file, { contentType: file.type });

            if (uploadError) throw new Error("Falha no upload: " + uploadError.message);

            const { data: urlData } = supabase.storage.from('uploads').getPublicUrl(fileName);
            const publicUrl = urlData.publicUrl;

            // Determine media type
            let mediaType = 'document';
            if (file.type.startsWith('image/')) mediaType = 'image';
            else if (file.type.startsWith('video/')) mediaType = 'video';
            else if (file.type.startsWith('audio/')) mediaType = 'audio';

            // Send via API
            const res = await fetch(getApiUrl(`/api/leads/${leadId}/messages/send`), {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "Authorization": `Bearer ${token}`
                },
                body: JSON.stringify({
                    text: inputText || undefined,
                    file_url: publicUrl,
                    media_type: mediaType,
                    file_name: file.name,
                })
            });

            if (!res.ok) {
                const errData = await res.json().catch(() => ({}));
                throw new Error(errData.detail || "Erro ao enviar arquivo");
            }

            setInputText("");
            await loadHistory();
        } catch (err: any) {
            console.error("Erro no upload:", err);
            alert(err.message);
        } finally {
            setUploadingFile(false);
            if (fileInputRef.current) fileInputRef.current.value = "";
        }
    }

    const formatTime = (ts: number | string) => {
        if (!ts) return "";
        const date = new Date(Number(ts));
        if (ts.toString().length <= 10) date.setTime(Number(ts) * 1000);
        return date.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
    };

    const getMessageText = (msg: WhatsAppMessage) => {
        if (msg.text) return msg.text;
        if (msg.body) return msg.body;
        if (typeof msg.content === 'string') return msg.content;
        if (msg.content && msg.content.text) return msg.content.text;
        return `[${msg.messageType || "Mensagem"}]`;
    };

    const isFromMe = (msg: WhatsAppMessage) => {
        if (msg.fromMe !== undefined) return msg.fromMe;
        if (msg.key && msg.key.fromMe !== undefined) return msg.key.fromMe;
        return msg.id?.startsWith("owner") || false;
    };

    const getMessageTypeIcon = (msg: WhatsAppMessage) => {
        const type = msg.messageType?.toLowerCase();
        if (type === 'image' || type === 'imageMessage') return '🖼️';
        if (type === 'video' || type === 'videoMessage') return '🎬';
        if (type === 'audio' || type === 'audioMessage' || type === 'ptt') return '🎤';
        if (type === 'document' || type === 'documentMessage') return '📎';
        if (type === 'sticker' || type === 'stickerMessage') return '🏷️';
        if (type === 'location' || type === 'locationMessage') return '📍';
        return null;
    };

    return (
        <div className="fixed inset-0 z-[60] flex items-center justify-center p-4 sm:p-6 bg-slate-900/50 backdrop-blur-md">
            <div className="bg-white dark:bg-[#111B21] w-full max-w-2xl h-[85vh] rounded-2xl shadow-2xl flex flex-col overflow-hidden relative border border-primary/20 dark:border-primary/30 ring-1 ring-primary/10">

                {/* Header — gradient with CRM primary */}
                <div className="px-4 py-3 flex items-center justify-between border-b border-primary/10 dark:border-primary/20 bg-primary">
                    <div className="flex items-center gap-3">
                        <div className="w-11 h-11 rounded-full bg-white/20 backdrop-blur-sm flex items-center justify-center ring-2 ring-white/30 overflow-hidden shrink-0">
                            <span className="material-symbols-outlined text-white text-xl">person</span>
                        </div>
                        <div>
                            <h3 className="font-bold text-white leading-tight truncate max-w-[300px]">{leadName}</h3>
                            <p className="text-xs text-rose-100 flex items-center gap-1">
                                <span className="w-2 h-2 bg-green-400 rounded-full inline-block animate-pulse"></span>
                                {loading ? "Conectando..." : messages.length > 0 ? `${messages.length} mensagens` : "Online"}
                            </p>
                        </div>
                    </div>
                    <div className="flex items-center gap-1">
                        <button onClick={loadHistory} disabled={loading}
                            className="p-2 text-white/80 hover:bg-white/10 rounded-full transition-colors"
                            title="Recarregar">
                            <span className={`material-symbols-outlined text-xl ${loading ? 'animate-spin' : ''}`}>refresh</span>
                        </button>
                        <button onClick={onClose}
                            className="p-2 text-white/80 hover:bg-white/10 rounded-full transition-colors">
                            <span className="material-symbols-outlined text-xl">close</span>
                        </button>
                    </div>
                </div>

                {/* Chat Area */}
                <div className="flex-1 overflow-y-auto p-4 space-y-3 relative"
                    style={{
                        background: 'linear-gradient(180deg, #fff1f2 0%, #f1f5f9 100%)',
                    }}>

                    {/* Subtle pattern overlay */}
                    <div className="absolute inset-0 opacity-[0.03] pointer-events-none"
                        style={{
                            backgroundImage: `radial-gradient(circle, #E11D48 1px, transparent 1px)`,
                            backgroundSize: '24px 24px',
                        }} />

                    {loading ? (
                        <div className="flex justify-center py-10 relative z-10">
                            <div className="flex items-center gap-3 bg-white/90 backdrop-blur-sm px-5 py-3 rounded-xl shadow-sm border border-primary/10">
                                <div className="animate-spin rounded-full h-5 w-5 border-2 border-primary border-t-transparent"></div>
                                <span className="text-sm text-text-secondary-light">Carregando histórico...</span>
                            </div>
                        </div>
                    ) : error ? (
                        <div className="flex justify-center py-10 relative z-10">
                            <div className="bg-red-50 border border-red-200 text-red-600 px-5 py-3 rounded-xl shadow-sm flex items-center gap-2">
                                <span className="material-symbols-outlined text-lg">error</span>
                                <span className="text-sm">{error}</span>
                                <button onClick={loadHistory} className="ml-2 text-xs underline hover:no-underline">Tentar novamente</button>
                            </div>
                        </div>
                    ) : messages.length === 0 ? (
                        <div className="flex justify-center py-10 relative z-10">
                            <div className="bg-gradient-to-r from-primary/5 to-rose-50 border border-primary/15 text-[#54656F] px-6 py-4 rounded-2xl shadow-sm text-center max-w-sm">
                                <span className="material-symbols-outlined text-3xl text-primary/40 block mb-2">forum</span>
                                <p className="text-sm font-medium">Nenhuma mensagem encontrada</p>
                                <p className="text-xs text-text-secondary-light mt-1">As mensagens do WhatsApp aparecerão aqui</p>
                            </div>
                        </div>
                    ) : (
                        messages.map((msg, i) => {
                            const me = isFromMe(msg);
                            const typeIcon = getMessageTypeIcon(msg);
                            return (
                                <div key={msg.id || i} className={`flex ${me ? "justify-end" : "justify-start"} relative z-10`}>
                                    <div className={`max-w-[75%] rounded-2xl px-3.5 py-2.5 shadow-sm relative transition-all hover:shadow-md ${me
                                            ? "bg-primary text-white rounded-br-sm"
                                            : "bg-white dark:bg-[#202C33] text-[#111B21] dark:text-[#E9EDEF] rounded-bl-sm border border-slate-100 dark:border-transparent"
                                        }`}>
                                        {!me && msg.pushName && (
                                            <p className="text-xs font-bold text-primary mb-0.5">{msg.pushName}</p>
                                        )}
                                        {typeIcon && (
                                            <span className="text-xs mr-1">{typeIcon}</span>
                                        )}
                                        <div className={`text-[14px] leading-[20px] whitespace-pre-wrap break-words ${me ? 'text-white' : ''}`}>
                                            {getMessageText(msg)}
                                        </div>
                                        <div className={`text-[10px] text-right mt-1 ml-4 flex justify-end items-center gap-1 ${me ? 'text-white/70' : 'text-[#667781] dark:text-[#8696A0] opacity-80'
                                            }`}>
                                            {formatTime(msg.messageTimestamp)}
                                            {me && <span className="material-symbols-outlined text-[13px] text-white/60">done_all</span>}
                                        </div>
                                    </div>
                                </div>
                            );
                        })
                    )}
                    <div ref={messagesEndRef} />
                </div>

                {/* Upload indicator */}
                {uploadingFile && (
                    <div className="bg-primary/5 border-t border-primary/10 px-4 py-2 flex items-center gap-2">
                        <div className="animate-spin rounded-full h-4 w-4 border-2 border-primary border-t-transparent"></div>
                        <span className="text-xs text-primary font-medium">Enviando arquivo...</span>
                    </div>
                )}

                {/* Input Area */}
                <form onSubmit={handleSend} className="bg-white dark:bg-[#202C33] px-3 py-3 flex items-end gap-2 border-t border-slate-100 dark:border-[#2A3942]">
                    {/* Attach button with menu */}
                    <div className="relative" ref={attachMenuRef}>
                        <button type="button"
                            onClick={() => setShowAttachMenu(!showAttachMenu)}
                            className="p-2.5 text-primary/70 hover:text-primary hover:bg-primary/10 rounded-full shrink-0 flex items-center justify-center transition-colors">
                            <span className="material-symbols-outlined text-xl">attach_file</span>
                        </button>
                        {showAttachMenu && (
                            <div className="absolute bottom-full left-0 mb-2 bg-white dark:bg-[#2A3942] rounded-2xl shadow-2xl border border-slate-100 dark:border-[#374045] py-2 w-52 animate-in fade-in slide-in-from-bottom-2">
                                <button type="button"
                                    onClick={() => { fileInputRef.current?.setAttribute('accept', 'image/*'); fileInputRef.current?.click(); }}
                                    className="w-full px-4 py-2.5 text-sm hover:bg-primary/5 dark:hover:bg-[#374045] flex items-center gap-3 transition-colors">
                                    <span className="w-8 h-8 bg-blue-500 rounded-full flex items-center justify-center">
                                        <span className="material-symbols-outlined text-white text-base">image</span>
                                    </span>
                                    <span>Fotos</span>
                                </button>
                                <button type="button"
                                    onClick={() => { fileInputRef.current?.setAttribute('accept', 'video/*'); fileInputRef.current?.click(); }}
                                    className="w-full px-4 py-2.5 text-sm hover:bg-primary/5 dark:hover:bg-[#374045] flex items-center gap-3 transition-colors">
                                    <span className="w-8 h-8 bg-red-500 rounded-full flex items-center justify-center">
                                        <span className="material-symbols-outlined text-white text-base">videocam</span>
                                    </span>
                                    <span>Vídeos</span>
                                </button>
                                <button type="button"
                                    onClick={() => { fileInputRef.current?.setAttribute('accept', '*/*'); fileInputRef.current?.click(); }}
                                    className="w-full px-4 py-2.5 text-sm hover:bg-primary/5 dark:hover:bg-[#374045] flex items-center gap-3 transition-colors">
                                    <span className="w-8 h-8 bg-primary rounded-full flex items-center justify-center">
                                        <span className="material-symbols-outlined text-white text-base">description</span>
                                    </span>
                                    <span>Documentos</span>
                                </button>
                                <button type="button"
                                    onClick={() => { fileInputRef.current?.setAttribute('accept', 'audio/*'); fileInputRef.current?.click(); }}
                                    className="w-full px-4 py-2.5 text-sm hover:bg-primary/5 dark:hover:bg-[#374045] flex items-center gap-3 transition-colors">
                                    <span className="w-8 h-8 bg-orange-500 rounded-full flex items-center justify-center">
                                        <span className="material-symbols-outlined text-white text-base">headphones</span>
                                    </span>
                                    <span>Áudio</span>
                                </button>
                            </div>
                        )}
                    </div>

                    {/* Hidden file input */}
                    <input
                        ref={fileInputRef}
                        type="file"
                        className="hidden"
                        onChange={handleFileUpload}
                    />

                    {/* Text input */}
                    <div className="flex-1 bg-slate-50 dark:bg-[#2A3942] rounded-2xl overflow-hidden shadow-sm flex items-end border border-slate-200 dark:border-transparent focus-within:border-primary/40 focus-within:ring-2 focus-within:ring-primary/10 transition-all">
                        <textarea
                            value={inputText}
                            onChange={(e) => setInputText(e.target.value)}
                            onKeyDown={(e) => {
                                if (e.key === 'Enter' && !e.shiftKey) {
                                    e.preventDefault();
                                    handleSend(e);
                                }
                            }}
                            placeholder="Digite uma mensagem..."
                            className="w-full max-h-32 bg-transparent text-[15px] leading-[20px] py-[10px] px-4 resize-none focus:outline-none dark:text-white placeholder:text-slate-400"
                            rows={1}
                            style={{ minHeight: "44px" }}
                        />
                    </div>

                    {/* Send or mic button */}
                    {inputText.trim() ? (
                        <button
                            type="submit"
                            disabled={sending || uploadingFile}
                            className="w-11 h-11 mb-0.5 bg-primary hover:bg-primary-hover text-white rounded-full flex items-center justify-center shrink-0 transition-all shadow-md shadow-primary/20 hover:shadow-lg hover:shadow-primary/30 disabled:opacity-50 active:scale-95"
                        >
                            <span className="material-symbols-outlined text-[20px]">{sending ? "hourglass_empty" : "send"}</span>
                        </button>
                    ) : (
                        <button type="button"
                            className="w-11 h-11 mb-0.5 text-primary/60 hover:text-primary hover:bg-primary/10 rounded-full shrink-0 flex items-center justify-center transition-colors"
                            title="Gravação de áudio (em breve)">
                            <span className="material-symbols-outlined text-xl">mic</span>
                        </button>
                    )}
                </form>

            </div>
        </div>
    );
}
