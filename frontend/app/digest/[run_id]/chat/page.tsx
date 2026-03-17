"use client";

import React, { useState, useEffect, useRef, useCallback } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { useAuth } from "@/app/context/AuthContext";
import { PERSONAS, type Persona } from "@/lib/personas";

interface Message {
  role: "user" | "assistant";
  content: string;
  timestamp: Date;
  sources?: string[];
  streaming?: boolean;
  audio_base64?: string;
  fromHistory?: boolean;
}

interface Thread {
  thread_id: string;
  title: string;
  message_count: number;
  last_active: string | null;
  message_preview: string;
}

const DEFAULT_QUICK_PROMPTS = [
  "Give me the top 3 highlights from this brief",
  "What competitor moves happened?",
  "Any new AI model or product releases?",
  "How does this affect Centific's strategy?",
];

// ── Markdown renderer ──────────────────────────────────────────────────────────

function renderInline(text: string, keyPrefix: string) {
  const URL_RE = /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)|(https?:\/\/[^\s<>"',;)]+)/g;
  const nodes: React.ReactNode[] = [];
  let last = 0;
  let m: RegExpExecArray | null;
  while ((m = URL_RE.exec(text)) !== null) {
    if (m.index > last) nodes.push(text.slice(last, m.index));
    if (m[2]) {
      nodes.push(
        <a key={`${keyPrefix}-${m.index}`} href={m[2]} target="_blank" rel="noopener noreferrer"
          className="text-[var(--primary)] underline underline-offset-2 hover:opacity-80 break-all">
          {m[1]}
        </a>
      );
    } else {
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

function renderBoldAndLinks(content: string, lineKey: number) {
  const boldParts = content.split(/\*\*(.*?)\*\*/g);
  return boldParts.map((part, j) =>
    j % 2 === 1
      ? <strong key={j} className="font-semibold">{renderInline(part, `${lineKey}-b${j}`)}</strong>
      : <React.Fragment key={j}>{renderInline(part, `${lineKey}-t${j}`)}</React.Fragment>
  );
}

function renderMarkdown(text: string) {
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

// ── Audio player ───────────────────────────────────────────────────────────────
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

// ── Thread date grouping ───────────────────────────────────────────────────────
function groupThreadsByDate(threads: Thread[]): { label: string; items: Thread[] }[] {
  const now   = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const groups: Record<string, Thread[]> = {
    "Today": [],
    "Yesterday": [],
    "Last 7 Days": [],
    "Older": [],
  };
  for (const t of threads) {
    const d    = t.last_active ? new Date(t.last_active).getTime() : 0;
    const diff = today - new Date(new Date(d).getFullYear(), new Date(d).getMonth(), new Date(d).getDate()).getTime();
    if (diff <= 0)            groups["Today"].push(t);
    else if (diff <= 86400000) groups["Yesterday"].push(t);
    else if (diff <= 6 * 86400000) groups["Last 7 Days"].push(t);
    else                      groups["Older"].push(t);
  }
  return Object.entries(groups)
    .filter(([, items]) => items.length > 0)
    .map(([label, items]) => ({ label, items }));
}

// ── Main page ──────────────────────────────────────────────────────────────────
export default function DigestChatPage() {
  const { run_id } = useParams<{ run_id: string }>();
  const { user }   = useAuth();

  const [messages,       setMessages]       = useState<Message[]>([]);
  const [input,          setInput]          = useState("");
  const [sending,        setSending]        = useState(false);
  const [voiceMode,      setVoiceMode]      = useState(false);
  const [listening,      setListening]      = useState(false);
  const [speaking,       setSpeaking]       = useState(false);
  const [sessionId,      setSessionId]      = useState<string | null>(null);
  const [sessionLoading, setSessionLoading] = useState(true);
  const [digestInfo,     setDigestInfo]     = useState<{ date: string; findings_count: number } | null>(null);
  const [statusText,     setStatusText]     = useState<string | null>(null);
  const [activePersona,  setActivePersona]  = useState<string | null>(null);
  const [sidebarOpen,    setSidebarOpen]    = useState(true);
  const [threads,        setThreads]        = useState<Thread[]>([]);
  const [activeThreadId, setActiveThreadId] = useState<string | null>(null);
  const [threadsLoading, setThreadsLoading] = useState(false);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef       = useRef<HTMLInputElement>(null);
  const activeAudioRef = useRef<HTMLAudioElement | null>(null);
  const messagesRef    = useRef<Message[]>([]);
  messagesRef.current  = messages;

  // ── Persist persona + sidebar state ────────────────────────────────────────
  useEffect(() => {
    const saved = globalThis.localStorage?.getItem("frontier_active_persona");
    setActivePersona(saved || "general");
    const savedSidebar = globalThis.localStorage?.getItem("frontier_sidebar_open");
    if (savedSidebar !== null) setSidebarOpen(savedSidebar !== "false");
  }, []);

  // ── Thread fetch ────────────────────────────────────────────────────────────
  const fetchThreads = useCallback(async (personaId: string) => {
    if (!user?.id || !personaId) { setThreads([]); return; }
    setThreadsLoading(true);
    try {
      const params = new URLSearchParams({
        user_id:    String(user.id),
        persona_id: personaId,
        run_id:     String(run_id),
      });
      const r = await fetch(`/api/threads?${params}`);
      if (r.ok) {
        const data = await r.json();
        setThreads(data.threads || []);
      }
    } catch {}
    setThreadsLoading(false);
  }, [user?.id, run_id]);

  // ── Persona switch ──────────────────────────────────────────────────────────
  const selectPersona = useCallback((id: string) => {
    if (id === activePersona) return;
    setActivePersona(id);
    globalThis.localStorage?.setItem("frontier_active_persona", id);
    setMessages([]);
    setSessionId(null);
    setActiveThreadId(null);
    setThreads([]);
    if (id) fetchThreads(id);
  }, [activePersona, fetchThreads]);

  const toggleSidebar = useCallback(() => {
    setSidebarOpen(prev => {
      const next = !prev;
      globalThis.localStorage?.setItem("frontier_sidebar_open", String(next));
      return next;
    });
  }, []);

  // ── New chat ────────────────────────────────────────────────────────────────
  const createNewThread = useCallback(async () => {
    if (!user?.id || !activePersona) return;
    const r = await fetch("/api/threads/new", {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body:    JSON.stringify({ user_id: user.id, persona_id: activePersona, run_id: Number(run_id) }),
    });
    if (r.ok) {
      const thread = await r.json();
      setActiveThreadId(thread.session_id);
      setSessionId(thread.session_id);
      setMessages([]);
      fetchThreads(activePersona);
    }
  }, [user?.id, activePersona, run_id, fetchThreads]);

  // ── Load existing thread ────────────────────────────────────────────────────
  const loadThread = useCallback(async (threadId: string) => {
    setActiveThreadId(threadId);
    setSessionId(threadId);
    setMessages([]);
    setSessionLoading(true);
    try {
      const token  = globalThis.localStorage?.getItem("frontier_ai_radar_token");
      const params = new URLSearchParams({ run_id: String(run_id), session_id: threadId });
      if (user?.id)      params.set("user_id", String(user.id));
      if (activePersona) params.set("persona_id", activePersona);
      const r = await fetch(`/api/chat/session?${params}`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (r.ok) {
        const data = await r.json();
        const prior: Message[] = (data.messages || []).map((m: any) => ({
          role:        m.role,
          content:     m.content,
          timestamp:   m.timestamp ? new Date(m.timestamp) : new Date(),
          sources:     m.sources || [],
          fromHistory: true,
        }));
        setMessages(prior);
      }
    } catch {}
    setSessionLoading(false);
  }, [run_id, user?.id, activePersona]);

  // ── Fill prompt chip ────────────────────────────────────────────────────────
  const fillPrompt = useCallback((prompt: string) => {
    setInput(prompt);
    const match = /\[([^\]]+)\]/.exec(prompt);
    if (match) {
      const start = match.index;
      const end   = start + match[0].length;
      setTimeout(() => {
        if (inputRef.current) {
          inputRef.current.focus();
          inputRef.current.setSelectionRange(start, end);
        }
      }, 0);
    } else {
      setTimeout(() => inputRef.current?.focus(), 0);
    }
  }, []);

  // ── Load digest info + threads on mount / persona change ───────────────────
  useEffect(() => {
    const token     = globalThis.localStorage?.getItem("frontier_ai_radar_token");
    const personaId = globalThis.localStorage?.getItem("frontier_active_persona") || "";

    // Reset to empty state — never auto-load a thread
    setMessages([]);
    setSessionId(null);
    setActiveThreadId(null);

    fetch("/api/digests", { headers: token ? { Authorization: `Bearer ${token}` } : {} })
      .then(r => r.json())
      .then(data => {
        const d = (data.data || []).find((x: any) => String(x.run_id) === String(run_id));
        if (d) setDigestInfo({ date: d.date, findings_count: d.findings_count });
      })
      .catch(() => {})
      .finally(() => {
        setSessionLoading(false);
        if (personaId) fetchThreads(personaId);
      });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run_id, activePersona]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, sending]);

  // ── Send message ────────────────────────────────────────────────────────────
  const sendMessage = useCallback(async (text: string) => {
    if (!text.trim() || sending) return;

    const userMsg: Message = { role: "user", content: text.trim(), timestamp: new Date() };
    setMessages(prev => [...prev, userMsg]);
    setInput("");
    setSending(true);

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
          persona_id: activePersona ?? null,
        }),
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.error || "Request failed");
      }

      const contentType = res.headers.get("content-type") || "";

      if (contentType.includes("text/event-stream") && res.body) {
        setMessages(prev => [
          ...prev,
          { role: "assistant", content: "", timestamp: new Date(), streaming: true },
        ]);

        const reader  = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer    = "";
        let fullText  = "";
        let sources: string[]        = [];
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
              if (payload.status) setStatusText(payload.status);
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
                sources      = payload.sources || [];
                newSessionId = payload.session_id || null;
                setStatusText(null);
              }
            } catch { /* malformed SSE */ }
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
        const data         = await res.json();
        const responseText = data.response || "I couldn't generate a response.";
        setMessages(prev => [...prev, {
          role:         "assistant",
          content:      responseText,
          timestamp:    new Date(),
          sources:      data.sources || [],
          audio_base64: data.audio_base64 || undefined,
        }]);
        if (voiceMode && data.audio_base64) {
          setSpeaking(true);
          activeAudioRef.current?.pause();
          activeAudioRef.current = playBase64Audio(data.audio_base64, () => setSpeaking(false));
        }
      }

    } catch (err: any) {
      setMessages(prev => [...prev, {
        role:      "assistant",
        content:   err.message === "Failed to fetch"
          ? "Cannot reach the AI service. Please ensure the backend is running."
          : `Something went wrong: ${err.message || "Unknown error"}`,
        timestamp: new Date(),
      }]);
    } finally {
      setSending(false);
      setStatusText(null);
      setTimeout(() => inputRef.current?.focus(), 50);
      if (activePersona) fetchThreads(activePersona);
    }
  }, [sending, voiceMode, run_id, sessionId, user?.id, activePersona, fetchThreads]);

  // ── Voice input ─────────────────────────────────────────────────────────────
  const handleVoiceInput = () => {
    const SR = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (!SR) { alert("Voice input requires Chrome or Edge."); return; }
    const recognition         = new SR();
    recognition.lang          = "en-US";
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
        .toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })
    : "";

  const userInitial     = user?.name?.[0]?.toUpperCase() ?? "U";
  const hasUserMessage  = messages.some(m => m.role === "user" && !m.fromHistory);
  const hasHistory      = messages.some(m => m.fromHistory);
  const showEmptyState  = !hasUserMessage && !hasHistory;
  const selectedPersona = PERSONAS.find(p => p.id === activePersona) ?? null;
  const threadGroups    = groupThreadsByDate(threads);
  const activeThread    = threads.find(t => t.thread_id === activeThreadId);

  return (
    <div className="flex bg-[var(--bg)]" style={{ height: "100dvh" }}>

      {/* ── LEFT SIDEBAR ──────────────────────────────────────────────────── */}
      <div
        className={`flex-none flex flex-col transition-all duration-200 overflow-hidden border-r border-[var(--border)] ${sidebarOpen ? "w-64" : "w-0"}`}
        style={{ background: "var(--bg-card)" }}
      >
        {/* App name */}
        <div className="flex-none px-4 pt-4 pb-3 border-b border-[var(--border)]">
          <div className="flex items-center gap-2">
            <span className="text-lg">🔭</span>
            <span className="text-sm font-semibold text-[var(--text-primary)] tracking-tight">Frontier AI Radar</span>
          </div>
        </div>

        {/* New Chat button */}
        <div className="flex-none px-3 pt-3 pb-3">
          <button
            onClick={createNewThread}
            disabled={!user?.id}
            className="w-full flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg text-xs font-medium border border-[var(--border)] text-[var(--text-secondary)] hover:border-[var(--primary)] hover:text-[var(--primary)] hover:bg-[var(--primary-light)] transition-all disabled:opacity-40 disabled:cursor-not-allowed"
          >
            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
              <line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>
            </svg>
            New Chat
          </button>
        </div>

        {/* Thread list */}
        <div className="flex-1 overflow-y-auto px-2 pb-4">
          {threadsLoading ? (
            <div className="px-2 py-3 text-[10px] text-[var(--text-muted)]">Loading…</div>
          ) : threadGroups.length === 0 ? (
            <p className="text-[10px] text-[var(--text-muted)] italic px-2 pt-1">No conversations yet</p>
          ) : (
            threadGroups.map(group => (
              <div key={group.label} className="mb-3">
                <p className="text-[9px] font-semibold text-[var(--text-muted)] uppercase tracking-widest px-2 py-1.5">
                  {group.label}
                </p>
                <div className="space-y-0.5">
                  {group.items.map(t => (
                    <button
                      key={t.thread_id}
                      onClick={() => loadThread(t.thread_id)}
                      title={t.title}
                      className={`w-full text-left px-2.5 py-2 rounded-lg transition-all group ${
                        activeThreadId === t.thread_id
                          ? "bg-[var(--primary)]/10 border border-[var(--primary)]/25 text-[var(--primary)]"
                          : "text-[var(--text-secondary)] hover:bg-[var(--bg)] border border-transparent"
                      }`}
                    >
                      <div className="text-[12px] font-medium truncate leading-snug">
                        {t.title}
                      </div>
                    </button>
                  ))}
                </div>
              </div>
            ))
          )}
        </div>
      </div>

      {/* ── MAIN CHAT AREA ──────────────────────────────────────────────────── */}
      <div className="flex flex-col flex-1 min-w-0">

        {/* ── Top bar ─────────────────────────────────────────────────────── */}
        <div
          className="flex-none border-b border-[var(--border)] bg-[var(--bg-card)] px-4 py-2.5 flex items-center gap-3"
          style={{ boxShadow: "0 1px 4px rgba(0,0,0,0.06)" }}
        >
          {/* Sidebar toggle */}
          <button
            onClick={toggleSidebar}
            className="flex-none text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors p-1 rounded"
          >
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/>
            </svg>
          </button>

          {/* Back to briefings */}
          <Link
            href="/digest"
            className="flex items-center gap-1 text-[var(--text-muted)] hover:text-[var(--primary)] transition-colors text-xs font-medium flex-none"
          >
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="19" y1="12" x2="5" y2="12"/><polyline points="12 19 5 12 12 5"/>
            </svg>
            Briefings
          </Link>

          <span className="text-[var(--border)]">|</span>

          {/* Thread title */}
          <div className="flex-1 min-w-0 flex items-center gap-2">
            <h1 className="text-sm font-semibold text-[var(--text-primary)] truncate">
              {activeThread?.title ?? (showEmptyState ? (selectedPersona?.label ?? "AI Intelligence Analyst") : "New conversation")}
            </h1>
            {selectedPersona && (
              <span className="flex-none text-[10px] px-2 py-0.5 rounded-full border border-[var(--primary)]/30 text-[var(--primary)] bg-[var(--primary)]/8 font-medium whitespace-nowrap">
                {selectedPersona.icon} {selectedPersona.label}
              </span>
            )}
            {digestInfo && (
              <span className="flex-none text-[10px] text-[var(--text-muted)] hidden sm:block">
                · {shortDate}
              </span>
            )}
          </div>

          {/* Persona dropdown — right side of top bar */}
          <select
            value={activePersona ?? "general"}
            onChange={e => selectPersona(e.target.value)}
            className="flex-none text-xs px-2.5 py-1.5 rounded-lg border border-[var(--border)] bg-[var(--bg)] text-[var(--text-primary)] focus:outline-none focus:ring-2 focus:ring-[var(--primary)]/30 focus:border-[var(--primary)] transition-colors cursor-pointer max-w-[160px]"
          >
            {PERSONAS.map(p => (
              <option key={p.id} value={p.id}>{p.label}</option>
            ))}
          </select>

          {/* Voice / Text toggle */}
          <button
            type="button"
            onClick={() => {
              activeAudioRef.current?.pause();
              activeAudioRef.current = null;
              setSpeaking(false);
              setVoiceMode(v => !v);
            }}
            className={`flex-none flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium transition-all ${
              voiceMode
                ? "bg-[var(--primary)] text-white shadow-sm"
                : "border border-[var(--border)] text-[var(--text-secondary)] hover:border-[var(--primary)] hover:text-[var(--primary)]"
            }`}
          >
            {voiceMode ? (
              <><svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor"><path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/></svg> Voice</>
            ) : (
              <><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg> Text</>
            )}
          </button>

          {/* User avatar */}
          {user?.name && (
            <div className="flex-none w-7 h-7 rounded-full bg-[var(--primary)] text-white text-xs font-bold flex items-center justify-center">
              {userInitial}
            </div>
          )}
        </div>

        {/* Loading bar */}
        {sessionLoading && (
          <div className="flex-none h-0.5 bg-[var(--primary)] animate-pulse" />
        )}

        {/* ── Messages / Empty state ───────────────────────────────────────── */}
        <div className="flex-1 overflow-y-auto px-4 sm:px-6 py-6">

          {showEmptyState ? (
            /* ── Empty state ── */
            <div className="h-full flex flex-col items-center justify-center gap-4 pb-16">
              {selectedPersona ? (
                <>
                  <span className="text-5xl">{selectedPersona.icon}</span>
                  <div className="text-center">
                    <h2 className="text-xl font-semibold text-[var(--text-primary)]">{selectedPersona.label}</h2>
                    <p className="text-xs text-[var(--text-muted)] mt-1 max-w-xs leading-relaxed">{selectedPersona.description}</p>
                  </div>
                  <div className="grid grid-cols-2 gap-2 w-full max-w-lg mt-2">
                    {selectedPersona.prompts.slice(0, 6).map((prompt, pi) => (
                      <button
                        key={pi}
                        onClick={() => fillPrompt(prompt)}
                        className="text-left px-3.5 py-3 rounded-xl border border-[var(--border)] bg-[var(--bg-card)] text-xs text-[var(--text-secondary)] hover:border-[var(--primary)] hover:text-[var(--text-primary)] hover:bg-[var(--primary-light)] transition-all leading-snug"
                      >
                        {prompt.includes("[") ? (
                          <>
                            {prompt.split(/(\[[^\]]+\])/g).map((part, idx) =>
                              /^\[[^\]]+\]$/.test(part)
                                ? <span key={idx} className="bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300 rounded px-0.5">{part}</span>
                                : part
                            )}
                          </>
                        ) : prompt}
                      </button>
                    ))}
                  </div>
                </>
              ) : (
                <>
                  <span className="text-5xl">🔭</span>
                  <div className="text-center">
                    <h2 className="text-xl font-semibold text-[var(--text-primary)]">AI Intelligence Analyst</h2>
                    <p className="text-xs text-[var(--text-muted)] mt-1 max-w-xs leading-relaxed">
                      Your real-time AI industry radar. Select a persona from the sidebar or ask anything about today's digest.
                    </p>
                  </div>
                  <div className="grid grid-cols-2 gap-2 w-full max-w-lg mt-2">
                    {DEFAULT_QUICK_PROMPTS.map(p => (
                      <button
                        key={p}
                        onClick={() => sendMessage(p)}
                        className="text-left px-3.5 py-3 rounded-xl border border-[var(--border)] bg-[var(--bg-card)] text-xs text-[var(--text-secondary)] hover:border-[var(--primary)] hover:text-[var(--text-primary)] hover:bg-[var(--primary-light)] transition-all leading-snug"
                      >
                        {p}
                      </button>
                    ))}
                  </div>
                </>
              )}
            </div>

          ) : (

            /* ── Active thread messages ── */
            <div className="max-w-3xl mx-auto space-y-5">

              {messages.map((msg, i) => {
                const isHistory = msg.fromHistory;
                return (
                  <div key={i}>
                    {isHistory && i === 0 && (
                      <div className="flex items-center gap-3 mb-4">
                        <div className="flex-1 h-px bg-[var(--border)]" />
                        <span className="text-[10px] text-[var(--text-muted)] uppercase tracking-widest">Previous conversation</span>
                        <div className="flex-1 h-px bg-[var(--border)]" />
                      </div>
                    )}

                    <div className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
                      <div className={`flex items-end gap-2.5 max-w-[88%] ${msg.role === "user" ? "flex-row-reverse" : ""}`}>

                        {/* Avatar */}
                        <div className={`w-7 h-7 rounded-full flex-none flex items-center justify-center text-[10px] font-bold mb-5 shrink-0 ${
                          msg.role === "user"
                            ? "bg-[var(--primary)] text-white"
                            : "bg-gradient-to-br from-[var(--primary)] to-cyan-500 text-white"
                        } ${isHistory ? "opacity-50" : ""}`}>
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

                          {/* Play again */}
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

              {/* Thinking indicator */}
              {sending && !messages[messages.length - 1]?.streaming && (
                <div className="flex justify-start">
                  <div className="flex items-end gap-2.5">
                    <div className="w-7 h-7 rounded-full flex-none flex items-center justify-center text-[10px] font-bold mb-5 bg-gradient-to-br from-[var(--primary)] to-cyan-500 text-white">AI</div>
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
          )}
        </div>

        {/* ── Input area ───────────────────────────────────────────────────── */}
        <div className="flex-none border-t border-[var(--border)] bg-[var(--bg-card)] px-4 sm:px-6 py-3">
          <div className="max-w-3xl mx-auto flex items-center gap-2">
            <input
              ref={inputRef}
              type="text"
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(input); } }}
              placeholder={
                listening ? "Listening…" :
                selectedPersona ? `Message ${selectedPersona.label}…` :
                "Ask about today's AI intelligence…"
              }
              disabled={sending || listening}
              className="flex-1 px-4 py-2.5 rounded-xl border border-[var(--border)] bg-[var(--bg)] text-[var(--text-primary)] text-sm placeholder:text-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-[var(--primary)]/25 focus:border-[var(--primary)] transition-colors disabled:opacity-60"
            />

            <button type="button" onClick={listening ? undefined : handleVoiceInput}
              disabled={sending}
              className={`w-9 h-9 rounded-xl flex-none flex items-center justify-center transition-all ${
                listening ? "bg-red-500 text-white animate-pulse" : "border border-[var(--border)] text-[var(--text-muted)] hover:border-[var(--primary)] hover:text-[var(--primary)]"
              } disabled:opacity-40`}>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/>
                <path d="M19 10v2a7 7 0 0 1-14 0v-2M12 19v4M8 23h8"/>
              </svg>
            </button>

            <button type="button" onClick={() => sendMessage(input)}
              disabled={!input.trim() || sending}
              className="w-9 h-9 rounded-xl flex-none flex items-center justify-center bg-[var(--primary)] hover:bg-[var(--primary-hover)] text-white transition-all disabled:opacity-40 disabled:cursor-not-allowed shadow-sm">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/>
              </svg>
            </button>
          </div>
        </div>

      </div>
    </div>
  );
}
