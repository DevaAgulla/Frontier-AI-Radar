"use client";

import React, { useState, useEffect, useRef, useCallback } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { useAuth } from "@/app/context/AuthContext";

// ── Types ─────────────────────────────────────────────────────────────────────

type VoiceState = "idle" | "connecting" | "listening" | "thinking" | "speaking" | "error";

interface Transcript {
  role: "user" | "assistant";
  text: string;
  streaming?: boolean;
}

// ── Audio playback queue ──────────────────────────────────────────────────────
// Incoming MP3 chunks are queued and decoded/played sequentially using
// the Web Audio API so playback is smooth even with variable-size chunks.

class AudioQueue {
  private ctx: AudioContext;
  private queue: ArrayBuffer[] = [];
  private playing = false;
  private nextTime = 0;
  onEnd?: () => void;

  constructor() {
    this.ctx = new (window.AudioContext || (window as any).webkitAudioContext)();
  }

  push(chunk: ArrayBuffer) {
    this.queue.push(chunk);
    if (!this.playing) this._drain();
  }

  private async _drain() {
    this.playing = true;
    while (this.queue.length > 0) {
      const buf = this.queue.shift()!;
      try {
        const decoded = await this.ctx.decodeAudioData(buf.slice(0));
        const src = this.ctx.createBufferSource();
        src.buffer = decoded;
        src.connect(this.ctx.destination);
        const startAt = Math.max(this.ctx.currentTime, this.nextTime);
        src.start(startAt);
        this.nextTime = startAt + decoded.duration;
      } catch {}
    }
    this.playing = false;
    this.onEnd?.();
  }

  stop() {
    this.queue = [];
    this.playing = false;
    this.nextTime = 0;
    try { this.ctx.close(); } catch {}
    this.ctx = new (window.AudioContext || (window as any).webkitAudioContext)();
  }

  resume() {
    if (this.ctx.state === "suspended") this.ctx.resume();
  }
}

// ── Component ─────────────────────────────────────────────────────────────────

export default function VoicePage() {
  const { run_id } = useParams<{ run_id: string }>();
  const { user }   = useAuth();

  const [voiceState,   setVoiceState]   = useState<VoiceState>("idle");
  const [transcripts,  setTranscripts]  = useState<Transcript[]>([]);
  const [statusLabel,  setStatusLabel]  = useState("Tap to start");
  const [wsReady,      setWsReady]      = useState(false);
  const [errorMsg,     setErrorMsg]     = useState("");

  const wsRef          = useRef<WebSocket | null>(null);
  const mediaRecRef    = useRef<MediaRecorder | null>(null);
  const audioQueueRef  = useRef<AudioQueue | null>(null);
  const bottomRef      = useRef<HTMLDivElement>(null);
  const streamingIdxRef = useRef<number>(-1);

  // ── Scroll to bottom on new transcript ──────────────────────────────────────
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [transcripts]);

  // ── Cleanup on unmount ───────────────────────────────────────────────────────
  useEffect(() => () => { _disconnect(); }, []);

  // ── Connect / disconnect ──────────────────────────────────────────────────────

  const _connect = useCallback(async () => {
    setVoiceState("connecting");
    setStatusLabel("Connecting…");
    setErrorMsg("");

    const protocol = window.location.protocol === "https:" ? "wss" : "ws";
    const host     = process.env.NEXT_PUBLIC_API_URL?.replace(/^https?:\/\//, "") || window.location.host;
    const userId   = user?.id ? `&user_id=${user.id}` : "";
    const url      = `${protocol}://${host}/api/v1/voice/${run_id}${userId ? `?${userId.slice(1)}` : ""}`;

    const ws = new WebSocket(url);
    wsRef.current = ws;
    ws.binaryType = "arraybuffer";

    ws.onopen = () => {};

    ws.onmessage = (ev) => {
      if (ev.data instanceof ArrayBuffer) {
        // Audio chunk
        audioQueueRef.current?.push(ev.data.slice(0));
        return;
      }
      try {
        const msg = JSON.parse(ev.data as string);
        _handleServerMessage(msg);
      } catch {}
    };

    ws.onerror = () => {
      setVoiceState("error");
      setErrorMsg("Connection failed. Is the server running?");
      setStatusLabel("Error");
    };

    ws.onclose = () => {
      setWsReady(false);
      if (voiceState !== "idle") {
        setVoiceState("idle");
        setStatusLabel("Tap to start");
      }
    };
  }, [run_id, user]);

  const _disconnect = useCallback(() => {
    _stopMic();
    audioQueueRef.current?.stop();
    wsRef.current?.close();
    wsRef.current = null;
    setWsReady(false);
    setVoiceState("idle");
    setStatusLabel("Tap to start");
  }, []);

  // ── Server message handler ────────────────────────────────────────────────────

  const _handleServerMessage = useCallback((msg: any) => {
    switch (msg.type) {

      case "ready":
        setWsReady(true);
        setVoiceState("idle");
        setStatusLabel("Tap to speak");
        audioQueueRef.current = new AudioQueue();
        break;

      case "transcript":
        if (msg.is_final) {
          setTranscripts(prev => [...prev, { role: "user", text: msg.text }]);
        } else {
          // Show partial transcript
          setStatusLabel(`Heard: "${msg.text}"`);
        }
        break;

      case "thinking":
        setVoiceState("thinking");
        setStatusLabel("Thinking…");
        // Add empty assistant turn that we'll fill with streaming tokens
        setTranscripts(prev => {
          const next = [...prev, { role: "assistant" as const, text: "", streaming: true }];
          streamingIdxRef.current = next.length - 1;
          return next;
        });
        break;

      case "text_chunk":
        setTranscripts(prev => {
          const next = [...prev];
          const idx  = streamingIdxRef.current;
          if (idx >= 0 && next[idx]) {
            next[idx] = { ...next[idx], text: next[idx].text + msg.text };
          }
          return next;
        });
        break;

      case "audio_start":
        setVoiceState("speaking");
        setStatusLabel("Speaking…");
        audioQueueRef.current?.resume();
        break;

      case "audio_end":
        // Nothing needed — queue drains automatically
        break;

      case "turn_done":
        setTranscripts(prev => {
          const next = [...prev];
          const idx  = streamingIdxRef.current;
          if (idx >= 0 && next[idx]) {
            next[idx] = { ...next[idx], text: msg.text, streaming: false };
          }
          return next;
        });
        streamingIdxRef.current = -1;
        setVoiceState("idle");
        setStatusLabel("Tap to speak");
        break;

      case "interrupted":
        audioQueueRef.current?.stop();
        audioQueueRef.current = new AudioQueue();
        setVoiceState("listening");
        setStatusLabel("Listening…");
        break;

      case "error":
        setErrorMsg(msg.message || "Unknown error");
        break;
    }
  }, []);

  // ── Microphone recording ──────────────────────────────────────────────────────

  const _startMic = useCallback(async () => {
    try {
      const stream  = await navigator.mediaDevices.getUserMedia({
        audio: { sampleRate: 16000, channelCount: 1, echoCancellation: true }
      });
      const rec = new MediaRecorder(stream, { mimeType: "audio/webm;codecs=opus" });
      mediaRecRef.current = rec;

      rec.ondataavailable = async (e) => {
        if (e.data.size > 0 && wsRef.current?.readyState === WebSocket.OPEN) {
          // Signal that a binary frame follows
          wsRef.current.send(JSON.stringify({ type: "audio_chunk" }));
          wsRef.current.send(await e.data.arrayBuffer());
        }
      };

      rec.start(200);  // emit chunks every 200 ms
      setVoiceState("listening");
      setStatusLabel("Listening…");
    } catch {
      setErrorMsg("Microphone access denied.");
      setVoiceState("error");
    }
  }, []);

  const _stopMic = useCallback(() => {
    if (mediaRecRef.current && mediaRecRef.current.state !== "inactive") {
      mediaRecRef.current.stop();
      mediaRecRef.current.stream.getTracks().forEach(t => t.stop());
    }
    mediaRecRef.current = null;
  }, []);

  // ── Button press: start speaking ──────────────────────────────────────────────

  const handleMicPress = useCallback(async () => {
    if (!wsReady) {
      await _connect();
      return;
    }
    if (voiceState === "listening") {
      // User stopped speaking — signal end-of-speech
      _stopMic();
      wsRef.current?.send(JSON.stringify({ type: "end_of_speech" }));
      setVoiceState("thinking");
      setStatusLabel("Processing…");
    } else if (voiceState === "idle") {
      await _startMic();
    } else if (voiceState === "speaking") {
      // Interrupt
      _stopMic();
      wsRef.current?.send(JSON.stringify({ type: "interrupt" }));
    }
  }, [wsReady, voiceState, _connect, _startMic, _stopMic]);

  // ── Render ────────────────────────────────────────────────────────────────────

  const stateColor: Record<VoiceState, string> = {
    idle:       "bg-[var(--primary)]",
    connecting: "bg-yellow-400 animate-pulse",
    listening:  "bg-green-500 animate-pulse",
    thinking:   "bg-orange-400 animate-spin",
    speaking:   "bg-blue-500 animate-pulse",
    error:      "bg-red-500",
  };

  const micIcon = voiceState === "listening" ? (
    // Stop icon
    <svg width="28" height="28" viewBox="0 0 24 24" fill="currentColor">
      <rect x="6" y="6" width="12" height="12" rx="2"/>
    </svg>
  ) : (
    // Mic icon
    <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/>
      <path d="M19 10v2a7 7 0 0 1-14 0v-2"/>
      <line x1="12" y1="19" x2="12" y2="23"/>
      <line x1="8"  y1="23" x2="16" y2="23"/>
    </svg>
  );

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
          <p className="text-xs text-[var(--text-secondary)]">Digest #{run_id}</p>
        </div>
        <div className="ml-auto flex items-center gap-2">
          <div className={`w-2 h-2 rounded-full ${wsReady ? "bg-green-500" : "bg-gray-400"}`}/>
          <span className="text-xs text-[var(--text-secondary)]">{wsReady ? "Connected" : "Not connected"}</span>
        </div>
      </div>

      {/* Transcript */}
      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-4">
        {transcripts.length === 0 && (
          <div className="text-center text-[var(--text-secondary)] text-sm mt-8">
            <p className="font-medium">Voice mode</p>
            <p className="mt-1 text-xs">Tap the microphone to ask about the AI digest</p>
          </div>
        )}
        {transcripts.map((t, i) => (
          <div key={i} className={`flex ${t.role === "user" ? "justify-end" : "justify-start"}`}>
            <div className={`max-w-[80%] px-4 py-2.5 rounded-2xl text-sm ${
              t.role === "user"
                ? "bg-[var(--primary)] text-white rounded-br-sm"
                : "bg-[var(--bg-card)] border border-[var(--border)] text-[var(--text-primary)] rounded-bl-sm"
            }`}>
              {t.text || (t.streaming ? <span className="animate-pulse">…</span> : "")}
            </div>
          </div>
        ))}
        <div ref={bottomRef}/>
      </div>

      {/* Error banner */}
      {errorMsg && (
        <div className="mx-4 mb-2 px-3 py-2 bg-red-50 border border-red-200 rounded-lg text-red-700 text-xs">
          {errorMsg}
        </div>
      )}

      {/* Mic button */}
      <div className="flex flex-col items-center pb-10 pt-4 gap-3">
        <p className="text-xs text-[var(--text-secondary)]">{statusLabel}</p>
        <button
          onClick={handleMicPress}
          className={`w-20 h-20 rounded-full flex items-center justify-center text-white shadow-lg transition-all
            ${stateColor[voiceState]} hover:opacity-90 active:scale-95`}
        >
          {voiceState === "thinking"
            ? <span className="text-xl font-bold">…</span>
            : micIcon
          }
        </button>
        {voiceState !== "idle" && voiceState !== "connecting" && wsReady && (
          <button onClick={_disconnect}
            className="text-xs text-[var(--text-secondary)] hover:text-red-500 transition-colors mt-1">
            End session
          </button>
        )}
      </div>
    </div>
  );
}
