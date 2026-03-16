"use client";

import React, { useState, useEffect, useRef, useCallback } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { useAuth } from "@/app/context/AuthContext";

interface Message {
  role: "user" | "assistant";
  content: string;
  timestamp: Date;
  sources?: string[];
  streaming?: boolean;
  audio_base64?: string;
  fromHistory?: boolean;
}

const DEFAULT_QUICK_PROMPTS = [
  "Give me the top 3 highlights from this brief",
  "What competitor moves happened?",
  "Any new AI model or product releases?",
  "How does this affect Centific's strategy?",
];

// ── Markdown renderer ─────────────────────────────────────────────────────────

/** Split a plain-text string into runs of text and URLs, return React nodes. */
function renderInline(text: string, keyPrefix: string) {
  // Matches [label](url) markdown links OR bare https?:// URLs
  const URL_RE = /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)|(https?:\/\/[^\s<>"',;)]+)/g;
  const nodes: React.ReactNode[] = [];
  let last = 0;
  let m: RegExpExecArray | null;
  while ((m = URL_RE.exec(text)) !== null) {
    if (m.index > last) nodes.push(text.slice(last, m.index));
    if (m[2]) {
      // [label](url) syntax
      nodes.push(
        <a key={`${keyPrefix}-${m.index}`} href={m[2]} target="_blank" rel="noopener noreferrer"
          className="text-[var(--primary)] underline underline-offset-2 hover:opacity-80 break-all">
          {m[1]}
        </a>
      );
    } else {
      // bare URL
      nodes.push(
        <a key={`${keyPrefix}-${m.index}`} href={m[3]} target="_blank" rel="noopener noreferrer"
          className="text-[var(--primary)] underline underline-offset-2 hover:opacity-80 break-all">
          {m[3]}
        </a>
      );
    }
    last = m.index + m[0].length;
  }
  if (last < text.length) nodes.push(text.slice(last));
  return nodes;
}

/** Render a bold-split part, further splitting on URLs inside each segment. */
function renderBoldAndLinks(content: string, lineKey: number) {
  const boldParts = content.split(/\*\*(.*?)\*\*/g);
  return boldParts.map((part, j) =>
    j % 2 === 1
      ? <strong key={j} className="font-semibold">{renderInline(part, `${lineKey}-b${j}`)}</strong>
      : <React.Fragment key={j}>{renderInline(part, `${lineKey}-t${j}`)}</React.Fragment>
  );
}

function renderMarkdown(text: string) {
  // Hide the machine-readable __SOURCES_JSON__ marker that comes from search_web
  const cleanText = text.replace(/\n?__SOURCES_JSON__:\[.*?\]/g, "");
  return cleanText.split("\n").map((line, i) => {
    const isBullet = line.trimStart().startsWith("- ");
    const content  = isBullet ? line.trimStart().slice(2) : line;
    const rendered = renderBoldAndLinks(content, i);
    if (isBullet) {
      return (
        <div key={i} className="flex gap-2 mt-1.5">
          <span className="shrink-0 mt-0.5 text-[var(--primary)]">•</span>
          <span>{rendered}</span>
        </div>
      );
    }
    return (
      <p key={i} className={i > 0 && line.trim() ? "mt-2" : line.trim() ? "" : "mt-1"}>
        {rendered}
      </p>
    );
  });
}

// ── ElevenLabs base64 MP3 player ──────────────────────────────────────────────
function playBase64Audio(b64: string, onEnd?: () => void): HTMLAudioElement | null {
  try {
    const bytes = atob(b64);
    const buf   = new Uint8Array(bytes.length);
    for (let i = 0; i < bytes.length; i++) buf[i] = bytes.charCodeAt(i);
    const blob  = new Blob([buf], { type: "audio/mpeg" });
    const url   = URL.createObjectURL(blob);
    const audio = new Audio(url);
    audio.onended = () => { URL.revokeObjectURL(url); onEnd?.(); };
    audio.onerror = () => { URL.revokeObjectURL(url); onEnd?.(); };
    audio.play().catch(() => onEnd?.());
    return audio;
  } catch {
    onEnd?.();
    return null;
  }
}

// ── Main page ─────────────────────────────────────────────────────────────────
export default function DigestChatPage() {
  const { run_id } = useParams<{ run_id: string }>();
  const { user }   = useAuth();

  const [messages,        setMessages]        = useState<Message[]>([]);
  const [input,           setInput]           = useState("");
  const [sending,         setSending]         = useState(false);
  const [voiceMode,       setVoiceMode]       = useState(false);
  const [listening,       setListening]       = useState(false);
  const [speaking,        setSpeaking]        = useState(false);
  const [sessionId,       setSessionId]       = useState<string | null>(null);
  const [sessionLoading,  setSessionLoading]  = useState(true);
  const [digestInfo,      setDigestInfo]      = useState<{ date: string; findings_count: number } | null>(null);
  const [quickPrompts,    setQuickPrompts]    = useState<string[]>(DEFAULT_QUICK_PROMPTS);
  const [statusText,      setStatusText]      = useState<string | null>(null);

  const messagesEndRef  = useRef<HTMLDivElement>(null);
  const inputRef        = useRef<HTMLInputElement>(null);
  const activeAudioRef  = useRef<HTMLAudioElement | null>(null);
  // Ref for latest messages — avoids stale closure in sendMessage
  const messagesRef     = useRef<Message[]>([]);
  messagesRef.current   = messages;

  // ── Load session + history on mount ────────────────────────────────────
  useEffect(() => {
    const token  = globalThis.localStorage?.getItem("frontier_ai_radar_token");
    const userId = user?.id ? String(user.id) : null;

    // Load digest metadata in parallel
    fetch("/api/digests", {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
      .then(r => r.json())
      .then(data => {
        const d = (data.data || []).find((x: any) => String(x.run_id) === String(run_id));
        if (d) setDigestInfo({ date: d.date, findings_count: d.findings_count });
      })
      .catch(() => {});

    // Load session — backend resolves the right session by (user_id, run_id)
    // and returns the most recent 10 messages directly from the DB.
    const params = new URLSearchParams({ run_id: String(run_id) });
    if (userId) params.set("user_id", userId);

    fetch(`/api/chat/session?${params.toString()}`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
      .then(r => r.json())
      .then(data => {
        if (data.session_id) setSessionId(data.session_id);

        const prior: Message[] = (data.messages || []).map((m: any) => ({
          role:        m.role,
          content:     m.content,
          timestamp:   m.timestamp ? new Date(m.timestamp) : new Date(),
          sources:     m.sources || [],
          fromHistory: true,
        }));

        if (data.popular_questions?.length) {
          setQuickPrompts([
            ...data.popular_questions.slice(0, 3),
            ...DEFAULT_QUICK_PROMPTS.slice(0, 2),
          ]);
        }

        if (prior.length > 0) {
          setMessages(prior);
        } else {
          setMessages([{
            role:      "assistant",
            content:   `Hello! I'm your AI intelligence analyst. Ask me anything about this digest.`,
            timestamp: new Date(),
          }]);
        }
      })
      .catch(() => {
        setMessages([{
          role:      "assistant",
          content:   "Hello! I'm your AI intelligence analyst. Ask me anything about this digest.",
          timestamp: new Date(),
        }]);
      })
      .finally(() => setSessionLoading(false));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run_id]);

  // Scroll to bottom on new messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, sending]);

  // ── Send message ──────────────────────────────────────────────────────
  const sendMessage = useCallback(async (text: string) => {
    if (!text.trim() || sending) return;

    const userMsg: Message = { role: "user", content: text.trim(), timestamp: new Date() };
    setMessages(prev => [...prev, userMsg]);
    setInput("");
    setSending(true);

    // Build history from ref (never stale)
    const history = messagesRef.current
      .filter(m => !m.fromHistory)
      .slice(-14)
      .map(m => ({ role: m.role, content: m.content }));

    const mode  = voiceMode ? "voice" : "text";
    const token = globalThis.localStorage?.getItem("frontier_ai_radar_token");

    try {
      const res = await fetch("/api/chat", {
        method:  "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({
          run_id,
          message:    text.trim(),
          history,
          mode,
          session_id: sessionId,
          user_id:    user?.id ?? null,
        }),
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.error || "Request failed");
      }

      const contentType = res.headers.get("content-type") || "";

      // ── Streaming text response ─────────────────────────────────────
      if (contentType.includes("text/event-stream") && res.body) {
        setMessages(prev => [
          ...prev,
          { role: "assistant", content: "", timestamp: new Date(), streaming: true },
        ]);

        const reader  = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer    = "";
        let fullText  = "";
        let sources: string[]  = [];
        let newSessionId: string | null = null;

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop() ?? "";

          for (const line of lines) {
            if (!line.startsWith("data:")) continue;
            try {
              const payload = JSON.parse(line.slice(5).trim());
              if (payload.status) {
                setStatusText(payload.status);
              }
              if (payload.token) {
                setStatusText(null);
                fullText += payload.token;
                setMessages(prev => {
                  const updated = [...prev];
                  const last    = updated[updated.length - 1];
                  if (last?.role === "assistant") {
                    updated[updated.length - 1] = { ...last, content: fullText, streaming: true };
                  }
                  return updated;
                });
              }
              if (payload.done) {
                sources       = payload.sources || [];
                newSessionId  = payload.session_id || null;
                setStatusText(null);
              }
            } catch { /* malformed SSE line */ }
          }
        }

        if (newSessionId && !sessionId) setSessionId(newSessionId);

        setMessages(prev => {
          const updated = [...prev];
          const last    = updated[updated.length - 1];
          if (last?.role === "assistant") {
            updated[updated.length - 1] = {
              ...last,
              content:   fullText || "I couldn't generate a response.",
              streaming: false,
              sources,
            };
          }
          return updated;
        });

      } else {
        // ── Voice JSON response ───────────────────────────────────────
        const data         = await res.json();
        const responseText = data.response || "I couldn't generate a response.";

        setMessages(prev => [
          ...prev,
          {
            role:         "assistant",
            content:      responseText,
            timestamp:    new Date(),
            sources:      data.sources || [],
            audio_base64: data.audio_base64 || undefined,
          },
        ]);

        if (voiceMode && data.audio_base64) {
          setSpeaking(true);
          activeAudioRef.current?.pause();
          activeAudioRef.current = playBase64Audio(data.audio_base64, () => setSpeaking(false));
        }
      }

    } catch (err: any) {
      setMessages(prev => [
        ...prev,
        {
          role:      "assistant",
          content:   err.message === "Failed to fetch"
            ? "Cannot reach the AI service. Please ensure the backend is running."
            : `Something went wrong: ${err.message || "Unknown error"}`,
          timestamp: new Date(),
        },
      ]);
    } finally {
      setSending(false);
      setStatusText(null);
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [sending, voiceMode, run_id, sessionId, user?.id]);

  // ── Voice input (STT) ─────────────────────────────────────────────────
  const handleVoiceInput = () => {
    const SR = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (!SR) { alert("Voice input requires Chrome or Edge."); return; }
    const recognition      = new SR();
    recognition.lang       = "en-US";
    recognition.interimResults = false;
    setListening(true);
    recognition.start();
    recognition.onresult = (e: any) => { setListening(false); sendMessage(e.results[0][0].transcript); };
    recognition.onerror  = () => setListening(false);
    recognition.onend    = () => setListening(false);
  };

  const stopSpeaking = () => {
    activeAudioRef.current?.pause();
    activeAudioRef.current = null;
    setSpeaking(false);
  };

  const formatTime = (d: Date) =>
    d.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" });

  const shortDate = digestInfo?.date
    ? new Date(digestInfo.date + (digestInfo.date.includes("T") ? "" : "T00:00:00Z"))
        .toLocaleDateString("en-US", { month: "long", day: "numeric", year: "numeric" })
    : "";

  const userInitial    = user?.name?.[0]?.toUpperCase() ?? "U";
  const hasUserMessage = messages.some(m => m.role === "user" && !m.fromHistory);

  return (
    <div className="flex flex-col bg-[var(--bg)]" style={{ height: "100dvh" }}>

      {/* ── Header ─────────────────────────────────────────────────────── */}
      <div
        className="flex-none border-b border-[var(--border)] bg-[var(--bg-card)] px-4 sm:px-6 py-3 flex items-center gap-3"
        style={{ boxShadow: "0 1px 4px rgba(0,0,0,0.06)" }}
      >
        <Link
          href="/digest"
          className="flex items-center gap-1.5 text-[var(--text-secondary)] hover:text-[var(--primary)] transition-colors text-sm font-medium flex-none"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <line x1="19" y1="12" x2="5" y2="12" /><polyline points="12 19 5 12 12 5" />
          </svg>
          Briefings
        </Link>

        <span className="text-[var(--border)] text-lg">|</span>

        <div className="flex-1 min-w-0">
          <h1 className="text-sm font-semibold text-[var(--text-primary)] truncate">
            AI Intelligence Analyst
          </h1>
          {digestInfo && (
            <p className="text-xs text-[var(--text-muted)] truncate">
              {shortDate} · {digestInfo.findings_count} findings
              {sessionId && !sessionLoading && (
                <span className="ml-2 text-[var(--primary)]">· Session active</span>
              )}
            </p>
          )}
        </div>

        {/* Voice / Text toggle */}
        <button
          type="button"
          onClick={() => {
            activeAudioRef.current?.pause();
            activeAudioRef.current = null;
            setSpeaking(false);
            setVoiceMode(v => !v);
          }}
          className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
            voiceMode
              ? "bg-[var(--primary)] text-white shadow-sm"
              : "border border-[var(--border)] text-[var(--text-secondary)] hover:border-[var(--primary)] hover:text-[var(--primary)]"
          }`}
        >
          {voiceMode ? (
            <>
              <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
                <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/>
              </svg>
              Voice
            </>
          ) : (
            <>
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
              </svg>
              Text
            </>
          )}
        </button>
      </div>

      {/* ── Session loading skeleton ────────────────────────────────────── */}
      {sessionLoading && (
        <div className="flex-none px-6 py-3 border-b border-[var(--border)] bg-[var(--bg-card)]">
          <div className="flex items-center gap-2 text-xs text-[var(--text-muted)]">
            <span className="w-3 h-3 rounded-full bg-[var(--primary)] animate-pulse" />
            Loading conversation history…
          </div>
        </div>
      )}

      {/* ── Messages ───────────────────────────────────────────────────── */}
      <div className="flex-1 overflow-y-auto px-4 sm:px-6 py-6">
        <div className="max-w-3xl mx-auto space-y-5">

          {messages.map((msg, i) => {
            const isHistory = msg.fromHistory;
            return (
              <div key={i}>
                {/* History divider before first history message */}
                {isHistory && i === 0 && (
                  <div className="flex items-center gap-3 mb-4">
                    <div className="flex-1 h-px bg-[var(--border)]" />
                    <span className="text-[10px] text-[var(--text-muted)] uppercase tracking-widest">
                      Previous conversation
                    </span>
                    <div className="flex-1 h-px bg-[var(--border)]" />
                  </div>
                )}

                <div className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
                  <div className={`flex items-end gap-2.5 max-w-[88%] ${msg.role === "user" ? "flex-row-reverse" : ""}`}>

                    {/* Avatar */}
                    <div className={`w-8 h-8 rounded-full flex-none flex items-center justify-center text-xs font-bold mb-5 shrink-0 ${
                      msg.role === "user"
                        ? "bg-[var(--primary)] text-white"
                        : "bg-gradient-to-br from-[var(--primary)] to-cyan-500 text-white"
                    } ${isHistory ? "opacity-60" : ""}`}>
                      {msg.role === "user" ? userInitial : "AI"}
                    </div>

                    <div>
                      <div className={`px-4 py-3 rounded-2xl text-sm leading-relaxed ${
                        msg.role === "user"
                          ? `bg-[var(--primary)] text-white rounded-br-sm ${isHistory ? "opacity-70" : ""}`
                          : `bg-[var(--bg-card)] border border-[var(--border)] text-[var(--text-primary)] rounded-bl-sm shadow-sm ${isHistory ? "opacity-70" : ""}`
                      }`}>
                        {renderMarkdown(msg.content)}
                        {msg.streaming && (
                          <span className="inline-block w-0.5 h-4 bg-[var(--primary)] ml-0.5 animate-pulse align-middle" />
                        )}
                      </div>

                      {/* Sources */}
                      {msg.sources && msg.sources.length > 0 && !msg.streaming && (
                        <div className="mt-1.5 flex flex-wrap gap-1.5">
                          {msg.sources.slice(0, 4).map((src, si) => {
                            let host = src;
                            try { host = new URL(src).hostname.replace("www.", ""); } catch {}
                            return (
                              <a key={si} href={src} target="_blank" rel="noopener noreferrer"
                                className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-[var(--primary-light)] text-[var(--primary)] text-[10px] font-medium hover:underline">
                                <svg width="8" height="8" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                                  <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/>
                                  <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>
                                </svg>
                                {host}
                              </a>
                            );
                          })}
                        </div>
                      )}

                      {/* Play again (voice mode) */}
                      {msg.role === "assistant" && !msg.streaming && msg.audio_base64 && (
                        <button type="button"
                          onClick={() => {
                            stopSpeaking();
                            setSpeaking(true);
                            activeAudioRef.current = playBase64Audio(msg.audio_base64!, () => setSpeaking(false));
                          }}
                          className="mt-1 flex items-center gap-1 text-[10px] text-[var(--text-muted)] hover:text-[var(--primary)] transition-colors">
                          <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                            <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/>
                            <path d="M15.54 8.46a5 5 0 0 1 0 7.07"/>
                          </svg>
                          Play again
                        </button>
                      )}

                      <p className={`text-[10px] text-[var(--text-muted)] mt-1 ${msg.role === "user" ? "text-right" : "text-left"}`}>
                        {formatTime(msg.timestamp)}
                      </p>
                    </div>
                  </div>
                </div>
              </div>
            );
          })}

          {/* Thinking / tool-activity indicator */}
          {sending && !messages[messages.length - 1]?.streaming && (
            <div className="flex justify-start">
              <div className="flex items-end gap-2.5">
                <div className="w-8 h-8 rounded-full flex-none flex items-center justify-center text-xs font-bold mb-5 bg-gradient-to-br from-[var(--primary)] to-cyan-500 text-white">AI</div>
                <div className="px-4 py-3.5 rounded-2xl rounded-bl-sm bg-[var(--bg-card)] border border-[var(--border)] shadow-sm">
                  {statusText ? (
                    <div className="flex items-center gap-2 text-xs text-[var(--text-secondary)]">
                      <span className="w-2 h-2 rounded-full bg-[var(--primary)] animate-pulse flex-none" />
                      {statusText}
                    </div>
                  ) : (
                    <div className="flex items-center gap-1.5">
                      {[0, 150, 300].map(delay => (
                        <span key={delay} className="w-2 h-2 rounded-full bg-[var(--primary)] animate-bounce" style={{ animationDelay: `${delay}ms` }} />
                      ))}
                    </div>
                  )}
                </div>
              </div>
            </div>
          )}

          {/* Speaking indicator */}
          {speaking && (
            <div className="flex justify-start">
              <button type="button" onClick={stopSpeaking}
                className="flex items-center gap-2 px-3 py-2 rounded-xl bg-[var(--primary-light)] border border-[var(--border-purple)] text-[var(--primary)] text-xs font-medium hover:bg-[var(--primary)] hover:text-white transition-all">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                  <rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/>
                </svg>
                Speaking… tap to stop
              </button>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>
      </div>

      {/* ── Quick prompts ───────────────────────────────────────────────── */}
      {!hasUserMessage && !sending && !sessionLoading && (
        <div className="flex-none px-4 sm:px-6 pb-3">
          <div className="max-w-3xl mx-auto">
            <p className="text-[10px] text-[var(--text-muted)] text-center mb-2 uppercase tracking-wide">
              {quickPrompts[0] !== DEFAULT_QUICK_PROMPTS[0] ? "Trending questions on this brief" : "Try asking"}
            </p>
            <div className="flex flex-wrap gap-2 justify-center">
              {quickPrompts.slice(0, 5).map(p => (
                <button key={p} onClick={() => sendMessage(p)}
                  className="px-3 py-1.5 rounded-full border border-[var(--border)] bg-[var(--bg-card)] text-xs text-[var(--text-secondary)] hover:border-[var(--primary)] hover:text-[var(--primary)] hover:bg-[var(--primary-light)] transition-all text-left">
                  {p}
                </button>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* ── Input area ─────────────────────────────────────────────────── */}
      <div className="flex-none border-t border-[var(--border)] bg-[var(--bg-card)] px-4 sm:px-6 py-3">
        <div className="max-w-3xl mx-auto flex items-center gap-2.5">
          <input
            ref={inputRef}
            type="text"
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(input); } }}
            placeholder={
              sessionLoading ? "Loading session…" :
              listening      ? "Listening…" :
              voiceMode      ? "Ask a question — response will be spoken aloud…" :
              "Ask about today's AI intelligence…"
            }
            disabled={sending || listening || sessionLoading}
            className="flex-1 px-4 py-3 rounded-xl border border-[var(--border)] bg-[var(--bg)] text-[var(--text-primary)] text-sm placeholder:text-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-[var(--primary)]/25 focus:border-[var(--primary)] transition-colors disabled:opacity-60"
          />

          {/* Mic */}
          <button type="button" onClick={listening ? undefined : handleVoiceInput}
            disabled={sending || sessionLoading}
            className={`w-10 h-10 rounded-xl flex-none flex items-center justify-center transition-all ${
              listening ? "bg-red-500 text-white animate-pulse" : "border border-[var(--border)] text-[var(--text-muted)] hover:border-[var(--primary)] hover:text-[var(--primary)]"
            } disabled:opacity-40`}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/>
              <path d="M19 10v2a7 7 0 0 1-14 0v-2M12 19v4M8 23h8"/>
            </svg>
          </button>

          {/* Send */}
          <button type="button" onClick={() => sendMessage(input)}
            disabled={!input.trim() || sending || sessionLoading}
            className="w-10 h-10 rounded-xl flex-none flex items-center justify-center bg-[var(--primary)] hover:bg-[var(--primary-hover)] text-white transition-all disabled:opacity-40 disabled:cursor-not-allowed shadow-sm">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/>
            </svg>
          </button>
        </div>

        <p className="text-center text-[10px] text-[var(--text-muted)] mt-2">
          {voiceMode
            ? "Voice mode · ElevenLabs · session saved · web search on demand"
            : "Text mode · streaming · session saved · 3-tier answer cache"}
        </p>
      </div>
    </div>
  );
}
