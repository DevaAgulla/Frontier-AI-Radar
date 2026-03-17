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
  audioUrl?:  string;
  timestamp?: Date;
  toolName?:  string;
  toolPhase?: "start" | "end";
}

// ── IndexedDB Audio Store ─────────────────────────────────────────────────────
//
// Kept for audio replay. LiveKit handles real-time playback natively via WebRTC
// audio tracks — IDB is only used to store completed turns for the replay button.

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
        store.createIndex("createdAt", "createdAt");
      };
      req.onsuccess = (e) => resolve((e.target as IDBOpenDBRequest).result);
      req.onerror   = () => { this.dbP = null; reject(req.error); };
    });
    return this.dbP;
  }

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
      this._evict();
      return URL.createObjectURL(blob);
    } catch { return null; }
  }

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
      const excess = count - VoiceAudioStore.MAX_ENTRIES;
      const rows: any[] = await new Promise((ok, fail) => {
        const tx  = db.transaction(VoiceAudioStore.STORE, "readonly");
        const req = tx.objectStore(VoiceAudioStore.STORE).index("createdAt").getAll();
        req.onsuccess = () => ok(req.result);
        req.onerror   = () => fail(req.error);
      });
      rows.sort((a, b) => a.createdAt - b.createdAt);
      const toDelete = rows.slice(0, excess).map((r) => r.key);
      await new Promise<void>((ok, fail) => {
        const tx = db.transaction(VoiceAudioStore.STORE, "readwrite");
        toDelete.forEach((k) => tx.objectStore(VoiceAudioStore.STORE).delete(k));
        tx.oncomplete = () => ok();
        tx.onerror    = () => fail(tx.error);
      });
    } catch {}
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

const STOP_PATTERNS = [
  /^(stop|pause|cancel|enough|quiet|silence)$/,
  /\bshut up\b/, /\bstop (talking|speaking|now|it|please)\b/,
  /\byou can stop\b/, /\bplease (stop|pause|be quiet)\b/,
  /\bok(ay)? (stop|pause)\b/, /\bthat'?s (all|enough|fine|ok|okay|good|great)\b/,
  /\bno (more|thanks?|thank you)\b/, /\bi('m| am) (good|done|all set|fine|ok|okay)\b/,
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
  const [connected,   setConnected]   = useState(false);
  const [errorMsg,    setErrorMsg]    = useState("");
  const [interimText, setInterimText] = useState("");

  // ── Refs ──────────────────────────────────────────────────────────────────────
  const roomRef             = useRef<any>(null);                  // livekit Room
  const bottomRef           = useRef<HTMLDivElement>(null);
  const streamingIdxRef     = useRef(-1);
  const sessionIdRef        = useRef("");
  const assistantTurnRef    = useRef(0);
  const userTurnRef         = useRef(0);
  const audioStoreRef       = useRef<VoiceAudioStore | null>(null);
  const connectedRef        = useRef(false);                      // mirror for callbacks
  const aiSpeakingRef       = useRef(false);

  // ── Init audio store ──────────────────────────────────────────────────────────
  useEffect(() => { audioStoreRef.current = new VoiceAudioStore(); }, []);

  // ── Scroll to bottom ──────────────────────────────────────────────────────────
  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: "smooth" }); },
    [transcripts, interimText]);

  // ── Cleanup on unmount ────────────────────────────────────────────────────────
  useEffect(() => () => { _disconnect(); }, []);

  // ── Load voice history from API ───────────────────────────────────────────────
  const fetchHistory = useCallback(async () => {
    try {
      const base = (process.env.NEXT_PUBLIC_API_URL || "").replace(/\/$/, "");
      const qs   = user?.id ? `?user_id=${user.id}` : "";
      const res  = await fetch(`${base}/api/v1/voice/${run_id}/history${qs}`);
      if (!res.ok) return;
      const data = await res.json();

      sessionIdRef.current = data.session_id;

      const msgs: Transcript[] = (data.messages as any[]).map(m => ({
        role:      m.role as TranscriptRole,
        text:      String(m.content ?? "").replace(/ \[paused\]$/, ""),
        timestamp: m.created_at ? new Date(m.created_at) : undefined,
      }));

      if (msgs.length > 0) setTranscripts(msgs);

      // Count turns for audio key sequencing
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
      assistantTurnRef.current = aIdx;
      userTurnRef.current      = uIdx;

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
    } catch (e) {
      console.error("[LiveKitVoice] fetchHistory error:", e);
    }
  }, [run_id, user?.id]);

  // ── LiveKit connect ───────────────────────────────────────────────────────────
  const _connect = useCallback(async () => {
    setVoiceState("connecting");
    setStatusLabel("Connecting…");
    setErrorMsg("");

    try {
      // Dynamically import livekit-client to avoid SSR issues
      const { Room, RoomEvent, Track } = await import("livekit-client");

      // Get LiveKit token from our FastAPI endpoint
      const base       = (process.env.NEXT_PUBLIC_API_URL || "").replace(/\/$/, "");
      const voice      = globalThis.localStorage?.getItem("frontier_voice_preset") || "rachel";
      const personaId  = globalThis.localStorage?.getItem("frontier_active_persona") || "";
      const qs         = new URLSearchParams({
        run_id: String(run_id),
        ...(user?.id ? { user_id: String(user.id) } : {}),
        voice,
        ...(personaId ? { persona_id: personaId } : {}),
      });

      const tokenRes = await fetch(`${base}/api/v1/voice/livekit-token?${qs}`);
      if (!tokenRes.ok) {
        const err = await tokenRes.json().catch(() => ({}));
        throw new Error(err.detail || `Token error ${tokenRes.status}`);
      }
      const { token, ws_url } = await tokenRes.json();

      // Create and connect the LiveKit room
      const room = new Room({
        adaptiveStream: true,
        dynacast: true,
        audioCaptureDefaults: {
          noiseSuppression:  true,
          echoCancellation:  true,   // prevents mic from picking up AI speaker output
          autoGainControl:   true,
        },
      });
      roomRef.current = room;

      // ── Event: remote participant joins (agent connects) ────────────────────
      room.on(RoomEvent.ParticipantConnected, () => {
        setStatusLabel("Agent connected — speak now");
        setVoiceState("idle");
      });

      // ── Event: agent audio track published ──────────────────────────────────
      // LiveKit publishes ONE continuous audio track per participant for the whole
      // session — it is never "ended" between utterances, just silent.
      // We attach it once for playback; speaking state is tracked via
      // ActiveSpeakersChanged (audio energy level) not via track lifecycle events.
      const attachedTracks = new Set<string>();
      room.on(RoomEvent.TrackSubscribed, (track: any, publication: any, participant: any) => {
        if (track.kind !== Track.Kind.Audio) return;
        const trackKey = participant.identity + ":" + track.sid;
        if (attachedTracks.has(trackKey)) return; // already attached — never attach twice
        attachedTracks.add(trackKey);
        // Attach to a hidden <audio> element — LiveKit track.attach() returns
        // an HTMLAudioElement and starts playback automatically after user gesture.
        const audioEl = track.attach() as HTMLAudioElement;
        audioEl.style.display = "none";
        document.body.appendChild(audioEl);
        // Ensure AudioContext is resumed (required after autoplay policy changes)
        audioEl.play().catch(() => { /* browser will auto-play on next user gesture */ });
      });

      // ── Speaking state: use audio energy events, not track lifecycle ──────────
      // ActiveSpeakersChanged fires in real-time as participants start/stop
      // generating audio above the silence threshold. This is how all production
      // voice SDKs (Alexa, Google Assistant, Siri SDK) track speaking state.
      room.on(RoomEvent.ActiveSpeakersChanged, (speakers: any[]) => {
        const agentSpeaking = speakers.some(
          (p: any) => p.identity?.startsWith("agent")
        );
        if (agentSpeaking && !aiSpeakingRef.current) {
          aiSpeakingRef.current = true;
          setVoiceState("speaking");
          setStatusLabel("Speaking… (speak to interrupt)");
        } else if (!agentSpeaking && aiSpeakingRef.current) {
          aiSpeakingRef.current = false;
          // Don't override "thinking" — only transition from "speaking" to "listening"
          setVoiceState(prev => prev === "speaking" ? "listening" : prev);
          setStatusLabel(prev => prev.startsWith("Speaking") ? "Listening…" : prev);
        }
      });

      // ── Event: transcription (user STT or agent TTS text) ───────────────────
      room.on(RoomEvent.TranscriptionReceived, (segments: any[], participant: any) => {
        const isAgent = participant?.identity?.startsWith("agent");
        segments.forEach(seg => {
          if (!seg.final) {
            // Interim — show as interimText
            if (!isAgent) setInterimText(seg.text);
            return;
          }
          setInterimText("");

          if (!isAgent) {
            // User utterance finalised
            if (isStopCommand(seg.text)) {
              setVoiceState("idle");
              setStatusLabel("Tap to speak");
              return;
            }
            const uIdx = userTurnRef.current;
            userTurnRef.current += 1;
            setTranscripts(prev => [
              ...prev,
              { role: "user", text: seg.text, timestamp: new Date() },
            ]);
            setVoiceState("thinking");
            setStatusLabel("Thinking…");
          } else {
            // Agent TTS transcription — only used as a fallback when word_token
            // data packets didn't arrive (e.g. backend not streaming).
            // If word_token already created/populated the bubble (idx >= 0 or sentinel -2),
            // skip to avoid duplicating text that word_token already streamed.
            const idx = streamingIdxRef.current;
            if (idx === -1) {
              // No word_token bubble yet — create one from TTS transcription
              streamingIdxRef.current = -2; // sentinel
              assistantTurnRef.current += 1;
              setTranscripts(prev => {
                const next = [
                  ...prev,
                  { role: "assistant" as const, text: seg.text, streaming: true, timestamp: new Date() },
                ];
                streamingIdxRef.current = next.length - 1;
                return next;
              });
            }
            // idx >= 0 or -2: word_token already streamed this text — skip
          }
        });
      });

      // ── Event: data messages from agent (tool_status, turn_done, etc.) ───────
      room.on(RoomEvent.DataReceived, (payload: Uint8Array, participant: any) => {
        try {
          const msg = JSON.parse(new TextDecoder().decode(payload));
          _handleDataMsg(msg);
        } catch {}
      });

      // ── Event: connection state ───────────────────────────────────────────────
      room.on(RoomEvent.Disconnected, () => {
        connectedRef.current = false;
        setConnected(false);
        setVoiceState("idle");
        setStatusLabel("Disconnected");
        aiSpeakingRef.current = false;
      });

      room.on(RoomEvent.Reconnecting, () => {
        setStatusLabel("Reconnecting…");
        setVoiceState("connecting");
      });

      room.on(RoomEvent.Reconnected, () => {
        setStatusLabel("Listening…");
        setVoiceState("listening");
      });

      // Connect to room
      await room.connect(ws_url, token);

      // Enable microphone — LiveKit handles STT via the agent subscribing to this track
      await room.localParticipant.setMicrophoneEnabled(true);

      connectedRef.current = true;
      setConnected(true);
      setVoiceState("listening");
      setStatusLabel("Listening…");

      console.log("[LiveKitVoice] Connected to room:", room.name);
    } catch (err: any) {
      console.error("[LiveKitVoice] connect error:", err);
      setVoiceState("error");
      setErrorMsg(err?.message || "Failed to connect to voice service");
      setStatusLabel("Connection failed");
    }
  }, [run_id, user?.id]);

  // ── Handle data messages from the agent ──────────────────────────────────────
  const _handleDataMsg = useCallback((msg: any) => {
    switch (msg.type) {
      case "thinking":
        aiSpeakingRef.current   = false;
        streamingIdxRef.current = -1;
        setVoiceState("thinking");
        setStatusLabel("Thinking…");
        break;

      // ── word_token: each LLM output token forwarded for real-time transcript sync.
      // Fires as the LLM generates tokens (~500ms before TTS audio) so the text
      // appears to stream in sync with the voice.
      case "word_token": {
        const token = msg.text || "";
        if (!token) break;
        const idx = streamingIdxRef.current;
        if (idx === -1) {
          streamingIdxRef.current = -2; // sentinel
          assistantTurnRef.current += 1;
          setTranscripts(prev => {
            const next = [
              ...prev,
              { role: "assistant" as const, text: token, streaming: true, timestamp: new Date() },
            ];
            streamingIdxRef.current = next.length - 1;
            return next;
          });
        } else if (idx >= 0) {
          setTranscripts(prev => {
            const next = [...prev];
            if (next[idx]) next[idx] = { ...next[idx], text: next[idx].text + token };
            return next;
          });
        }
        // idx === -2: sentinel in progress — skip, next token will use the real index
        break;
      }

      case "turn_done":
        setTranscripts(prev => {
          const next = [...prev];
          const idx  = streamingIdxRef.current;
          if (idx >= 0 && next[idx]) {
            // word_token already built the text — just finalize streaming state.
            // Only use msg.text if the bubble is empty (word_tokens never arrived).
            const builtText = next[idx].text;
            next[idx] = { ...next[idx], text: builtText || msg.text || "", streaming: false };
          } else if (idx === -2) {
            // Bubble creation was in progress — find and finalize it
            const lastStreaming = [...next].reverse().findIndex(t => t.role === "assistant" && t.streaming);
            const realIdx = lastStreaming >= 0 ? next.length - 1 - lastStreaming : -1;
            if (realIdx >= 0) {
              next[realIdx] = { ...next[realIdx], streaming: false };
            } else if (msg.text) {
              next.push({ role: "assistant" as const, text: msg.text, streaming: false, timestamp: new Date() });
            }
          } else if (msg.text) {
            // word_tokens never arrived — create completed bubble from full text
            next.push({ role: "assistant" as const, text: msg.text, streaming: false, timestamp: new Date() });
          }
          return next;
        });
        streamingIdxRef.current = -1;
        // Only transition to "listening" if the agent ISN'T currently speaking.
        // turn_done fires when LLM text generation finishes — TTS audio may still
        // be playing. ActiveSpeakersChanged will transition from "speaking" →
        // "listening" when the audio actually ends.
        if (!aiSpeakingRef.current) {
          setVoiceState("listening");
          setStatusLabel("Listening…");
        }
        aiSpeakingRef.current = false; // allow ActiveSpeakersChanged to re-evaluate
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
        setErrorMsg(msg.message || "Unknown agent error");
        break;
    }
  }, []);

  // ── Disconnect ────────────────────────────────────────────────────────────────
  const _disconnect = useCallback(async () => {
    if (roomRef.current) {
      try {
        await roomRef.current.disconnect();
      } catch {}
      roomRef.current = null;
    }
    connectedRef.current = false;
    setConnected(false);
    setVoiceState("idle");
    setStatusLabel("Tap to speak");
    setInterimText("");
    aiSpeakingRef.current = false;
  }, []);

  // ── Auto-connect + history on mount ──────────────────────────────────────────
  useEffect(() => {
    _connect();
    fetchHistory();
  }, [run_id]);

  // ── Mic button handler ────────────────────────────────────────────────────────
  const handleMicPress = useCallback(async () => {
    if (!connected) { await _connect(); return; }

    if (voiceState === "speaking" && roomRef.current) {
      // User tapped mic during agent speech — signal interrupt via data message
      // LiveKit's VAD handles full-duplex interrupt automatically,
      // but this provides an explicit tap-to-interrupt fallback.
      try {
        const payload = new TextEncoder().encode(JSON.stringify({ type: "interrupt" }));
        await roomRef.current.localParticipant.publishData(payload, { reliable: true });
      } catch {}
      aiSpeakingRef.current = false;
      setVoiceState("listening");
      setStatusLabel("Listening…");
    }
    // In LiveKit mode, the mic is always on and VAD handles turn detection.
    // The mic button is a visual indicator + explicit interrupt only.
  }, [connected, voiceState, _connect]);

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
          <p className="text-xs text-[var(--text-secondary)]">Digest #{run_id} · LiveKit WebRTC</p>
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
            <div className={`w-2 h-2 rounded-full transition-colors ${connected ? "bg-green-500" : "bg-gray-400"}`}/>
            <span className="text-xs text-[var(--text-secondary)]">{connected ? "Connected" : "Connecting…"}</span>
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
              Fully hands-free. Radar will start listening automatically.
              Speak any time — even while Radar is talking — to interrupt.
            </p>
          </div>
        )}

        {transcripts.map((t, i) => {

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

      {/* Mic button */}
      <div className="flex flex-col items-center pb-10 pt-4 gap-3">
        <p className="text-xs text-[var(--text-secondary)] h-4">{statusLabel}</p>

        <button
          onClick={handleMicPress}
          disabled={voiceState === "thinking" || voiceState === "connecting"}
          className={`w-20 h-20 rounded-full flex items-center justify-center text-white shadow-lg
            transition-all ${stateColor[voiceState]} hover:opacity-90 active:scale-95
            disabled:opacity-50 disabled:cursor-not-allowed`}
          aria-label={voiceState === "speaking" ? "Interrupt agent" : "Voice status"}
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
        {voiceState === "listening" && (
          <p className="text-[10px] text-[var(--text-secondary)] text-center max-w-[200px] leading-relaxed opacity-70">
            Mic always on · Deepgram VAD detects when you speak
          </p>
        )}

        {connected && (
          <button onClick={_disconnect}
            className="text-xs text-[var(--text-secondary)] hover:text-red-400 transition-colors mt-1">
            End session
          </button>
        )}
      </div>
    </div>
  );
}
