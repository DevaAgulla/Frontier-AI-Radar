"use client";

import React, { useState, useEffect, useRef, useCallback } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { useAuth } from "@/app/context/AuthContext";

// ── Types ──────────────────────────────────────────────────────────────────────

type VoiceState = "idle" | "connecting" | "listening" | "thinking" | "speaking" | "error";
type TranscriptRole = "user" | "assistant" | "tool_status";

interface Transcript {
  role:       TranscriptRole;
  text:       string;
  streaming?: boolean;
  audioUrl?:  string;      // blob URL (in-memory) or data URL (from IDB) for replay
  timestamp?: Date;
  toolName?:  string;
  toolPhase?: "start" | "end";
}

// ── IndexedDB Audio Store ─────────────────────────────────────────────────────
//
// Persists MP3 audio for every completed assistant turn so users can replay
// responses after a page refresh. Stored as raw ArrayBuffer (no base64 penalty).
//
// Key schema:  `${sessionId}-${assistantTurnIndex}`
//   - assistantTurnIndex is 0-based across the entire session lifetime
//   - Interrupted turns (saved as "[paused]") increment the counter but have
//     no audio entry — IDB load returns null gracefully
//
// Eviction: oldest entries removed once total count exceeds MAX_ENTRIES (200).
// At ~50 KB/response average, 200 entries ≈ 10 MB — well within browser limits.

class VoiceAudioStore {
  private static readonly DB_NAME     = "frontier-voice-audio";
  private static readonly STORE       = "clips";
  private static readonly VERSION     = 1;
  private static readonly MAX_ENTRIES = 200;

  private dbP: Promise<IDBDatabase> | null = null;

  private _open(): Promise<IDBDatabase> {
    if (this.dbP) return this.dbP;
    this.dbP = new Promise((resolve, reject) => {
      if (typeof indexedDB === "undefined") { reject(new Error("no IDB")); return; }
      const req = indexedDB.open(VoiceAudioStore.DB_NAME, VoiceAudioStore.VERSION);
      req.onupgradeneeded = (e) => {
        const db    = (e.target as IDBOpenDBRequest).result;
        const store = db.createObjectStore(VoiceAudioStore.STORE, { keyPath: "key" });
        store.createIndex("createdAt", "createdAt"); // for LRU eviction
      };
      req.onsuccess = (e) => resolve((e.target as IDBOpenDBRequest).result);
      req.onerror   = () => { this.dbP = null; reject(req.error); };
    });
    return this.dbP;
  }

  /** Save MP3 chunks under `key`; returns an object URL for immediate playback. */
  async save(key: string, chunks: ArrayBuffer[]): Promise<string | null> {
    try {
      const db   = await this._open();
      const blob = new Blob(chunks, { type: "audio/mpeg" });
      const buf  = await blob.arrayBuffer();
      await new Promise<void>((ok, fail) => {
        const tx = db.transaction(VoiceAudioStore.STORE, "readwrite");
        tx.objectStore(VoiceAudioStore.STORE).put({ key, data: buf, createdAt: Date.now() });
        tx.oncomplete = () => ok();
        tx.onerror    = () => fail(tx.error);
      });
      this._evict(); // fire-and-forget LRU cleanup
      return URL.createObjectURL(blob);
    } catch { return null; }
  }

  /** Load a stored clip; returns an object URL or null if not cached. */
  async load(key: string): Promise<string | null> {
    try {
      const db  = await this._open();
      const row: any = await new Promise((ok, fail) => {
        const tx  = db.transaction(VoiceAudioStore.STORE, "readonly");
        const req = tx.objectStore(VoiceAudioStore.STORE).get(key);
        req.onsuccess = () => ok(req.result ?? null);
        req.onerror   = () => fail(req.error);
      });
      if (!row) return null;
      const blob = new Blob([row.data as ArrayBuffer], { type: "audio/mpeg" });
      return URL.createObjectURL(blob);
    } catch { return null; }
  }

  private async _evict(): Promise<void> {
    try {
      const db    = await this._open();
      const count = await new Promise<number>((ok, fail) => {
        const tx  = db.transaction(VoiceAudioStore.STORE, "readonly");
        const req = tx.objectStore(VoiceAudioStore.STORE).count();
        req.onsuccess = () => ok(req.result);
        req.onerror   = () => fail(req.error);
      });
      if (count <= VoiceAudioStore.MAX_ENTRIES) return;
      // Collect the oldest `count - MAX_ENTRIES` keys
      const toDelete = count - VoiceAudioStore.MAX_ENTRIES;
      const keys: IDBValidKey[] = await new Promise((ok, fail) => {
        const tx  = db.transaction(VoiceAudioStore.STORE, "readonly");
        const req = tx.objectStore(VoiceAudioStore.STORE).index("createdAt").getAllKeys();
        req.onsuccess = () => ok((req.result as IDBValidKey[]).slice(0, toDelete));
        req.onerror   = () => fail(req.error);
      });
      await new Promise<void>((ok, fail) => {
        const tx = db.transaction(VoiceAudioStore.STORE, "readwrite");
        keys.forEach(k => tx.objectStore(VoiceAudioStore.STORE).delete(k));
        tx.oncomplete = () => ok();
        tx.onerror    = () => fail(tx.error);
      });
    } catch {}
  }
}

// ── Streaming Audio Player (MediaSource Extensions) ───────────────────────────
//
// Change from previous version: `onBlobReady` replaced by `onTurnComplete(chunks)`
// so the component can persist chunks to IndexedDB before creating the blob URL.

class StreamingAudioPlayer {
  private ms!:      MediaSource;
  private sb:       SourceBuffer | null = null;
  private audio!:   HTMLAudioElement;
  private blobUrl!: string;
  private pending:  ArrayBuffer[] = [];
  private chunks:   ArrayBuffer[] = [];
  private ready     = false;
  private turnDone  = false;

  onPlaybackEnd?:   () => void;
  onTurnComplete?:  (chunks: ArrayBuffer[]) => void; // replaces onBlobReady

  constructor() { this._init(); }

  private _init() {
    this.ms      = new MediaSource();
    this.audio   = new Audio();
    this.blobUrl = URL.createObjectURL(this.ms);
    this.audio.src = this.blobUrl;
    this.audio.preload = "auto";
    this.audio.addEventListener("ended", () => this.onPlaybackEnd?.());
    this.ms.addEventListener("sourceopen", () => {
      try {
        this.sb = this.ms.addSourceBuffer("audio/mpeg");
        this.sb.mode = "sequence";
        this.sb.addEventListener("updateend", () => this._flush());
        this.ready = true;
        this._flush();
      } catch (e) { console.warn("[Audio] MSE init:", e); }
    });
  }

  resume() { this.audio.play().catch(() => {}); }

  push(chunk: ArrayBuffer) {
    if (this.turnDone) return;
    const copy = chunk.slice(0);
    this.chunks.push(copy);
    this.pending.push(copy);
    this._flush();
    if (this.audio.paused && this.audio.readyState >= 3) {
      this.audio.play().catch(() => {});
    }
  }

  private _flush() {
    if (!this.ready || !this.sb || this.sb.updating || this.pending.length === 0) return;
    const totalLen = this.pending.reduce((n, b) => n + b.byteLength, 0);
    const merged   = new Uint8Array(totalLen);
    let off = 0;
    for (const c of this.pending) { merged.set(new Uint8Array(c), off); off += c.byteLength; }
    this.pending = [];
    try {
      this.sb.appendBuffer(merged.buffer);
    } catch (e: any) {
      if (e?.name === "QuotaExceededError") {
        const t = this.audio.currentTime;
        if (t > 1) try { this.sb.remove(0, t - 0.5); } catch {}
        this.pending.unshift(merged.buffer);
      } else { console.warn("[Audio] appendBuffer:", e); }
    }
  }

  endTurn() {
    this.turnDone = true;
    if (this.chunks.length > 0) {
      this.onTurnComplete?.(this.chunks.slice()); // pass copy; component saves to IDB
    }
    const tryEnd = () => {
      if (this.ms.readyState === "open") try { this.ms.endOfStream(); } catch {}
    };
    if (this.sb?.updating) {
      this.sb.addEventListener("updateend", tryEnd, { once: true });
    } else { tryEnd(); }
  }

  stop() {
    this.audio.pause();
    try { URL.revokeObjectURL(this.blobUrl); } catch {}
    this.sb = null; this.ready = false; this.turnDone = false;
    this.pending = []; this.chunks = [];
    this._init();
  }
}

// ── Replay button ──────────────────────────────────────────────────────────────

function ReplayButton({ audioUrl }: { audioUrl: string }) {
  const [playing, setPlaying] = useState(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  const toggle = useCallback(() => {
    if (playing) {
      audioRef.current?.pause();
      if (audioRef.current) audioRef.current.currentTime = 0;
      setPlaying(false);
    } else {
      const a = new Audio(audioUrl);
      audioRef.current = a;
      a.onended = () => setPlaying(false);
      a.play().catch(() => setPlaying(false));
      setPlaying(true);
    }
  }, [audioUrl, playing]);

  useEffect(() => () => { audioRef.current?.pause(); }, []);

  return (
    <button onClick={toggle} title={playing ? "Stop" : "Replay"}
      className={`inline-flex items-center gap-1 ml-2 px-1.5 py-0.5 rounded text-xs transition-colors
        ${playing ? "text-blue-500 bg-blue-50" : "text-[var(--text-secondary)] hover:text-blue-500 hover:bg-blue-50"}`}>
      {playing
        ? <svg width="10" height="10" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="6" width="12" height="12" rx="1"/></svg>
        : <svg width="10" height="10" viewBox="0 0 24 24" fill="currentColor"><polygon points="5,3 19,12 5,21"/></svg>}
      {playing ? "Stop" : "Replay"}
    </button>
  );
}

// ── Stop-command classifier ───────────────────────────────────────────────────

// Patterns that indicate the user wants to stop the voice interaction.
// Checked during barge-in (while AI speaks) and hands-free listening (after AI finishes).
const STOP_PATTERNS = [
  /^(stop|pause|cancel|enough|quiet|silence)$/,
  /\bshut up\b/,
  /\bstop (talking|speaking|now|it|please)\b/,
  /\byou can stop\b/,
  /\bplease (stop|pause|be quiet)\b/,
  /\bok(ay)? (stop|pause)\b/,
  /\bthat'?s (all|enough|fine|ok|okay|good|great)\b/,
  /\bno (more|thanks?|thank you)\b/,
  /\bi('m| am) (good|done|all set|fine|ok|okay)\b/,
  /\b(thanks?|thank you)[\s,]*.*\b(stop|that'?s all|enough)\b/,
  /\bstop[\s,]+thanks?\b/,
];

function isStopCommand(text: string): boolean {
  const lower = text.toLowerCase().trim();
  return STOP_PATTERNS.some(p => p.test(lower));
}

// ── Component ─────────────────────────────────────────────────────────────────

export default function VoicePage() {
  const { run_id } = useParams<{ run_id: string }>();
  const { user }   = useAuth();

  const [voiceState,  setVoiceState]  = useState<VoiceState>("connecting");
  const [transcripts, setTranscripts] = useState<Transcript[]>([]);
  const [statusLabel, setStatusLabel] = useState("Connecting…");
  const [wsReady,     setWsReady]     = useState(false);
  const [errorMsg,    setErrorMsg]    = useState("");
  const [interimText, setInterimText] = useState("");

  // ── Stable refs (safe in stale closures) ────────────────────────────────────
  const wsRef               = useRef<WebSocket | null>(null);
  const audioPlayerRef      = useRef<StreamingAudioPlayer | null>(null);
  const bottomRef           = useRef<HTMLDivElement>(null);
  const streamingIdxRef     = useRef(-1);
  const recognitionRef      = useRef<any>(null);
  const bargeInRecRef       = useRef<any>(null);
  const bargeInActiveRef    = useRef(false);
  const aiSpeakingRef       = useRef(false);
  const interruptSentRef    = useRef(false);
  const sessionIdRef        = useRef("");          // stable session ID from WS/API
  const assistantTurnRef    = useRef(0);           // next assistant audio key index
  const userTurnRef         = useRef(0);           // next user audio key index
  const mediaRecorderRef    = useRef<MediaRecorder | null>(null); // active mic recorder
  const audioStoreRef       = useRef<VoiceAudioStore | null>(null);
  const wsReadyRef          = useRef(false);       // mirror wsReady for callbacks
  const pendingActionRef    = useRef<"greeting" | "listen" | null>(null);
  const startListeningRef   = useRef<() => void>(() => {});
  const bufferedTextRef     = useRef("");          // text_chunks queued before audio_start fires
  const audioStartedRef     = useRef(false);       // true once audio_start fires for current turn

  // ── Init audio store once ────────────────────────────────────────────────────
  useEffect(() => { audioStoreRef.current = new VoiceAudioStore(); }, []);

  // ── Scroll to bottom ─────────────────────────────────────────────────────────
  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: "smooth" }); },
    [transcripts, interimText]);

  // ── Cleanup ───────────────────────────────────────────────────────────────────
  useEffect(() => () => { _disconnect(); }, []);

  // ── Fetch voice history from API ─────────────────────────────────────────────
  const fetchHistory = useCallback(async () => {
    try {
      const base   = (process.env.NEXT_PUBLIC_API_URL || "").replace(/\/$/, "");
      const qs     = user?.id ? `?user_id=${user.id}` : "";
      const res    = await fetch(`${base}/api/v1/voice/${run_id}/history${qs}`);
      if (!res.ok) return;
      const data   = await res.json();

      sessionIdRef.current = data.session_id;

      // Build transcript from history (text only — audio loaded lazily below)
      const msgs: Transcript[] = (data.messages as any[]).map(m => ({
        role:      m.role as TranscriptRole,
        text:      String(m.content ?? "").replace(/ \[paused\]$/, ""),
        timestamp: m.created_at ? new Date(m.created_at) : undefined,
      }));

      // IMPORTANT: only replace transcripts when there is real history to show.
      // If msgs is empty (brand-new session), the WS greeting pipeline may have
      // already appended a streaming bubble — calling setTranscripts([]) here
      // would erase it and break capturedTranscriptIdx / audioUrl patching.
      if (msgs.length > 0) {
        setTranscripts(msgs);
      }

      // Count turns for audio key sequencing (assistant keys and user keys)
      let aIdx = 0, uIdx = 0;
      const audioJobs: { transcriptIdx: number; key: string }[] = [];
      msgs.forEach((m, ti) => {
        if (m.role === "assistant") {
          audioJobs.push({ transcriptIdx: ti, key: `${data.session_id}-${aIdx}` });
          aIdx++;
        } else if (m.role === "user") {
          audioJobs.push({ transcriptIdx: ti, key: `${data.session_id}-user-${uIdx}` });
          uIdx++;
        }
      });
      assistantTurnRef.current = aIdx; // next new assistant turn starts here
      userTurnRef.current      = uIdx; // next new user turn starts here

      // Load cached audio in background — update bubbles as each resolves
      audioJobs.forEach(({ transcriptIdx, key }) => {
        audioStoreRef.current?.load(key).then(url => {
          if (!url) return;
          setTranscripts(prev => {
            const next = [...prev];
            if (next[transcriptIdx]) next[transcriptIdx] = { ...next[transcriptIdx], audioUrl: url };
            return next;
          });
        });
      });

      // Decide what to do once WS is ready
      pendingActionRef.current = data.is_new ? "greeting" : "listen";
      if (wsReadyRef.current) {
        if (data.is_new) wsRef.current?.send(JSON.stringify({ type: "greeting" }));
        else             startListeningRef.current();
      }
    } catch (e) {
      console.error("[VoiceAgent] fetchHistory error:", e);
    }
  }, [run_id, user?.id]);

  // ── Auto-connect + history on mount ──────────────────────────────────────────
  useEffect(() => {
    _connect();
    fetchHistory();
  }, [run_id]);

  // ── Barge-in cycle (runs while AI is speaking) ─────────────────────────────
  const _startBargeIn = useCallback(() => {
    const SR = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (!SR || bargeInActiveRef.current) return;
    bargeInActiveRef.current = true;

    function _shot() {
      if (!bargeInActiveRef.current) return;
      const rec = new SR();
      rec.continuous = false; rec.interimResults = true; rec.lang = "en-US";
      bargeInRecRef.current = rec;

      rec.onresult = (event: any) => {
        let interim = "", final = "";
        for (let i = event.resultIndex; i < event.results.length; i++) {
          const t = event.results[i][0].transcript;
          if (event.results[i].isFinal) final += t; else interim += t;
        }
        if (interim) setInterimText(interim);
        if (final.trim()) {
          setInterimText("");
          const text = final.trim();
          if (aiSpeakingRef.current && !interruptSentRef.current) {
            interruptSentRef.current = true;
            audioPlayerRef.current?.stop();
            wsRef.current?.send(JSON.stringify({ type: "interrupt" }));
            if (isStopCommand(text)) {
              // User wants to stop — kill barge-in cycle so it doesn't restart
              bargeInActiveRef.current = false;
              setVoiceState("idle"); setStatusLabel("Tap to speak");
            } else {
              setTranscripts(prev => [
                ...prev.filter(t => t.role !== "tool_status"),
                { role: "user", text, timestamp: new Date() },
              ]);
              wsRef.current?.send(JSON.stringify({ type: "user_text", text, barge_in: true }));
              setVoiceState("thinking"); setStatusLabel("Thinking…");
            }
          } else if (!aiSpeakingRef.current) {
            // Hands-free post-AI listening — check for stop before querying LLM
            if (isStopCommand(text)) {
              setInterimText("");
              bargeInActiveRef.current = false;
              setVoiceState("idle"); setStatusLabel("Tap to speak");
            } else {
              setTranscripts(prev => [...prev, { role: "user", text, timestamp: new Date() }]);
              wsRef.current?.send(JSON.stringify({ type: "user_text", text }));
              setVoiceState("thinking"); setStatusLabel("Thinking…");
            }
          }
        }
      };
      rec.onerror = (e: any) => {
        bargeInRecRef.current = null;
        if (e.error === "not-allowed") { bargeInActiveRef.current = false; return; }
        if (bargeInActiveRef.current) setTimeout(_shot, 300);
      };
      rec.onend = () => {
        bargeInRecRef.current = null;
        if (bargeInActiveRef.current) setTimeout(_shot, 150);
      };
      try { rec.start(); } catch { bargeInActiveRef.current = false; }
    }
    _shot();
  }, []);

  const _stopBargeIn = useCallback(() => {
    bargeInActiveRef.current = false;
    if (bargeInRecRef.current) { try { bargeInRecRef.current.abort(); } catch {} bargeInRecRef.current = null; }
  }, []);

  // ── WebSocket connect ─────────────────────────────────────────────────────────
  const _connect = useCallback(async () => {
    setVoiceState("connecting");
    setStatusLabel("Connecting…");
    setErrorMsg("");

    const protocol = window.location.protocol === "https:" ? "wss" : "ws";
    const base     = process.env.NEXT_PUBLIC_API_URL?.replace(/^https?:\/\//, "") || window.location.host;
    const userId   = user?.id ? `?user_id=${user.id}` : "";
    const url      = `${protocol}://${base}/api/v1/voice/${run_id}${userId}`;

    console.log("[VoiceAgent] Connecting →", url);
    const ws = new WebSocket(url);
    wsRef.current   = ws;
    ws.binaryType   = "arraybuffer";

    ws.onmessage = (ev) => {
      if (ev.data instanceof ArrayBuffer) { audioPlayerRef.current?.push(ev.data.slice(0)); return; }
      try { _handleMsg(JSON.parse(ev.data as string)); } catch {}
    };
    ws.onerror = () => {
      setVoiceState("error");
      setErrorMsg(`Cannot connect to ${url} — is the backend running?`);
      setStatusLabel("Connection failed");
    };
    ws.onclose = () => { wsReadyRef.current = false; setWsReady(false); };
  }, [run_id, user?.id]);

  const _disconnect = useCallback(() => {
    _stopBargeIn();
    if (recognitionRef.current) { try { recognitionRef.current.stop(); } catch {} recognitionRef.current = null; }
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== "inactive") {
      try { mediaRecorderRef.current.stop(); } catch {} mediaRecorderRef.current = null;
    }
    audioPlayerRef.current?.stop();
    if (wsRef.current) {
      const ws = wsRef.current;
      wsRef.current = null;
      // Avoid "WebSocket closed before connection established" (Chrome error) by
      // deferring close until after the handshake when still in CONNECTING state.
      if (ws.readyState === WebSocket.CONNECTING) {
        ws.onopen  = () => ws.close();
        ws.onerror = () => {};
      } else if (ws.readyState === WebSocket.OPEN) {
        ws.close();
      }
      // CLOSING (2) or CLOSED (3) — nothing to do
    }
    wsReadyRef.current = false; setWsReady(false);
    setVoiceState("idle"); setStatusLabel("Tap to speak"); setInterimText("");
    aiSpeakingRef.current = false;
  }, [_stopBargeIn]);

  // ── Server message handler ────────────────────────────────────────────────────
  const _handleMsg = useCallback((msg: any) => {
    switch (msg.type) {

      case "ready": {
        if (msg.session_id) sessionIdRef.current = msg.session_id;
        setWsReady(true); wsReadyRef.current = true;
        setVoiceState("idle");
        audioPlayerRef.current = new StreamingAudioPlayer();

        // Trigger greeting or start listening depending on history fetch result
        const action = pendingActionRef.current;
        if (action === "greeting") {
          wsRef.current?.send(JSON.stringify({ type: "greeting" }));
        } else if (action === "listen") {
          setStatusLabel("Listening…");
          setTimeout(() => startListeningRef.current(), 200);
        } else {
          // History not loaded yet — will be handled when fetchHistory completes
          setStatusLabel("Ready");
        }
        break;
      }

      case "thinking": {
        audioPlayerRef.current?.stop();
        _stopBargeIn();
        aiSpeakingRef.current  = false;
        interruptSentRef.current = false;

        // Capture turn index NOW (before async audio save changes it)
        const thisTurnIndex         = assistantTurnRef.current;
        assistantTurnRef.current   += 1; // always increment, even for interrupted turns
        let capturedTranscriptIdx   = -1;

        const player = audioPlayerRef.current;
        if (player) {
          player.onPlaybackEnd = () => {
            aiSpeakingRef.current = false;
            _stopBargeIn();
            setVoiceState("idle");
            setStatusLabel("Listening…");
            // Always hands-free: auto-restart listening after AI finishes
            setTimeout(() => startListeningRef.current(), 300);
          };
          player.onTurnComplete = async (chunks: ArrayBuffer[]) => {
            const key = `${sessionIdRef.current}-${thisTurnIndex}`;
            const url = await audioStoreRef.current?.save(key, chunks) ?? null;
            if (url && capturedTranscriptIdx >= 0) {
              setTranscripts(prev => {
                const next = [...prev];
                if (next[capturedTranscriptIdx]) {
                  next[capturedTranscriptIdx] = { ...next[capturedTranscriptIdx], audioUrl: url };
                }
                return next;
              });
            }
          };
        }

        bufferedTextRef.current = "";
        audioStartedRef.current = false;
        setVoiceState("thinking"); setStatusLabel("Thinking…");
        setTranscripts(prev => {
          const next = [...prev, { role: "assistant" as const, text: "", streaming: true, timestamp: new Date() }];
          streamingIdxRef.current = next.length - 1;
          capturedTranscriptIdx   = next.length - 1;
          return next;
        });
        break;
      }

      case "text_chunk":
        if (audioStartedRef.current) {
          // Audio already playing — stream text live so it syncs with speech
          setTranscripts(prev => {
            const next = [...prev];
            const idx  = streamingIdxRef.current;
            if (idx >= 0 && next[idx]) next[idx] = { ...next[idx], text: next[idx].text + msg.text };
            return next;
          });
        } else {
          // Audio not started yet — buffer text to avoid text appearing before voice
          bufferedTextRef.current += msg.text;
        }
        break;

      case "audio_start":
        setVoiceState("speaking");
        setStatusLabel("Speaking… (speak to interrupt)");
        aiSpeakingRef.current    = true;
        interruptSentRef.current = false;
        audioPlayerRef.current?.resume();
        audioStartedRef.current = true;
        // Flush any text buffered before audio started — text and audio now appear together
        if (bufferedTextRef.current) {
          const flushed = bufferedTextRef.current;
          bufferedTextRef.current = "";
          setTranscripts(prev => {
            const next = [...prev];
            const idx  = streamingIdxRef.current;
            if (idx >= 0 && next[idx]) next[idx] = { ...next[idx], text: flushed };
            return next;
          });
        }
        // Stop any foreground PTT, start barge-in cycle
        if (recognitionRef.current) { try { recognitionRef.current.stop(); } catch {} recognitionRef.current = null; }
        _startBargeIn();
        break;

      case "audio_end":
        break; // MSE plays continuously — no-op

      case "turn_done":
        // Fallback flush: if no audio (no ElevenLabs key), text was buffered — reveal it now
        bufferedTextRef.current = "";
        audioStartedRef.current = false;
        setTranscripts(prev => {
          const cleaned = prev.filter(t => t.role !== "tool_status");
          const next    = [...cleaned];
          const idx     = streamingIdxRef.current;
          if (idx >= 0 && next[idx]) next[idx] = { ...next[idx], text: msg.text, streaming: false };
          return next;
        });
        streamingIdxRef.current = -1;
        aiSpeakingRef.current   = false;
        _stopBargeIn();
        audioPlayerRef.current?.endTurn();
        break;

      case "interrupted":
        aiSpeakingRef.current = false;
        _stopBargeIn();
        audioPlayerRef.current?.stop();
        setVoiceState("idle"); setStatusLabel("Tap to speak");
        break;

      case "tool_status": {
        const { tool_name, phase, label } = msg;
        if (phase === "start") {
          setTranscripts(prev => {
            const cleaned = prev.filter(t => !(t.role === "tool_status" && t.toolName === tool_name));
            return [...cleaned, { role: "tool_status" as const, text: label, toolName: tool_name, toolPhase: "start", timestamp: new Date() }];
          });
          setStatusLabel(label);
        } else {
          setTranscripts(prev => prev.map(t =>
            t.role === "tool_status" && t.toolName === tool_name
              ? { ...t, text: label, toolPhase: "end" as const } : t
          ));
          setStatusLabel("Processing…");
        }
        break;
      }

      case "error":
        setErrorMsg(msg.message || "Unknown error");
        break;
    }
  }, [_startBargeIn, _stopBargeIn]);

  // ── Foreground PTT listener ───────────────────────────────────────────────────
  const _startListening = useCallback(() => {
    if (bargeInActiveRef.current) {
      _stopBargeIn();
      setTimeout(() => startListeningRef.current(), 150);
      return;
    }
    const SR = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (!SR) {
      setErrorMsg("Speech recognition not supported. Use Chrome or Edge.");
      setVoiceState("error"); return;
    }

    const rec = new SR();
    rec.continuous = false; rec.interimResults = true; rec.lang = "en-US"; rec.maxAlternatives = 1;
    recognitionRef.current = rec;

    // ── Capture mic audio for replay (MediaRecorder alongside SpeechRecognition) ─
    // Fails silently — user still gets full voice interaction, just no replay button.
    const audioChunks: Blob[] = [];
    const userTurnIdx = userTurnRef.current;
    userTurnRef.current += 1;
    let capturedUserIdx = -1;
    if (typeof MediaRecorder !== "undefined" && navigator.mediaDevices?.getUserMedia) {
      navigator.mediaDevices.getUserMedia({ audio: true, video: false }).then(stream => {
        const mimeType = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
          ? "audio/webm;codecs=opus"
          : MediaRecorder.isTypeSupported("audio/webm") ? "audio/webm" : "";
        const mr = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
        mediaRecorderRef.current = mr;
        mr.ondataavailable = (e) => { if (e.data.size > 0) audioChunks.push(e.data); };
        mr.onstop = async () => {
          stream.getTracks().forEach(t => t.stop()); // release mic track
          if (audioChunks.length === 0 || capturedUserIdx < 0) return;
          try {
            const blob = new Blob(audioChunks, { type: mr.mimeType || "audio/webm" });
            const buf  = await blob.arrayBuffer();
            const key  = `${sessionIdRef.current}-user-${userTurnIdx}`;
            const url  = await audioStoreRef.current?.save(key, [buf]) ?? null;
            if (url) {
              setTranscripts(prev => {
                const next = [...prev];
                if (next[capturedUserIdx]) next[capturedUserIdx] = { ...next[capturedUserIdx], audioUrl: url };
                return next;
              });
            }
          } catch {}
        };
        mr.start();
      }).catch(() => {}); // permission denied or not supported — continue without recording
    }

    let lastInterim = "", finalFired = false;
    const _stopRecording = () => {
      if (mediaRecorderRef.current && mediaRecorderRef.current.state !== "inactive") {
        mediaRecorderRef.current.stop();
        mediaRecorderRef.current = null;
      }
    };
    const _submit = (text: string) => {
      setInterimText("");
      if (isStopCommand(text)) {
        setVoiceState("idle"); setStatusLabel("Tap to speak");
        _stopRecording();
        return;
      }
      setTranscripts(prev => {
        const next = [...prev, { role: "user" as const, text, timestamp: new Date() }];
        capturedUserIdx = next.length - 1;
        return next;
      });
      _stopRecording(); // triggers onstop → saves audio to IDB
      wsRef.current?.send(JSON.stringify({ type: "user_text", text }));
      setVoiceState("thinking"); setStatusLabel("Thinking…");
    };

    rec.onstart = () => { setVoiceState("listening"); setStatusLabel("Listening… speak now"); setInterimText(""); };

    rec.onresult = (event: any) => {
      let interim = "", final = "";
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const t = event.results[i][0].transcript;
        if (event.results[i].isFinal) final += t; else interim += t;
      }
      if (interim) { lastInterim = interim; setInterimText(interim); }
      if (final.trim()) { finalFired = true; lastInterim = ""; _submit(final.trim()); }
    };

    rec.onerror = (e: any) => {
      recognitionRef.current = null; setInterimText("");
      _stopRecording();
      if (e.error === "not-allowed") {
        setErrorMsg("Microphone access denied. Allow mic in browser settings.");
        setVoiceState("error");
      } else {
        setVoiceState("idle"); setStatusLabel("Tap to speak");
      }
    };

    rec.onend = () => {
      if (recognitionRef.current !== rec) return;
      recognitionRef.current = null;
      if (finalFired) return;
      if (lastInterim.trim() && wsRef.current?.readyState === WebSocket.OPEN) {
        _submit(lastInterim.trim());
      } else {
        setVoiceState(v => v === "listening" ? "idle" : v);
        setStatusLabel("Tap to speak"); setInterimText("");
      }
    };

    try { rec.start(); } catch (e) {
      recognitionRef.current = null; setVoiceState("idle"); setStatusLabel("Tap to speak");
      console.warn("[VoiceAgent] rec.start() failed:", e);
    }
  }, [_stopBargeIn]);

  // Keep ref fresh for callbacks (onPlaybackEnd, pendingAction)
  useEffect(() => { startListeningRef.current = _startListening; }, [_startListening]);

  const _stopListening = useCallback(() => {
    if (recognitionRef.current) { recognitionRef.current.stop(); recognitionRef.current = null; }
    setInterimText("");
  }, []);

  // ── Mic button (manual fallback) ─────────────────────────────────────────────
  const handleMicPress = useCallback(async () => {
    if (!wsReady) { await _connect(); return; }
    if (voiceState === "listening") { _stopListening(); }
    else if (voiceState === "idle") { _startListening(); }
    else if (voiceState === "speaking") {
      aiSpeakingRef.current = false;
      _stopBargeIn();
      audioPlayerRef.current?.stop();
      wsRef.current?.send(JSON.stringify({ type: "interrupt" }));
      _startListening();
    }
  }, [wsReady, voiceState, _connect, _startListening, _stopListening, _stopBargeIn]);

  // ── Render ────────────────────────────────────────────────────────────────────

  const stateColor: Record<VoiceState, string> = {
    idle:       "bg-[var(--primary)]",
    connecting: "bg-yellow-400 animate-pulse",
    listening:  "bg-green-500 animate-pulse",
    thinking:   "bg-orange-400",
    speaking:   "bg-blue-500 animate-pulse",
    error:      "bg-red-500",
  };

  const micIcon = voiceState === "listening" ? (
    <svg width="28" height="28" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="6" width="12" height="12" rx="2"/></svg>
  ) : (
    <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/>
      <path d="M19 10v2a7 7 0 0 1-14 0v-2"/>
      <line x1="12" y1="19" x2="12" y2="23"/><line x1="8" y1="23" x2="16" y2="23"/>
    </svg>
  );

  const fmt = (d?: Date) => d?.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) ?? "";

  return (
    <div className="flex flex-col h-screen bg-[var(--bg-main)]">

      {/* Header */}
      <div className="flex items-center gap-3 px-4 py-3 border-b border-[var(--border)] bg-[var(--bg-card)]">
        <Link href={`/digest/${run_id}`}
          className="text-[var(--text-secondary)] hover:text-[var(--primary)] transition-colors">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M19 12H5M12 19l-7-7 7-7"/>
          </svg>
        </Link>
        <div>
          <h1 className="text-sm font-semibold text-[var(--text-primary)]">Voice Agent</h1>
          <p className="text-xs text-[var(--text-secondary)]">Digest #{run_id} · Hands-free</p>
        </div>
        <div className="ml-auto flex items-center gap-3">
          {transcripts.filter(t => t.role !== "tool_status").length > 0 && (
            <button
              onClick={() => {
                transcripts.forEach(t => { if (t.audioUrl) URL.revokeObjectURL(t.audioUrl); });
                setTranscripts([]);
              }}
              className="text-xs text-[var(--text-secondary)] hover:text-red-400 transition-colors"
            >Clear</button>
          )}
          <div className="flex items-center gap-1.5">
            <div className={`w-2 h-2 rounded-full transition-colors ${wsReady ? "bg-green-500" : "bg-gray-400"}`}/>
            <span className="text-xs text-[var(--text-secondary)]">{wsReady ? "Connected" : "Connecting…"}</span>
          </div>
        </div>
      </div>

      {/* Conversation */}
      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-3">
        {transcripts.filter(t => t.role !== "tool_status").length === 0 && !interimText && (
          <div className="text-center text-[var(--text-secondary)] text-sm mt-16">
            <div className="text-4xl mb-3">🎙️</div>
            <p className="font-medium text-base text-[var(--text-primary)]">Voice Agent</p>
            <p className="mt-1 text-xs max-w-xs mx-auto leading-relaxed opacity-70">
              Fully hands-free. Radar will greet you and start listening automatically.
              Speak any time — even while Radar is talking — to interrupt or ask more.
            </p>
          </div>
        )}

        {transcripts.map((t, i) => {

          // Tool status row
          if (t.role === "tool_status") {
            return (
              <div key={i} className="flex items-center gap-2 px-1">
                {t.toolPhase === "start"
                  ? <span className="w-3 h-3 border-2 border-[var(--primary)] border-t-transparent rounded-full animate-spin shrink-0"/>
                  : <svg className="w-3 h-3 text-green-500 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3"><polyline points="20 6 9 17 4 12"/></svg>
                }
                <span className={`text-xs ${t.toolPhase === "start" ? "text-[var(--primary)]" : "text-green-600"}`}>
                  {t.text}
                </span>
              </div>
            );
          }

          // User / assistant bubble
          return (
            <div key={i} className={`flex flex-col gap-0.5 ${t.role === "user" ? "items-end" : "items-start"}`}>
              <div className={`flex items-center gap-1.5 px-1 ${t.role === "user" ? "flex-row-reverse" : ""}`}>
                <span className="text-[10px] font-medium text-[var(--text-secondary)]">
                  {t.role === "user" ? "You" : "Radar"}
                </span>
                <span className="text-[10px] text-[var(--text-secondary)] opacity-50">{fmt(t.timestamp)}</span>
              </div>
              <div className={`max-w-[80%] px-4 py-2.5 rounded-2xl text-sm leading-relaxed ${
                t.role === "user"
                  ? "bg-[var(--primary)] text-white rounded-br-sm"
                  : "bg-[var(--bg-card)] border border-[var(--border)] text-[var(--text-primary)] rounded-bl-sm"
              }`}>
                {t.role === "user" && <span className="mr-1.5 opacity-70 text-xs">🎤</span>}
                {t.role === "user" && t.audioUrl && <ReplayButton audioUrl={t.audioUrl}/>}
                {t.text || (t.streaming ? (
                  <span className="flex items-center gap-1.5">
                    <span className="text-xs opacity-60">Thinking</span>
                    <span className="flex gap-0.5">
                      {[0,150,300].map(d => (
                        <span key={d} className="w-1 h-1 bg-current rounded-full animate-bounce"
                          style={{ animationDelay: `${d}ms` }}/>
                      ))}
                    </span>
                  </span>
                ) : "")}
                {t.role === "assistant" && !t.streaming && t.audioUrl && <ReplayButton audioUrl={t.audioUrl}/>}
                {t.role === "assistant" && !t.streaming && t.text && !t.audioUrl && (
                  <span className="ml-1.5 opacity-30 text-xs">🔊</span>
                )}
              </div>
            </div>
          );
        })}

        {/* Interim bubble */}
        {interimText && (
          <div className="flex flex-col items-end gap-0.5">
            <div className="flex items-center gap-1.5 px-1 flex-row-reverse">
              <span className="text-[10px] font-medium text-[var(--text-secondary)]">You</span>
            </div>
            <div className="max-w-[80%] px-4 py-2.5 rounded-2xl text-sm bg-[var(--primary)]/50 text-white rounded-br-sm italic opacity-80">
              <span className="mr-1 text-xs">🎤</span>{interimText}…
            </div>
          </div>
        )}
        <div ref={bottomRef}/>
      </div>

      {/* Error banner */}
      {errorMsg && (
        <div className="mx-4 mb-2 px-3 py-2 bg-red-50 border border-red-200 rounded-lg text-red-700 text-xs flex items-start gap-2">
          <span>⚠️</span><span className="flex-1">{errorMsg}</span>
          <button onClick={() => setErrorMsg("")} className="font-bold shrink-0">×</button>
        </div>
      )}

      {/* Mic button — manual fallback, always visible */}
      <div className="flex flex-col items-center pb-10 pt-4 gap-3">
        <p className="text-xs text-[var(--text-secondary)] h-4">{statusLabel}</p>

        <button
          onClick={handleMicPress}
          disabled={voiceState === "thinking" || voiceState === "connecting"}
          className={`w-20 h-20 rounded-full flex items-center justify-center text-white shadow-lg
            transition-all ${stateColor[voiceState]} hover:opacity-90 active:scale-95
            disabled:opacity-50 disabled:cursor-not-allowed`}
          aria-label={voiceState === "listening" ? "Stop recording" : "Start speaking"}
        >
          {voiceState === "thinking"
            ? <span className="flex gap-1">{[0,100,200].map(d => (
                <span key={d} className="w-2 h-2 bg-white rounded-full animate-bounce" style={{ animationDelay: `${d}ms` }}/>
              ))}</span>
            : micIcon}
        </button>

        {voiceState === "speaking" && (
          <p className="text-[10px] text-[var(--text-secondary)] text-center max-w-[200px] leading-relaxed opacity-70">
            Just speak to interrupt at any time
          </p>
        )}

        {wsReady && (
          <button onClick={_disconnect}
            className="text-xs text-[var(--text-secondary)] hover:text-red-400 transition-colors mt-1">
            End session
          </button>
        )}
      </div>
    </div>
  );
}
