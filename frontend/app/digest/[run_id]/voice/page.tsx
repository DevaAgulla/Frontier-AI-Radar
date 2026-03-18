"use client";

import React, { useState, useEffect, useRef, useCallback } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { useAuth } from "@/app/context/AuthContext";

// ── Types ──────────────────────────────────────────────────────────────────────

type VoiceState = "idle" | "connecting" | "listening" | "thinking" | "speaking" | "cooldown" | "error";
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

  const [voiceState,   setVoiceState]  = useState<VoiceState>("connecting");
  const [transcripts,  setTranscripts] = useState<Transcript[]>([]);
  const [statusLabel,  setStatusLabel] = useState("Preparing voice…");
  const [connected,    setConnected]   = useState(false);
  const [errorMsg,     setErrorMsg]    = useState("");
  const [interimText,  setInterimText] = useState("");
  const [idleMessage,  setIdleMessage] = useState("");
  const [cooldownSecs, setCooldownSecs] = useState(3);

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
  // Tracks attached audio elements by "identity:sid" key so we can detach/remove
  // them properly on TrackUnsubscribed and on disconnect.
  const audioElementsRef    = useRef<Map<string, HTMLAudioElement>>(new Map());
  // Visibility-change handler ref so it can be removed on disconnect.
  const visibilityHandlerRef = useRef<(() => void) | null>(null);
  const cooldownTimerRef     = useRef<ReturnType<typeof setInterval> | null>(null);
  const wordRevealTimersRef  = useRef<ReturnType<typeof setTimeout>[]>([]);
  const agentAudioRef        = useRef<HTMLAudioElement | null>(null);
  // Prevents concurrent _connect() calls (React Strict Mode fires useEffect twice).
  // Two simultaneous connections to the same room creates two agent workers that
  // fight each other → job executor marks both unresponsive → endless reconnect loop.
  const connectingRef        = useRef(false);
  // True once the user has provided a gesture (tap) that unlocked the AudioContext.
  // Used by TrackSubscribed to decide whether to start muted or unmuted.
  const audioUnlockedRef     = useRef(false);
  // ── Audio-text sync refs (Bug 3) ──────────────────────────────────────────────
  // word_token packets arrive ~500ms before TTS audio starts. We buffer them here
  // and only flush to the transcript bubble when tts_started fires — so text
  // appears at exactly the moment the voice begins playing.
  const pendingTokensRef    = useRef<string>("");   // buffered LLM tokens pre-TTS
  const ttsReadyRef         = useRef(false);        // true once TTS audio has started
  // Fix 3 — dedup guard: prevents the same assistant message being pushed twice
  // (race between tts_started flush and turn_done fallback). Keyed by first-50-char
  // hash of content; cleared on every new "thinking" event.
  const committedTurnsRef   = useRef<Set<string>>(new Set());

  // ── Init audio store ──────────────────────────────────────────────────────────
  useEffect(() => { audioStoreRef.current = new VoiceAudioStore(); }, []);

  // ── Scroll to bottom ──────────────────────────────────────────────────────────
  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: "smooth" }); },
    [transcripts, interimText]);

  // ── Cleanup on unmount ────────────────────────────────────────────────────────
  useEffect(() => () => {
    // Cancel all timers immediately — prevents phantom state updates after navigation
    wordRevealTimersRef.current.forEach(clearTimeout);
    wordRevealTimersRef.current = [];
    if (cooldownTimerRef.current) {
      clearInterval(cooldownTimerRef.current);
      cooldownTimerRef.current = null;
    }
    _disconnect();
  }, []);

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
    // Guard: if a connection attempt is already in progress, do nothing.
    // React Strict Mode mounts → unmounts → mounts, firing useEffect twice.
    // Without this guard, two _connect() calls race and spawn duplicate agents.
    if (connectingRef.current) return;
    connectingRef.current = true;

    setVoiceState("connecting");
    setStatusLabel("Connecting…");
    setErrorMsg("");

    try {
      // Dynamically import livekit-client to avoid SSR issues
      const { Room, RoomEvent, Track, ConnectionState } = await import("livekit-client");

      // Fix 3: tear down any existing room session before creating a new one.
      // Without this, navigating between digests or re-clicking connect leaves
      // the previous session alive — two sessions fight over the same room and
      // destroy each other's Deepgram/ElevenLabs connections.
      if (roomRef.current && roomRef.current.state !== ConnectionState.Disconnected) {
        await roomRef.current.disconnect();
        roomRef.current = null;
      }

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

      // Create and connect the LiveKit room.
      // adaptiveStream and dynacast are VIDEO-only features — they pause tracks
      // attached to hidden/off-screen elements. With adaptiveStream=true, our
      // hidden <audio> element causes LiveKit to pause the agent's audio track.
      // Disabled here: this is audio-only, no video tracks exist.
      const room = new Room({
        audioCaptureDefaults: {
          noiseSuppression:  true,
          echoCancellation:  true,
          autoGainControl:   true,
        },
      });
      roomRef.current = room;

      // ── Event: remote participant joins (agent connects) ────────────────────
      // Do NOT set voiceState here — the backend sends state_change:idle
      // via agent_state_changed (initializing→listening) ~50ms after joining.
      // Setting state here races with that message and can cause a flicker or
      // override a more specific state if the agent joins mid-reconnect.
      room.on(RoomEvent.ParticipantConnected, (participant: any) => {
        console.log("[LiveKitVoice][DIAG] ParticipantConnected:", participant.identity);
        setStatusLabel("Agent ready…");
      });

      room.on(RoomEvent.TrackSubscribed, (track: any) => {
        if (track.kind === Track.Kind.Audio && agentAudioRef.current) {
          // Attach to the stable <audio> element. LiveKit sets srcObject,
          // autoplay=true, muted=false internally and queues play() via
          // DeviceManager.onPlaybackAllowed — fired when room.startAudio() runs.
          // Do NOT touch .muted here — it breaks LiveKit's internal flow.
          track.attach(agentAudioRef.current);
        }
      });

      room.on(RoomEvent.TrackUnsubscribed, (track: any) => {
        if (track.kind === Track.Kind.Audio && agentAudioRef.current) {
          track.detach(agentAudioRef.current);
        }
      });

      // ── Visibility change: resume AudioContext when tab regains focus ─────────
      // Some browsers (Firefox, Safari) suspend the AudioContext when the tab
      // loses focus and do not auto-resume it. Calling room.startAudio() on
      // visibilitychange ensures audio resumes when the user returns to the tab.
      const visibilityHandler = () => {
        if (document.visibilityState === "visible" && roomRef.current) {
          roomRef.current.startAudio().catch(() => {});
        }
      };
      document.addEventListener("visibilitychange", visibilityHandler);
      visibilityHandlerRef.current = visibilityHandler;

      // ── Event: transcription ────────────────────────────────────────────────
      // sync_alignment=True on ElevenLabs TTS → LiveKit fires TranscriptionReceived
      // for the agent with cumulative word text as each audio chunk plays.
      // We use these to update the streaming bubble in real-time — no estimation,
      // no timers, inherently synced to the actual audio.
      // User (Deepgram STT) segments are handled in the else-branch below.
      room.on(RoomEvent.TranscriptionReceived, (segments: any[], participant: any) => {
        const isAgent = participant?.identity?.startsWith("agent");

        // ── Agent word-reveal via ElevenLabs alignment ──────────────────────
        if (isAgent) {
          segments.forEach((seg: any) => {
            if (!seg.text) return;
            setTranscripts(prev => {
              const next = [...prev];
              const idx  = streamingIdxRef.current;
              // Only update while bubble is still streaming (turn_done may have
              // already finalized it with the authoritative LLM text).
              if (idx >= 0 && next[idx] && next[idx].streaming) {
                next[idx] = { ...next[idx], text: seg.text };
              }
              return next;
            });
          });
          return;
        }

        segments.forEach(seg => {
          if (!seg.final) {
            setInterimText(seg.text);
            return;
          }
          setInterimText("");
          if (isStopCommand(seg.text)) {
            setVoiceState("idle");
            setStatusLabel("Tap to speak");
            return;
          }
          userTurnRef.current += 1;
          setTranscripts(prev => [
            ...prev,
            { role: "user", text: seg.text, timestamp: new Date() },
          ]);
          setVoiceState("thinking");
          setStatusLabel("Thinking…");
        });
      });

      // ── Event: data messages from agent (tool_status, turn_done, etc.) ───────
      room.on(RoomEvent.DataReceived, (payload: Uint8Array, participant: any) => {
        try {
          const msg = JSON.parse(new TextDecoder().decode(payload));
          if (["tts_started", "tts_stopped", "thinking", "turn_done"].includes(msg.type)) {
            console.log("[LiveKitVoice][DIAG] DataReceived:", msg.type, "from:", participant?.identity);
          }
          _handleDataMsg(msg);
        } catch {}
      });

      // ── Event: connection state ───────────────────────────────────────────────
      room.on(RoomEvent.Disconnected, () => {
        const wasConnected   = connectedRef.current;
        connectedRef.current  = false;
        aiSpeakingRef.current = false;
        setConnected(false);
        setVoiceState("idle");
        // "Session ended" for natural / farewell-driven close; "Disconnected" for
        // unexpected drops so the user knows something went wrong.
        setStatusLabel(wasConnected ? "Session ended — tap to start again" : "Disconnected");
      });

      room.on(RoomEvent.Reconnecting, () => {
        setStatusLabel("Reconnecting…");
        setVoiceState("connecting");
      });

      room.on(RoomEvent.Reconnected, () => {
        setStatusLabel("Reconnected — waiting for agent…");
        setVoiceState("connecting");
      });

      // Connect to room
      await room.connect(ws_url, token);
      // NOTE: room.startAudio() is intentionally NOT called here.
      // startAudio() unlocks the browser AudioContext and MUST be called from
      // a direct user-gesture handler (button click). This function is now called
      // from background useEffect, so startAudio is deferred to handleTapToSpeak
      // / handleMicPress which always run inside a click handler.

      // Mic is enabled in handleTapToSpeak (inside user gesture) not here.
      // Enabling it here (background) causes browser permission issues on first visit.

      connectedRef.current = true;
      setConnected(true);
      setVoiceState("connecting");   // backend will send state_change:idle shortly
      setStatusLabel("Agent connecting…");

      console.log("[LiveKitVoice] Connected to room:", room.name);
    } catch (err: any) {
      console.error("[LiveKitVoice] connect error:", err);
      setVoiceState("error");
      setErrorMsg(err?.message || "Failed to connect to voice service");
      setStatusLabel("Connection failed");
    } finally {
      connectingRef.current = false;
    }
  }, [run_id, user?.id]);

  // ── Handle data messages from the agent ──────────────────────────────────────
  const _handleDataMsg = useCallback((msg: any) => {
    // Helper: clear any running cooldown countdown timer
    const _clearCooldown = () => {
      if (cooldownTimerRef.current) {
        clearInterval(cooldownTimerRef.current);
        cooldownTimerRef.current = null;
      }
    };

    switch (msg.type) {

      // ── PRIMARY: backend state machine driver ─────────────────────────────────
      // All voice state transitions flow through state_change messages.
      // word_token / turn_done handle text only; state_change handles UI state.
      case "state_change": {
        const s: VoiceState = msg.state;
        _clearCooldown();

        // Cancel any pending word-reveal timers whenever leaving speaking state
        if (s !== "speaking") {
          wordRevealTimersRef.current.forEach(clearTimeout);
          wordRevealTimersRef.current = [];
        }

        if (s === "thinking") {
          aiSpeakingRef.current    = false;
          streamingIdxRef.current  = -1;
          ttsReadyRef.current      = false;
          pendingTokensRef.current = "";
          committedTurnsRef.current.clear();
          setVoiceState("thinking");
          setStatusLabel("Thinking…");

        } else if (s === "speaking") {
          // Create empty streaming bubble. Word-by-word reveal is driven by
          // TranscriptionReceived (agent) events — ElevenLabs sync_alignment=True
          // sends word timing alongside audio chunks so text is naturally synced
          // to the actual audio playback with no estimation needed.
          ttsReadyRef.current = true;
          const buffered = pendingTokensRef.current;
          pendingTokensRef.current = "";
          if (buffered) {
            const dedupKey = buffered.slice(0, 50);
            if (!committedTurnsRef.current.has(dedupKey)) {
              committedTurnsRef.current.add(dedupKey);
              assistantTurnRef.current += 1;
              streamingIdxRef.current = -2;
              setTranscripts(prev => {
                const next = [...prev, {
                  role: "assistant" as const, text: "",
                  streaming: true, timestamp: new Date(),
                }];
                streamingIdxRef.current = next.length - 1;
                return next;
              });
            }
          }
          aiSpeakingRef.current = true;
          // Audio stream now has data — ensure the element is unmuted and playing.
          // This is the definitive play() call: the agent IS speaking right now,
          // so the MediaStream is active and the browser won't block playback.
          if (agentAudioRef.current) {
            agentAudioRef.current.muted = false;
            agentAudioRef.current.play().catch(() => {});
          }
          setVoiceState("speaking");
          setStatusLabel("Speaking…");

        } else if (s === "cooldown") {
          // Finalize the streaming bubble (TTS audio ended)
          ttsReadyRef.current   = false;
          aiSpeakingRef.current = false;
          setTranscripts(prev => {
            const next = [...prev];
            const idx  = streamingIdxRef.current;
            if (idx >= 0 && next[idx]?.streaming) {
              next[idx] = { ...next[idx], streaming: false };
            } else if (idx === -2) {
              const lastIdx = [...next].reverse().findIndex(t => t.role === "assistant" && t.streaming);
              const real    = lastIdx >= 0 ? next.length - 1 - lastIdx : -1;
              if (real >= 0) next[real] = { ...next[real], streaming: false };
            }
            return next;
          });
          setVoiceState("cooldown");
          setStatusLabel("Listening for follow-up…");
          // 3-second countdown display
          setCooldownSecs(3);
          cooldownTimerRef.current = setInterval(() => {
            setCooldownSecs(prev => {
              if (prev <= 1) {
                clearInterval(cooldownTimerRef.current!);
                cooldownTimerRef.current = null;
                return 0;
              }
              return prev - 1;
            });
          }, 1000);

        } else if (s === "idle") {
          ttsReadyRef.current   = false;
          aiSpeakingRef.current = false;
          if (msg.message) setIdleMessage(msg.message);
          setVoiceState("idle");
          setStatusLabel("Tap to speak");

        } else if (s === "listening") {
          ttsReadyRef.current   = false;
          aiSpeakingRef.current = false;
          // Reset audio playhead so next response starts cleanly
          if (agentAudioRef.current) agentAudioRef.current.currentTime = 0;
          setIdleMessage("");
          setVoiceState("listening");
          setStatusLabel("Listening…");
        }
        break;
      }

      // ── word_token: buffer ALL tokens — never render on token events.
      // Voice leads; text follows. The full buffer is flushed when state:speaking fires.
      case "word_token": {
        const token = msg.text || "";
        if (token) pendingTokensRef.current += token;
        break;
      }

      // ── turn_done: LLM stream finished — finalize the transcript bubble text.
      // Does NOT change voice state (state_change:cooldown handles that).
      case "turn_done":
        ttsReadyRef.current = false;
        setTranscripts(prev => {
          const next = [...prev];
          const idx  = streamingIdxRef.current;
          if (idx >= 0 && next[idx]) {
            // Normal: update with complete LLM text and mark done
            next[idx] = { ...next[idx], streaming: false, text: msg.text || next[idx].text };
          } else if (idx === -2) {
            const lastIdx = [...next].reverse().findIndex(t => t.role === "assistant" && t.streaming);
            const real    = lastIdx >= 0 ? next.length - 1 - lastIdx : -1;
            if (real >= 0) next[real] = { ...next[real], streaming: false, text: msg.text || next[real].text };
          } else if (idx === -1 && msg.text) {
            // Fallback: TTS never fired — create completed bubble directly
            const dedupKey = (msg.text as string).slice(0, 50);
            if (!committedTurnsRef.current.has(dedupKey)) {
              committedTurnsRef.current.add(dedupKey);
              next.push({ role: "assistant" as const, text: msg.text, streaming: false, timestamp: new Date() });
            }
          }
          return next;
        });
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

      case "session_end":
        _clearCooldown();
        setStatusLabel("Session ended — goodbye!");
        setVoiceState("idle");
        setTimeout(() => { roomRef.current?.disconnect().catch(() => {}); }, 1000);
        break;

      case "error":
        setErrorMsg(msg.message || "Unknown agent error");
        break;
    }
  }, []);

  // ── Disconnect ────────────────────────────────────────────────────────────────
  const _disconnect = useCallback(async () => {
    // Cancel all pending timers so no phantom state updates fire after disconnect
    wordRevealTimersRef.current.forEach(clearTimeout);
    wordRevealTimersRef.current = [];
    if (cooldownTimerRef.current) {
      clearInterval(cooldownTimerRef.current);
      cooldownTimerRef.current = null;
    }

    // Remove visibility handler before disconnecting
    if (visibilityHandlerRef.current) {
      document.removeEventListener("visibilitychange", visibilityHandlerRef.current);
      visibilityHandlerRef.current = null;
    }

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

  // ── Pre-warm: connect in background on page mount ─────────────────────────────
  // We start the LiveKit connection as soon as the page loads — BEFORE the user
  // clicks anything. By the time they tap "Tap to Speak", the WebSocket is open,
  // the agent is spawned, and Deepgram + ElevenLabs are initialised.
  // The only operation we defer to the click handler is room.startAudio() (which
  // unlocks the browser AudioContext and legally requires a user gesture).
  useEffect(() => {
    fetchHistory();
    _connect().catch(console.error);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run_id]);

  // ── Mic / connect button ─────────────────────────────────────────────────────
  // Only used as a fallback when the background pre-connect failed or the user
  // explicitly wants to reconnect. Interrupt and tap-to-speak handled below.
  const handleMicPress = useCallback(async () => {
    if (!connected) await _connect();
    audioUnlockedRef.current = true;
    roomRef.current?.startAudio().catch(() => {});
    if (agentAudioRef.current) {
      agentAudioRef.current.muted = false;
      agentAudioRef.current.play().catch(() => {});
    }
  }, [connected, _connect]);

  // ── Tap to Speak — published from idle/cooldown state ────────────────────────
  const handleTapToSpeak = useCallback(async () => {
    // Edge case: background pre-connect failed — run it now inside user gesture
    if (!connected) await _connect();
    audioUnlockedRef.current = true;
    if (roomRef.current) {
      roomRef.current.startAudio().catch(() => {});
      roomRef.current.localParticipant?.setMicrophoneEnabled(true).catch(() => {});
    }
    // Belt-and-suspenders: ensure the audio element is unmuted and playing.
    // startAudio() above unlocks LiveKit's DeviceManager (handles future tracks).
    // This explicit play() handles the case where the track is already attached.
    if (agentAudioRef.current) {
      agentAudioRef.current.muted = false;
      agentAudioRef.current.play().catch(() => {});
    }
    try {
      const payload = new TextEncoder().encode(JSON.stringify({ type: "tap_to_speak" }));
      await roomRef.current!.localParticipant.publishData(payload, { reliable: true });
    } catch {}
    setVoiceState("listening");
    setStatusLabel("Listening…");
  }, [connected, _connect]);

  // ── Tap to Interrupt — hard stop: audio + timers + UI all killed immediately ──
  const handleInterrupt = useCallback(async () => {
    // 1. Stop browser audio immediately — no waiting for backend
    if (agentAudioRef.current) {
      agentAudioRef.current.pause();
      agentAudioRef.current.currentTime = 0;
    }

    // 2. Cancel all pending word-reveal timers — text stops at current word
    wordRevealTimersRef.current.forEach(clearTimeout);
    wordRevealTimersRef.current = [];

    // 3. Discard any buffered tokens
    pendingTokensRef.current = "";

    // 4. Update UI immediately — user sees listening state before backend responds
    aiSpeakingRef.current = false;
    setVoiceState("listening");
    setStatusLabel("Listening…");

    // 5. Tell backend to stop (async cleanup — UI already updated above)
    try {
      const payload = new TextEncoder().encode(JSON.stringify({ type: "user_interrupt" }));
      await roomRef.current?.localParticipant.publishData(payload, { reliable: true });
    } catch {}
  }, []);

  // ── Render ────────────────────────────────────────────────────────────────────

  const stateColor: Record<VoiceState, string> = {
    idle:       "bg-[var(--primary)]",
    connecting: "bg-yellow-400 animate-pulse",
    listening:  "bg-green-500 animate-pulse",
    thinking:   "bg-orange-400",
    speaking:   "bg-blue-500 animate-pulse",
    cooldown:   "bg-green-400",
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

      {/* Stable audio element — always in DOM so TrackSubscribed can attach to it immediately.
          No style override: <audio> without controls renders as 0×0 naturally.
          display:none would trigger LiveKit's adaptiveStream to pause the track. */}
      {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
      <audio ref={agentAudioRef} autoPlay playsInline />

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
            <div className={`w-2 h-2 rounded-full transition-colors ${
              voiceState === "error"      ? "bg-red-500" :
              voiceState === "connecting" ? "bg-yellow-400 animate-pulse" :
              connected                   ? "bg-green-500" : "bg-gray-400"
            }`}/>
            <span className="text-xs text-[var(--text-secondary)]">
              {voiceState === "error" ? "Error" : connected ? "Connected" : "Connecting…"}
            </span>
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
              Agent is connecting in the background. Tap the mic button when
              it appears to start speaking. After each answer Radar listens
              3 s for follow-ups.
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

      {/* Voice controls — pb-safe covers iOS home-bar notch */}
      <div className="flex flex-col items-center pb-[max(2.5rem,env(safe-area-inset-bottom))] pt-4 gap-3">
        <p className="text-xs text-[var(--text-secondary)] h-4">{statusLabel}</p>

        {/* ── Not connected: connect button ── */}
        {!connected && (
          <button
            onClick={handleMicPress}
            disabled={voiceState === "connecting"}
            className={`w-20 h-20 rounded-full flex items-center justify-center text-white shadow-lg
              transition-all ${voiceState === "connecting" ? "bg-yellow-400 animate-pulse" : "bg-[var(--primary)]"}
              hover:opacity-90 active:scale-95 disabled:opacity-50 disabled:cursor-not-allowed`}
            aria-label="Connect to voice agent"
          >
            {voiceState === "connecting"
              ? <span className="flex gap-1">{[0,100,200].map(d => (
                  <span key={d} className="w-2 h-2 bg-white rounded-full animate-bounce" style={{ animationDelay: `${d}ms` }}/>
                ))}</span>
              : micIcon}
          </button>
        )}

        {/* ── CONNECTING (room joined, waiting for agent state) ── */}
        {connected && voiceState === "connecting" && (
          <div className="w-20 h-20 rounded-full flex items-center justify-center bg-yellow-400 animate-pulse shadow-lg text-white">
            <span className="flex gap-1">{[0,100,200].map(d => (
              <span key={d} className="w-2 h-2 bg-white rounded-full animate-bounce" style={{ animationDelay: `${d}ms` }}/>
            ))}</span>
          </div>
        )}

        {/* ── IDLE: Tap to Speak ── */}
        {connected && voiceState === "idle" && (
          <button
            onClick={handleTapToSpeak}
            className="w-20 h-20 rounded-full flex items-center justify-center text-white shadow-lg
              bg-[var(--primary)] hover:opacity-90 active:scale-95 transition-all"
            aria-label="Tap to speak"
          >
            {micIcon}
          </button>
        )}

        {/* ── LISTENING: pulsing green mic ── */}
        {connected && voiceState === "listening" && (
          <div className="w-20 h-20 rounded-full flex items-center justify-center text-white bg-green-500 shadow-lg animate-pulse">
            {micIcon}
          </div>
        )}

        {/* ── THINKING: bouncing dots ── */}
        {connected && voiceState === "thinking" && (
          <div className="w-20 h-20 rounded-full flex items-center justify-center bg-orange-400 shadow-lg">
            <span className="flex gap-1">{[0,100,200].map(d => (
              <span key={d} className="w-2 h-2 bg-white rounded-full animate-bounce" style={{ animationDelay: `${d}ms` }}/>
            ))}</span>
          </div>
        )}

        {/* ── SPEAKING: Tap to Interrupt button ── */}
        {connected && voiceState === "speaking" && (
          <button
            onClick={handleInterrupt}
            className="px-6 py-3 rounded-full border-2 border-red-400 text-red-500 text-sm font-semibold
              hover:bg-red-50 active:scale-95 transition-all shadow-sm"
            aria-label="Interrupt agent"
          >
            Tap to Interrupt
          </button>
        )}

        {/* ── COOLDOWN: dimmer pulsing mic + countdown ── */}
        {connected && voiceState === "cooldown" && (
          <>
            <div className="w-20 h-20 rounded-full flex items-center justify-center text-white bg-green-400 opacity-60 shadow-lg animate-pulse">
              {micIcon}
            </div>
            {cooldownSecs > 0 && (
              <p className="text-[10px] text-[var(--text-secondary)] opacity-60">
                Follow-up? {cooldownSecs}s…
              </p>
            )}
          </>
        )}

        {/* ── ERROR: retry button ── */}
        {voiceState === "error" && (
          <button
            onClick={() => { setErrorMsg(""); _connect(); }}
            className="w-20 h-20 rounded-full flex items-center justify-center text-white shadow-lg
              bg-red-500 hover:opacity-90 active:scale-95 transition-all"
            aria-label="Retry connection"
          >
            {micIcon}
          </button>
        )}

        {/* Farewell / idle message */}
        {connected && voiceState === "idle" && idleMessage && (
          <p className="text-xs text-[var(--text-secondary)] text-center max-w-[200px] leading-relaxed opacity-70 mt-1">
            {idleMessage}
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
