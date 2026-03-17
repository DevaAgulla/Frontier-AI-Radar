"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import Link from "next/link";
import { useAuth } from "@/app/context/AuthContext";

interface DigestCard {
  id: string;
  run_id: string;
  date: string;
  executive_summary: string;
  findings_count: number;
  pdf_url: string | null;
  audio_url?: string;
  created_at: string;
  period?: "daily" | "weekly" | "monthly";
}

function formatDate(dateStr: string): string {
  try {
    const d = dateStr.includes("T") ? toUtcDate(dateStr) : new Date(dateStr + "T00:00:00Z");
    return d.toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric", year: "numeric" });
  } catch { return dateStr; }
}

function shortDate(dateStr: string): string {
  try {
    const d = dateStr.includes("T") ? toUtcDate(dateStr) : new Date(dateStr + "T00:00:00Z");
    return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
  } catch { return dateStr; }
}

function toUtcDate(dateStr: string): Date {
  // Backend returns UTC timestamps without 'Z' (e.g. "2026-03-15T11:30:00").
  // Without the Z, browsers parse as local time (IST = UTC+5:30), making
  // timestamps appear 5.5 h older. Append Z if no TZ info is present.
  const hasTimezone = /[Zz]$|[+-]\d{2}:\d{2}$/.test(dateStr);
  return new Date(hasTimezone ? dateStr : `${dateStr}Z`);
}

function timeAgo(dateStr: string): string {
  try {
    const d = toUtcDate(dateStr);
    const now = new Date();
    const mins = Math.floor((now.getTime() - d.getTime()) / 60000);
    if (mins < 2) return "Just now";
    if (mins < 60) return `${mins}m ago`;
    const hours = Math.floor(mins / 60);
    if (hours < 24) return `${hours}h ago`;
    // Use calendar-day diff so "Yesterday" only means the actual previous calendar day
    const todayMidnight = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    const dMidnight    = new Date(d.getFullYear(),   d.getMonth(),   d.getDate());
    const calDays = Math.round((todayMidnight.getTime() - dMidnight.getTime()) / 86_400_000);
    return calDays === 1 ? "Yesterday" : `${calDays}d ago`;
  } catch { return ""; }
}

// ── PDF Viewer Modal ──────────────────────────────────────────────────────────
function PdfViewerModal({ pdfUrl, date, onClose }: { pdfUrl: string; date: string; onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-black/80 backdrop-blur-sm" onClick={onClose}>
      <div
        className="flex items-center justify-between px-5 py-3 bg-[var(--bg-card)] border-b border-[var(--border)] shrink-0"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-red-500/10 flex items-center justify-center">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#ef4444" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
              <polyline points="14 2 14 8 20 8" />
            </svg>
          </div>
          <div>
            <p className="font-semibold text-sm text-[var(--text-primary)]">Frontier AI Intelligence Brief</p>
            <p className="text-xs text-[var(--text-muted)]">{formatDate(date)}</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <a href={pdfUrl} target="_blank" rel="noopener noreferrer"
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border border-[var(--border)] text-[var(--text-secondary)] hover:text-[var(--primary)] hover:border-[var(--primary)]/40 transition-colors"
            onClick={(e) => e.stopPropagation()}>
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
              <polyline points="15 3 21 3 21 9" /><line x1="10" y1="14" x2="21" y2="3" />
            </svg>
            Open in new tab
          </a>
          <button onClick={onClose} className="w-8 h-8 rounded-full flex items-center justify-center text-[var(--text-muted)] hover:bg-[var(--border)] transition-colors">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>
      </div>
      <div className="flex-1 overflow-hidden" onClick={(e) => e.stopPropagation()}>
        <iframe src={`${pdfUrl}#toolbar=1&navpanes=1&scrollbar=1`} className="w-full h-full" title="Frontier AI Intelligence Brief" />
      </div>
    </div>
  );
}

// ── Talking Avatar SVG ────────────────────────────────────────────────────────
function TalkingAvatar({ amplitude, playing }: { amplitude: number; playing: boolean }) {
  const [blink, setBlink] = useState(false);

  // Random blink every 2-5 seconds
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout>;
    const scheduleNext = () => {
      timer = setTimeout(() => {
        setBlink(true);
        setTimeout(() => { setBlink(false); scheduleNext(); }, 120);
      }, 2000 + Math.random() * 3000);
    };
    scheduleNext();
    return () => clearTimeout(timer);
  }, []);

  // Mouth shape: smooth quadratic bezier transition
  const mouthOpen = amplitude * 22; // 0 → 22px max opening
  const eyeRy = blink ? 1 : 7;

  // Mouth: thin smile when closed, open ellipse when speaking
  const mouthPath = mouthOpen > 3
    ? `M 58,90 Q 80,${86 - mouthOpen * 0.3} 102,90 Q 110,${94 + mouthOpen} 80,${96 + mouthOpen} Q 50,${94 + mouthOpen} 58,90 Z`
    : `M 60,93 Q 80,${97 + mouthOpen * 0.4} 100,93`;

  // Glow pulse when speaking
  const glowOpacity = playing ? 0.15 + amplitude * 0.35 : 0;

  return (
    <svg viewBox="0 0 160 160" width="90" height="90" style={{ filter: playing ? `drop-shadow(0 0 ${6 + amplitude * 10}px rgba(139,92,246,${0.4 + amplitude * 0.4}))` : "none", transition: "filter 0.05s", flexShrink: 0 }}>
      <defs>
        <radialGradient id="faceGrad" cx="45%" cy="38%" r="60%">
          <stop offset="0%" stopColor="#c4b5fd" />
          <stop offset="100%" stopColor="#7c3aed" />
        </radialGradient>
        <radialGradient id="glowGrad" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor="#a78bfa" stopOpacity={glowOpacity * 2} />
          <stop offset="100%" stopColor="#7c3aed" stopOpacity={0} />
        </radialGradient>
        <clipPath id="faceClip">
          <circle cx="80" cy="80" r="66" />
        </clipPath>
      </defs>

      {/* Outer glow ring — pulses with audio */}
      <circle cx="80" cy="80" r="74" fill="url(#glowGrad)" style={{ transition: "opacity 0.05s" }} />

      {/* Face */}
      <circle cx="80" cy="80" r="66" fill="url(#faceGrad)" />

      {/* Subtle highlight */}
      <ellipse cx="62" cy="54" rx="18" ry="11" fill="white" fillOpacity="0.12" />

      {/* Left eye */}
      <ellipse cx="57" cy="68" rx="7" ry={eyeRy} fill="white" style={{ transition: "ry 0.06s" }} />
      <ellipse cx="57" cy="68" rx="4.5" ry={Math.min(eyeRy, 5)} fill="#1e1b4b" style={{ transition: "ry 0.06s" }} />
      <circle cx="59" cy="66.5" r="1.2" fill="white" fillOpacity="0.8" />

      {/* Right eye */}
      <ellipse cx="103" cy="68" rx="7" ry={eyeRy} fill="white" style={{ transition: "ry 0.06s" }} />
      <ellipse cx="103" cy="68" rx="4.5" ry={Math.min(eyeRy, 5)} fill="#1e1b4b" style={{ transition: "ry 0.06s" }} />
      <circle cx="105" cy="66.5" r="1.2" fill="white" fillOpacity="0.8" />

      {/* Nose */}
      <ellipse cx="76" cy="80" rx="2.5" ry="1.5" fill="white" fillOpacity="0.25" />
      <ellipse cx="84" cy="80" rx="2.5" ry="1.5" fill="white" fillOpacity="0.25" />

      {/* Mouth */}
      <path
        d={mouthPath}
        fill={mouthOpen > 3 ? "rgba(15,10,40,0.75)" : "none"}
        stroke="white"
        strokeWidth={mouthOpen > 3 ? "0" : "2"}
        strokeLinecap="round"
        style={{ transition: "d 0.04s ease-out" }}
      />
      {/* Teeth — visible when mouth open */}
      {mouthOpen > 8 && (
        <rect
          x="64" y="90" width="32" height={Math.min(mouthOpen * 0.45, 8)} rx="2"
          fill="white" fillOpacity="0.9"
          clipPath="url(#faceClip)"
          style={{ transition: "all 0.04s" }}
        />
      )}
    </svg>
  );
}

// ── Preset type (from DB) ─────────────────────────────────────────────────────
interface VoicePresetInfo {
  id: string;
  label: string;
  gender: string;
  style: string;
  is_ready: boolean;
  audio_url: string | null;
}

// ── Audio Book Modal ──────────────────────────────────────────────────────────
function AudioModal({ runId, date, onClose }: { runId: string; date: string; onClose: () => void }) {
  const [playing, setPlaying] = useState(false);
  const [amplitude, setAmplitude] = useState(0);
  const [presets, setPresets] = useState<VoicePresetInfo[]>([]);
  const [presetsLoading, setPresetsLoading] = useState(true);
  const [scriptReady, setScriptReady] = useState(false);
  const [activePreset, setActivePreset] = useState<VoicePresetInfo | null>(null);
  const [generating, setGenerating] = useState(false);
  const [genError, setGenError] = useState("");
  const audioRef = useRef<HTMLAudioElement>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const animRef = useRef<number>(0);
  const dataArrayRef = useRef<Uint8Array | null>(null);

  const setupAnalyser = useCallback((forElement: HTMLAudioElement) => {
    // Close any stale context first
    if (audioCtxRef.current) {
      try { audioCtxRef.current.close(); } catch { /* ignore */ }
      audioCtxRef.current = null;
      analyserRef.current = null;
      dataArrayRef.current = null;
    }
    try {
      // Use captureStream() instead of createMediaElementSource().
      // createMediaElementSource() permanently hijacks the element's speaker output
      // and requires a running AudioContext to produce any sound — causing silent playback
      // if the context is suspended even briefly.
      // captureStream() gives us a MediaStream for the analyser WITHOUT routing audio
      // through the Web Audio graph, so the element always plays through the speakers.
      const stream: MediaStream | null =
        (forElement as any).captureStream?.() ??
        (forElement as any).mozCaptureStream?.() ??
        null;
      if (!stream) return; // browser doesn't support captureStream — animation just won't run

      const ctx = new AudioContext();
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 512;
      analyser.smoothingTimeConstant = 0.75;
      const source = ctx.createMediaStreamSource(stream);
      source.connect(analyser);
      // Do NOT connect analyser to ctx.destination — audio goes through speaker independently
      audioCtxRef.current = ctx;
      analyserRef.current = analyser;
      dataArrayRef.current = new Uint8Array(analyser.frequencyBinCount);
      ctx.resume().catch(() => {}); // resume for animation clock — not needed for audio
    } catch { /* ignore — captureStream not available or permission denied */ }
  }, []);

  const startAnimation = useCallback(() => {
    const tick = () => {
      if (!analyserRef.current || !dataArrayRef.current) { setAmplitude(0); return; }
      analyserRef.current.getByteFrequencyData(dataArrayRef.current as Uint8Array<ArrayBuffer>);
      // Speech sits in ~100-3000 Hz. For 512 FFT at 44100 Hz, those are roughly bins 1-35
      const speechBins = Array.from(dataArrayRef.current.slice(1, 35));
      const avg = speechBins.reduce((a, b) => a + b, 0) / speechBins.length;
      setAmplitude(Math.min(avg / 110, 1));
      animRef.current = requestAnimationFrame(tick);
    };
    animRef.current = requestAnimationFrame(tick);
  }, []);

  const stopAnimation = useCallback(() => {
    cancelAnimationFrame(animRef.current);
    setAmplitude(0);
  }, []);

  useEffect(() => () => {
    stopAnimation();
    audioCtxRef.current?.close();
  }, [stopAnimation]);

  const handlePlay = () => {
    startAnimation();
    setPlaying(true);
  };

  const handlePause = () => { stopAnimation(); setPlaying(false); };
  const handleEnded = () => { stopAnimation(); setPlaying(false); };

  const toggle = () => {
    if (!audioRef.current || !activePreset?.audio_url) return;
    if (playing) {
      audioRef.current.pause();
    } else {
      // Set up analyser via captureStream (for avatar animation only — does NOT affect audio output)
      setupAnalyser(audioRef.current);
      // Audio plays directly through the browser's speaker pipeline — no AudioContext in the path
      audioRef.current.play().catch((err) => {
        console.warn("[AudioModal] play() failed:", err);
      });
    }
  };

  // Load presets from backend on mount
  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setPresetsLoading(true);
      try {
        const res = await fetch(`/api/audio/presets?run_id=${runId}`);
        if (!res.ok) throw new Error("Failed to load presets");
        const data = await res.json();
        if (cancelled) return;
        const list: VoicePresetInfo[] = data.presets ?? [];
        setPresets(list);
        setScriptReady(data.script_ready ?? false);
        // Restore last-used preset from localStorage, or pick first ready one
        const savedId = globalThis.localStorage?.getItem("frontier_voice_preset") ?? "";
        const saved = list.find(p => p.id === savedId && p.is_ready);
        const firstReady = list.find(p => p.is_ready);
        setActivePreset(saved ?? firstReady ?? null);
      } catch {
        // Leave presets empty — UI will show error state
      } finally {
        if (!cancelled) setPresetsLoading(false);
      }
    };
    load();
    return () => { cancelled = true; };
  }, [runId]);

  // Switch preset — only loads player, never triggers generation
  const selectPreset = (preset: VoicePresetInfo) => {
    if (generating) return;
    setGenError("");
    if (audioRef.current) audioRef.current.pause();
    stopAnimation();
    setPlaying(false);
    setActivePreset(preset);
    try { globalThis.localStorage?.setItem("frontier_voice_preset", preset.id); } catch {}
  };

  // Explicit generate — only called when user clicks "Generate" button
  const generatePreset = async () => {
    if (!activePreset || generating) return;
    setGenError("");
    if (audioRef.current) audioRef.current.pause();
    stopAnimation();
    setPlaying(false);
    setGenerating(true);
    try {
      const res = await fetch(
        `/api/audio/presets?run_id=${runId}&preset_id=${activePreset.id}`,
        { method: "POST" }
      );
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error ?? "Generation failed");

      // Refresh preset list so is_ready flips to true
      const refreshRes = await fetch(`/api/audio/presets?run_id=${runId}`);
      if (refreshRes.ok) {
        const refreshData = await refreshRes.json();
        const updated: VoicePresetInfo[] = refreshData.presets ?? [];
        setPresets(updated);
        const updatedPreset = updated.find(p => p.id === activePreset.id);
        if (updatedPreset) {
          setActivePreset(updatedPreset);
          try { globalThis.localStorage?.setItem("frontier_voice_preset", updatedPreset.id); } catch {}
        }
      }
    } catch (e: any) {
      setGenError(e.message ?? "Failed to generate audio");
    } finally {
      setGenerating(false);
    }
  };

  const heights = [14, 28, 20, 38, 24, 40, 18, 32, 26, 42, 16, 36, 22, 30, 20, 44, 12, 38, 28, 34, 18, 40, 24, 32, 20, 36, 14, 28, 30, 22, 40, 16];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/75 backdrop-blur-sm" onClick={onClose}>
      <div className="w-full max-w-md bg-[var(--bg-card)] rounded-3xl shadow-2xl border border-[var(--border)] overflow-hidden max-h-[90vh] flex flex-col" onClick={(e) => e.stopPropagation()}>

        {/* Gradient header — avatar centered, moderate size */}
        <div className="relative bg-gradient-to-br from-indigo-900 via-purple-800 to-violet-900 px-6 pt-5 pb-6 shrink-0">
          <button onClick={onClose} className="absolute top-4 right-4 w-8 h-8 rounded-full bg-white/10 flex items-center justify-center text-white/70 hover:bg-white/20 transition-colors z-10">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
              <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>

          <div className="flex flex-col items-center">
            <TalkingAvatar amplitude={amplitude} playing={playing} />
            <p className="text-white font-bold text-lg mt-2">AI News Presenter</p>
            <p className="text-white/60 text-sm">{shortDate(date)}</p>
            <div className="flex items-center gap-1.5 mt-2 px-3 py-1 rounded-full bg-white/10">
              <div className={`w-1.5 h-1.5 rounded-full shrink-0 ${generating ? "bg-yellow-400 animate-pulse" : playing ? "bg-green-400 animate-pulse" : "bg-white/40"}`} />
              <span className="text-white/70 text-xs font-medium">
                {generating ? "Generating audio…" : playing ? "Speaking…"
                  : activePreset?.is_ready ? `ElevenLabs · ${activePreset.label}`
                  : activePreset ? `${activePreset.label} · Not generated`
                  : "Select a voice preset"}
              </span>
            </div>
          </div>
        </div>

        {/* Controls — scrollable */}
        <div className="px-5 pb-5 pt-4 bg-[var(--bg-card)] overflow-y-auto flex-1">
          {/* Voice preset dropdown */}
          <div className="mb-4">
            <p className="text-[10px] font-medium text-[var(--text-muted)] uppercase tracking-wider mb-2">
              Voice Preset
              {!scriptReady && !presetsLoading && (
                <span className="ml-2 normal-case text-yellow-500">· Script not ready yet</span>
              )}
            </p>
            {presetsLoading ? (
              <div className="flex items-center gap-2 py-2">
                <svg className="animate-spin" width="13" height="13" fill="none" stroke="var(--primary)" strokeWidth="2" viewBox="0 0 24 24">
                  <circle cx="12" cy="12" r="10" strokeOpacity="0.25"/><path d="M12 2a10 10 0 0 1 10 10" strokeLinecap="round"/>
                </svg>
                <span className="text-xs text-[var(--text-muted)]">Loading…</span>
              </div>
            ) : (
              <div className="flex items-center gap-2">
                {/* Dropdown */}
                <select
                  value={activePreset?.id ?? ""}
                  onChange={(e) => {
                    const p = presets.find(x => x.id === e.target.value);
                    if (p) selectPreset(p);
                  }}
                  disabled={generating}
                  className="flex-1 px-3 py-2 rounded-lg text-xs border border-[var(--border)] bg-[var(--bg-card)] text-[var(--text-primary)] focus:outline-none focus:border-[var(--primary)] disabled:opacity-50 cursor-pointer"
                >
                  {presets.map((v) => (
                    <option key={v.id} value={v.id}>
                      {v.label}{v.is_ready ? " ✓" : ""}
                    </option>
                  ))}
                </select>

                {/* Generate button — only shown when selected preset is not ready */}
                {activePreset && !activePreset.is_ready && (
                  <button
                    onClick={generatePreset}
                    disabled={generating || !scriptReady}
                    className="shrink-0 px-3 py-2 rounded-lg text-xs font-semibold bg-[var(--primary)] text-white hover:bg-[var(--primary-hover)] transition-all disabled:opacity-50 disabled:cursor-not-allowed"
                    title={!scriptReady ? "Audio script not ready yet" : "Generate audio for this voice"}
                  >
                    {generating ? "Generating…" : "Generate"}
                  </button>
                )}

                {/* Ready badge — shown when selected preset is ready */}
                {activePreset?.is_ready && (
                  <span className="shrink-0 text-[10px] font-semibold px-2 py-1 rounded-full bg-green-500/10 text-green-500 border border-green-500/20">
                    Ready
                  </span>
                )}
              </div>
            )}
            {genError && <p className="text-[10px] text-red-400 mt-1.5">{genError}</p>}
          </div>

          {/* Waveform / spinner */}
          {generating ? (
            <div className="flex items-center justify-center h-8 mb-3">
              <svg className="animate-spin" width="18" height="18" fill="none" stroke="var(--primary)" strokeWidth="2" viewBox="0 0 24 24">
                <circle cx="12" cy="12" r="10" strokeOpacity="0.25"/><path d="M12 2a10 10 0 0 1 10 10" strokeLinecap="round"/>
              </svg>
              <span className="ml-2 text-xs text-[var(--text-muted)]">Generating voice…</span>
            </div>
          ) : (
            <div className="flex items-center justify-center gap-0.5 h-8 mb-3">
              {heights.map((h, i) => (
                <div key={i} className="w-1 rounded-full"
                  style={{
                    height: playing ? `${4 + amplitude * h * 0.9}px` : `${h * 0.28}px`,
                    background: playing ? "var(--primary)" : "var(--border)",
                    opacity: playing ? 0.7 + amplitude * 0.3 : 0.4,
                    transition: "height 0.05s ease-out, background 0.2s",
                  }} />
              ))}
            </div>
          )}

          {/* Play/Pause */}
          <div className="flex justify-center mb-3">
            <button onClick={toggle} disabled={generating || !activePreset?.audio_url}
              className="w-12 h-12 rounded-full bg-[var(--primary)] hover:bg-[var(--primary-hover)] flex items-center justify-center text-white shadow-lg shadow-[var(--primary)]/30 transition-all active:scale-95 disabled:opacity-50">
              {playing ? (
                <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
                  <rect x="6" y="4" width="4" height="16" rx="1"/><rect x="14" y="4" width="4" height="16" rx="1"/>
                </svg>
              ) : (
                <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor" style={{ marginLeft: "2px" }}>
                  <polygon points="5 3 19 12 5 21 5 3"/>
                </svg>
              )}
            </button>
          </div>

          {/* Native audio scrubber */}
          {activePreset?.audio_url ? (
            <audio key={`${runId}-${activePreset.id}`} ref={audioRef}
              src={`${activePreset.audio_url}${activePreset.audio_url.includes("?") ? "&" : "?"}bust=${activePreset.id}`}
              onPlay={handlePlay} onPause={handlePause} onEnded={handleEnded}
              className="w-full rounded-lg" controls />
          ) : (
            !generating && (
              <p className="text-center text-xs text-[var(--text-muted)] py-2">
                {activePreset && !activePreset.is_ready
                  ? "Click Generate to create audio for this voice"
                  : "Select a voice preset above"}
              </p>
            )
          )}

          <p className="text-center text-[10px] text-[var(--text-muted)] mt-2">
            Want deeper insights?{" "}
            <Link href={`/digest/${runId}/chat`} className="text-[var(--primary)] hover:underline font-medium">
              Interact with AI →
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
}

// ── Agent options ─────────────────────────────────────────────────────────────
const AGENT_OPTIONS = [
  { id: "research",   label: "Research Intel",     desc: "AI papers & news" },
  { id: "competitor", label: "Competitor Intel",    desc: "Company & product moves" },
  { id: "model",      label: "Foundation Models",   desc: "New model releases" },
  { id: "benchmark",  label: "Benchmarks",          desc: "HuggingFace & perf data" },
] as const;

// ── New Brief Modal ───────────────────────────────────────────────────────────
function NewBriefModal({ user, onClose, onTriggered }: {
  user: { id: number; name: string } | null;
  onClose: () => void;
  onTriggered: (runId: string | null) => void;
}) {
  const [selected, setSelected] = useState<string[]>(["research", "competitor", "model", "benchmark"]);
  const [period, setPeriod] = useState<"daily" | "weekly" | "monthly">("daily");
  const [state, setState] = useState<"idle" | "triggering" | "triggered" | "error">("idle");
  const [error, setError] = useState("");

  const PERIOD_DAYS = { daily: 1, weekly: 7, monthly: 30 };

  const allSelected = selected.length === AGENT_OPTIONS.length;
  const toggle = (id: string) =>
    setSelected((prev) => prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]);

  const handleBuild = async () => {
    if (selected.length === 0) { setError("Select at least one agent."); return; }
    setState("triggering"); setError("");
    try {
      const token = globalThis.localStorage?.getItem("frontier_ai_radar_token");
      const res = await fetch("/api/runs", {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
        body: JSON.stringify({ agent_ids: selected, user_id: user?.id, async_run: true, since_days: PERIOD_DAYS[period], period, url_mode: "default", urls: [] }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Failed to start run");
      const run = data.data ?? data;
      const rid = run.id ? String(run.id) : null;
      setState("triggered");
      // Close modal after brief confirmation; hand off run tracking to parent
      setTimeout(() => {
        onTriggered(rid && !rid.startsWith("pending-") ? rid : null);
        onClose();
      }, 1500);
    } catch (e: any) { setState("error"); setError(e.message || "Something went wrong"); }
  };

  const isTriggering = state === "triggering";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm" onClick={onClose}>
      <div className="w-full max-w-sm bg-[var(--bg-card)] rounded-2xl shadow-2xl border border-[var(--border)] overflow-hidden" onClick={(e) => e.stopPropagation()}>

        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-[var(--border)]">
          <div className="flex items-center gap-2">
            <div className="w-7 h-7 rounded-lg bg-[var(--primary-light)] flex items-center justify-center">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--primary)" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <polyline points="23 4 23 10 17 10" /><path d="M20.49 15a9 9 0 1 1-.36-3.86" />
              </svg>
            </div>
            <h2 className="font-bold text-sm text-[var(--text-primary)]">New Intelligence Brief</h2>
          </div>
          <button onClick={onClose} className="w-7 h-7 rounded-full flex items-center justify-center text-[var(--text-muted)] hover:bg-[var(--border)] transition-colors">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
              <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>

        {/* Body */}
        <div className="px-5 py-4">
          {state === "triggered" ? (
            <div className="flex flex-col items-center gap-3 py-6">
              <div className="w-12 h-12 rounded-full bg-green-500/10 flex items-center justify-center">
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#22c55e" strokeWidth="2.5"><polyline points="20 6 9 17 4 12" /></svg>
              </div>
              <p className="font-semibold text-[var(--text-primary)]">Run triggered!</p>
              <p className="text-xs text-[var(--text-muted)] text-center max-w-[220px]">Agents are working in the background. You'll see a progress indicator while it runs.</p>
            </div>
          ) : isTriggering ? (
            <div className="flex flex-col items-center gap-3 py-6">
              <div className="w-12 h-12 rounded-full bg-[var(--primary-light)] flex items-center justify-center">
                <svg className="animate-spin" width="24" height="24" fill="none" stroke="var(--primary)" strokeWidth="2" viewBox="0 0 24 24">
                  <circle cx="12" cy="12" r="10" strokeOpacity="0.25" /><path d="M12 2a10 10 0 0 1 10 10" strokeLinecap="round" />
                </svg>
              </div>
              <p className="font-semibold text-[var(--text-primary)]">Starting pipeline…</p>
            </div>
          ) : (
            <>
              {/* Period selector */}
              <div className="mb-4">
                <p className="text-xs font-medium text-[var(--text-secondary)] mb-2">Brief period</p>
                <div className="flex gap-1.5">
                  {(["daily", "weekly", "monthly"] as const).map(p => (
                    <button
                      key={p}
                      onClick={() => setPeriod(p)}
                      className={`flex-1 py-1.5 rounded-lg text-xs font-semibold border transition-all capitalize ${
                        period === p
                          ? "bg-[var(--primary)] border-[var(--primary)] text-white"
                          : "border-[var(--border)] text-[var(--text-secondary)] hover:border-[var(--primary)]/50"
                      }`}
                    >
                      {p}
                    </button>
                  ))}
                </div>
                <p className="text-[10px] text-[var(--text-muted)] mt-1">
                  {period === "daily" ? "Last 24 hours" : period === "weekly" ? "Last 7 days" : "Last 30 days"}
                </p>
              </div>

              {/* Select All */}
              <div className="flex items-center justify-between mb-3">
                <p className="text-xs font-medium text-[var(--text-secondary)]">Select agents to run</p>
                <button
                  onClick={() => setSelected(allSelected ? [] : AGENT_OPTIONS.map((a) => a.id))}
                  className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-medium transition-colors border ${allSelected ? "border-[var(--primary)] text-[var(--primary)] bg-[var(--primary-light)]" : "border-[var(--border)] text-[var(--text-muted)] hover:border-[var(--primary)]/50"}`}
                >
                  <div className={`w-3 h-3 rounded flex items-center justify-center border ${allSelected ? "bg-[var(--primary)] border-[var(--primary)]" : "border-[var(--border)]"}`}>
                    {allSelected && <svg width="8" height="8" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="3"><polyline points="20 6 9 17 4 12" /></svg>}
                  </div>
                  Select all
                </button>
              </div>

              {/* Agent cards */}
              <div className="grid grid-cols-2 gap-2">
                {AGENT_OPTIONS.map((agent) => {
                  const isOn = selected.includes(agent.id);
                  return (
                    <button
                      key={agent.id}
                      onClick={() => toggle(agent.id)}
                      className={`flex flex-col gap-1 p-3 rounded-xl border text-left transition-all ${isOn ? "border-[var(--primary)] bg-[var(--primary-light)]" : "border-[var(--border)] hover:border-[var(--primary)]/40"}`}
                    >
                      <div className="flex items-center justify-between">
                        <span className={`text-xs font-bold truncate ${isOn ? "text-[var(--primary)]" : "text-[var(--text-primary)]"}`}>{agent.label}</span>
                        <div className={`w-4 h-4 rounded flex items-center justify-center shrink-0 border ${isOn ? "bg-[var(--primary)] border-[var(--primary)]" : "border-[var(--border)]"}`}>
                          {isOn && <svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="3"><polyline points="20 6 9 17 4 12" /></svg>}
                        </div>
                      </div>
                      <span className="text-[10px] text-[var(--text-muted)] leading-tight">{agent.desc}</span>
                    </button>
                  );
                })}
              </div>

              {error && <p className="text-xs text-red-500 mt-2">{error}</p>}
            </>
          )}
        </div>

        {/* Footer */}
        {(state === "idle" || state === "error") && (
          <div className="px-5 pb-5 flex gap-2">
            <button onClick={onClose} className="flex-1 px-4 py-2.5 rounded-xl border border-[var(--border)] text-sm text-[var(--text-secondary)] hover:bg-[var(--border)] transition-colors">
              Cancel
            </button>
            <button
              onClick={handleBuild}
              disabled={selected.length === 0}
              className="flex-1 px-4 py-2.5 rounded-xl bg-[var(--primary)] hover:bg-[var(--primary-hover)] text-white text-sm font-semibold transition-all shadow-md disabled:opacity-40 disabled:cursor-not-allowed flex items-center justify-center gap-2"
            >
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <polygon points="5 3 19 12 5 21 5 3" />
              </svg>
              Build Brief ({selected.length})
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Run Status Modal ──────────────────────────────────────────────────────────
function RunStatusModal({ runId, onClose }: { runId: string; onClose: () => void }) {
  const [runData, setRunData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchRun = async () => {
    try {
      const token = globalThis.localStorage?.getItem("frontier_ai_radar_token");
      const res = await fetch(`/api/runs/${runId}`, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
      if (!res.ok) return;
      const data = await res.json();
      setRunData(data.data ?? data);
    } catch { } finally { setLoading(false); }
  };

  useEffect(() => {
    fetchRun();
    pollRef.current = setInterval(fetchRun, 6000);
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [runId]);

  // Stop polling once completed
  useEffect(() => {
    if (!runData) return;
    const s = (runData.status ?? "").toLowerCase();
    if (s === "completed" || s === "success" || s === "failed" || s === "failure") {
      if (pollRef.current) clearInterval(pollRef.current);
    }
  }, [runData]);

  const statusColor = (s: string) => {
    switch (s) {
      case "completed": return "text-green-500";
      case "running": return "text-blue-400";
      case "failed": return "text-red-500";
      case "skipped": return "text-[var(--text-muted)]";
      default: return "text-[var(--text-muted)]";
    }
  };
  const statusIcon = (s: string) => {
    if (s === "completed") return <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#22c55e" strokeWidth="2.5"><polyline points="20 6 9 17 4 12" /></svg>;
    if (s === "running") return <svg className="animate-spin" width="12" height="12" fill="none" stroke="#60a5fa" strokeWidth="2" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10" strokeOpacity="0.3"/><path d="M12 2a10 10 0 0 1 10 10" strokeLinecap="round"/></svg>;
    if (s === "failed") return <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#ef4444" strokeWidth="2.5"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>;
    return <span className="w-3 h-0.5 bg-[var(--border)] rounded-full inline-block" />;
  };

  const overallStatus = (runData?.status ?? "").toLowerCase();
  const statusBadge = overallStatus === "completed" || overallStatus === "success"
    ? "bg-green-500/10 text-green-500 border-green-500/20"
    : overallStatus === "running"
    ? "bg-blue-500/10 text-blue-400 border-blue-400/20"
    : overallStatus === "failed" || overallStatus === "failure"
    ? "bg-red-500/10 text-red-500 border-red-500/20"
    : "bg-[var(--border)] text-[var(--text-muted)]";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm" onClick={onClose}>
      <div className="w-full max-w-sm bg-[var(--bg-card)] rounded-2xl shadow-2xl border border-[var(--border)] overflow-hidden" onClick={(e) => e.stopPropagation()}>

        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-[var(--border)]">
          <div>
            <h2 className="font-bold text-sm text-[var(--text-primary)]">Run #{runId} — Pipeline Status</h2>
            {runData && (
              <p className="text-xs text-[var(--text-muted)] mt-0.5">
                {runData.started_at ? new Date(runData.started_at).toLocaleString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : ""}
                {runData.user_name ? ` · ${runData.user_name}` : ""}
              </p>
            )}
          </div>
          <div className="flex items-center gap-2">
            {runData && (
              <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full border capitalize ${statusBadge}`}>
                {overallStatus}
              </span>
            )}
            <button onClick={onClose} className="w-7 h-7 rounded-full flex items-center justify-center text-[var(--text-muted)] hover:bg-[var(--border)] transition-colors">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
              </svg>
            </button>
          </div>
        </div>

        {/* Body */}
        <div className="px-5 py-4">
          {loading ? (
            <div className="flex items-center justify-center py-8">
              <svg className="animate-spin" width="20" height="20" fill="none" stroke="var(--primary)" strokeWidth="2" viewBox="0 0 24 24">
                <circle cx="12" cy="12" r="10" strokeOpacity="0.25" /><path d="M12 2a10 10 0 0 1 10 10" strokeLinecap="round" />
              </svg>
            </div>
          ) : !runData ? (
            <p className="text-sm text-[var(--text-muted)] text-center py-6">Could not load run details.</p>
          ) : (
            <>
              {/* Agent statuses */}
              <p className="text-[10px] font-bold text-[var(--text-muted)] uppercase tracking-widest mb-3">Agent Progress</p>
              <div className="space-y-2">
                {(runData.agent_statuses ?? []).map((a: any) => (
                  <div key={a.agent} className="flex items-center gap-3 py-2 px-3 rounded-xl bg-[var(--bg)] border border-[var(--border)]">
                    <div className="shrink-0">{statusIcon(a.status)}</div>
                    <div className="flex-1 min-w-0">
                      <p className="text-xs font-semibold text-[var(--text-primary)] truncate">{a.label}</p>
                      <p className={`text-[10px] capitalize ${statusColor(a.status)}`}>{a.status}</p>
                    </div>
                    {a.findings_count > 0 && (
                      <span className="text-[10px] font-bold text-[var(--primary)] bg-[var(--primary-light)] px-2 py-0.5 rounded-full">
                        {a.findings_count} findings
                      </span>
                    )}
                  </div>
                ))}
              </div>

              {/* Summary */}
              <div className="flex items-center gap-4 mt-4 pt-3 border-t border-[var(--border)] text-xs text-[var(--text-muted)]">
                <span>{runData.findings_count ?? 0} total findings</span>
                {runData.time_taken && <span>{Math.round(runData.time_taken)}s runtime</span>}
                {runData.recipient_emails?.length > 0 && (
                  <span title={runData.recipient_emails.join(", ")} className="truncate">
                    📧 {runData.recipient_emails[0]}
                  </span>
                )}
              </div>
            </>
          )}
        </div>

        <div className="px-5 pb-5">
          <button onClick={onClose} className="w-full px-4 py-2.5 rounded-xl border border-[var(--border)] text-sm text-[var(--text-secondary)] hover:bg-[var(--border)] transition-colors">
            Close
          </button>
        </div>
      </div>
    </div>
  );
}

// ── 3 Digest Action Cards (horizontal squares) ───────────────────────────────
function DigestActionCards({
  digest,
  onPdf,
  onAudio,
}: {
  digest: DigestCard;
  onPdf: () => void;
  onAudio: () => void;
}) {
  return (
    <div className="w-full max-w-2xl">
      {/* Brief header */}
      <div className="mb-6">
        <div className="flex items-center gap-2 mb-2">
          <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full bg-[var(--primary)] text-white text-[10px] font-bold tracking-widest uppercase">
            <span className="w-1.5 h-1.5 rounded-full bg-white/80 animate-pulse" />Latest
          </span>
          <span className="text-xs text-[var(--text-muted)]">{timeAgo(digest.created_at)}</span>
        </div>
        <h2 className="text-xl font-bold text-[var(--text-primary)]">Frontier AI Intelligence Brief</h2>
        <p className="text-sm text-[var(--text-muted)] mt-0.5">{formatDate(digest.date)}</p>
        <p className="text-sm text-[var(--text-secondary)] mt-2 line-clamp-2 leading-relaxed max-w-lg">{digest.executive_summary}</p>
        <div className="flex items-center gap-3 mt-2 text-xs text-[var(--text-muted)]">
          <span>{digest.findings_count} findings</span>
          <span className="w-1 h-1 rounded-full bg-current opacity-40" />
          <span>4 AI agents</span>
          <span className="w-1 h-1 rounded-full bg-current opacity-40" />
          <span>Auto-generated</span>
        </div>
      </div>

      {/* 3 square cards in a row */}
      <div className="grid grid-cols-3 gap-4">

        {/* Card 1 — PDF */}
        <button
          onClick={onPdf}
          className="group relative flex flex-col items-center justify-between rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] p-5 aspect-square hover:border-red-400/60 hover:shadow-xl hover:shadow-red-500/8 hover:-translate-y-0.5 transition-all text-left overflow-hidden"
        >
          {/* Background tint on hover */}
          <div className="absolute inset-0 bg-red-500/0 group-hover:bg-red-500/[0.03] transition-colors rounded-2xl" />

          <div className="relative w-full flex flex-col h-full gap-3">
            {/* Icon */}
            <div className="w-11 h-11 rounded-xl bg-red-500/10 group-hover:bg-red-500/18 flex items-center justify-center transition-colors shrink-0">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#ef4444" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                <polyline points="14 2 14 8 20 8" />
                <line x1="16" y1="13" x2="8" y2="13" />
                <line x1="16" y1="17" x2="8" y2="17" />
              </svg>
            </div>

            {/* Text */}
            <div className="flex-1">
              <p className="font-bold text-[var(--text-primary)] text-sm leading-tight">Intelligence Brief</p>
              <p className="text-[11px] text-[var(--text-secondary)] mt-1 leading-relaxed">Full report with all findings & analysis</p>
            </div>

            {/* CTA */}
            <div className="flex items-center gap-1 text-red-500 text-[11px] font-bold">
              Read PDF
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" className="group-hover:translate-x-0.5 transition-transform">
                <line x1="5" y1="12" x2="19" y2="12" /><polyline points="12 5 19 12 12 19" />
              </svg>
            </div>
          </div>
        </button>

        {/* Card 2 — Audio */}
        <button
          onClick={onAudio}
          className="group relative flex flex-col items-center justify-between rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] p-5 aspect-square hover:border-purple-400/60 hover:shadow-xl hover:shadow-purple-500/8 hover:-translate-y-0.5 transition-all text-left overflow-hidden"
        >
          <div className="absolute inset-0 bg-purple-500/0 group-hover:bg-purple-500/[0.03] transition-colors rounded-2xl" />

          <div className="relative w-full flex flex-col h-full gap-3">
            <div className="w-11 h-11 rounded-xl bg-purple-500/10 group-hover:bg-purple-500/18 flex items-center justify-center transition-colors shrink-0">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#a855f7" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M3 18v-6a9 9 0 0 1 18 0v6" />
                <path d="M21 19a2 2 0 0 1-2 2h-1a2 2 0 0 1-2-2v-3a2 2 0 0 1 2-2h3zM3 19a2 2 0 0 0 2 2h1a2 2 0 0 0 2-2v-3a2 2 0 0 0-2-2H3z" />
              </svg>
            </div>

            <div className="flex-1">
              <p className="font-bold text-[var(--text-primary)] text-sm leading-tight">Audio Briefing</p>
              <p className="text-[11px] text-[var(--text-secondary)] mt-1 leading-relaxed">Narrated by AI · hands-free listening</p>
            </div>

            <div className="flex items-center gap-1 text-purple-500 text-[11px] font-bold">
              Play Audio
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" className="group-hover:translate-x-0.5 transition-transform">
                <line x1="5" y1="12" x2="19" y2="12" /><polyline points="12 5 19 12 12 19" />
              </svg>
            </div>
          </div>
        </button>

        {/* Card 3 — Chat + Voice */}
        <div className="relative flex flex-col rounded-2xl border border-[var(--border)] bg-[var(--bg-card)] p-5 aspect-square overflow-hidden">
          <div className="w-11 h-11 rounded-xl bg-[var(--primary-light)] flex items-center justify-center shrink-0">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="var(--primary)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
            </svg>
          </div>

          <div className="flex-1 mt-3">
            <p className="font-bold text-[var(--text-primary)] text-sm leading-tight">Interact with AI</p>
            <p className="text-[11px] text-[var(--text-secondary)] mt-1 leading-relaxed">Choose your mode below</p>
          </div>

          {/* Two mode buttons */}
          <div className="flex gap-2 mt-2">
            <Link
              href={`/digest/${digest.run_id}/chat`}
              className="flex-1 flex items-center justify-center gap-1.5 py-2 rounded-xl bg-[var(--primary-light)] hover:bg-[var(--primary)] text-[var(--primary)] hover:text-white text-[11px] font-bold transition-all"
            >
              {/* Chat icon */}
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
              </svg>
              Text
            </Link>
            <Link
              href={`/digest/${digest.run_id}/voice`}
              className="flex-1 flex items-center justify-center gap-1.5 py-2 rounded-xl border border-[var(--primary)]/40 hover:bg-[var(--primary)] text-[var(--primary)] hover:text-white text-[11px] font-bold transition-all"
            >
              {/* Mic icon */}
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/>
                <path d="M19 10v2a7 7 0 0 1-14 0v-2"/>
                <line x1="12" y1="19" x2="12" y2="23"/>
              </svg>
              Voice
            </Link>
          </div>
        </div>

      </div>
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────
export default function DigestPage() {
  const { user } = useAuth();
  const [digests, setDigests] = useState<DigestCard[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [activePeriod, setActivePeriod] = useState<"daily" | "weekly" | "monthly">("daily");
  const [audioModal, setAudioModal] = useState<{ runId: string; date: string } | null>(null);
  const [pdfModal, setPdfModal] = useState<{ url: string; date: string } | null>(null);
  const [newBriefOpen, setNewBriefOpen] = useState(false);
  const [runStatusId, setRunStatusId] = useState<string | null>(null);
  // Background pipeline tracking
  const [bgRunId, setBgRunId] = useState<string | null>(null);
  const [bgRunning, setBgRunning] = useState(false);
  const bgPollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const loadDigests = useCallback(() => {
    const token = globalThis.localStorage?.getItem("frontier_ai_radar_token");
    fetch("/api/digests", { headers: token ? { Authorization: `Bearer ${token}` } : {} })
      .then((r) => r.json())
      .then((data) => {
        const list: DigestCard[] = data.data || [];
        // sorted by created_at desc (API already sorts, but ensure latest first)
        list.sort((a, b) => (a.created_at < b.created_at ? 1 : -1));
        setDigests(list);
        if (list.length > 0) setSelectedId((prev) => prev ?? list[0].id);
      })
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  const startBgPoll = useCallback((rid: string | null) => {
    setBgRunId(rid);
    setBgRunning(true);
    if (bgPollRef.current) clearInterval(bgPollRef.current);
    bgPollRef.current = setInterval(async () => {
      try {
        const token = globalThis.localStorage?.getItem("frontier_ai_radar_token");
        const hdrs: Record<string, string> = token ? { Authorization: `Bearer ${token}` } : {};
        let status = "";
        if (rid) {
          const res = await fetch(`/api/runs/${rid}`, { headers: hdrs });
          if (res.ok) {
            const d = await res.json();
            status = ((d.data ?? d).status ?? "").toLowerCase();
          }
        } else {
          // No run ID yet — look for any running run
          const res = await fetch("/api/runs?status=running", { headers: hdrs });
          if (res.ok) {
            const d = await res.json();
            const rows = d.data ?? [];
            if (rows.length > 0) {
              const found = String(rows[0].id);
              setBgRunId(found);
              rid = found;
            }
          }
        }
        if (status === "success" || status === "completed") {
          clearInterval(bgPollRef.current!);
          setBgRunning(false);
          loadDigests();
        } else if (status === "failure" || status === "failed") {
          clearInterval(bgPollRef.current!);
          setBgRunning(false);
        }
      } catch { }
    }, 8000);
  }, [loadDigests]);

  useEffect(() => () => { if (bgPollRef.current) clearInterval(bgPollRef.current); }, []);

  useEffect(() => { loadDigests(); }, [loadDigests]);

  // Filter by period — treat missing period field as "daily"
  const filteredDigests = digests.filter(d =>
    activePeriod === "daily"
      ? (!d.period || d.period === "daily")
      : d.period === activePeriod
  );

  const selected = digests.find((d) => d.id === selectedId) ?? null;

  const greeting = () => {
    const h = new Date().getHours();
    if (h < 12) return "Good morning";
    if (h < 17) return "Good afternoon";
    return "Good evening";
  };

  return (
    <div className="flex h-screen bg-[var(--bg)] overflow-hidden">
      {audioModal && <AudioModal runId={audioModal.runId} date={audioModal.date} onClose={() => setAudioModal(null)} />}
      {pdfModal && <PdfViewerModal pdfUrl={pdfModal.url} date={pdfModal.date} onClose={() => setPdfModal(null)} />}
      {newBriefOpen && <NewBriefModal user={user} onClose={() => setNewBriefOpen(false)} onTriggered={(rid) => startBgPoll(rid)} />}
      {runStatusId && <RunStatusModal runId={runStatusId} onClose={() => setRunStatusId(null)} />}

      {/* ── Left sidebar: digest list ── */}
      <div className="w-72 shrink-0 flex flex-col border-r border-[var(--border)] bg-[var(--bg-card)] h-full">
        {/* Sidebar header */}
        <div className="px-4 pt-5 pb-4 border-b border-[var(--border)]">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="font-bold text-[var(--text-primary)] text-sm">Intelligence Briefs</h2>
              <p className="text-xs text-[var(--text-muted)] mt-0.5">{filteredDigests.length} {activePeriod} briefings</p>
            </div>
            <button
              onClick={() => setNewBriefOpen(true)}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-[var(--primary)] hover:bg-[var(--primary-hover)] text-white font-semibold text-xs transition-all shadow-md"
            >
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <polyline points="23 4 23 10 17 10" /><path d="M20.49 15a9 9 0 1 1-.36-3.86" />
              </svg>
              New Brief
            </button>
          </div>
        </div>

        {/* Background pipeline progress pill */}
        {bgRunning && (
          <div className="flex items-center gap-2 px-4 py-2 border-b border-[var(--border)] bg-blue-500/5">
            <svg className="animate-spin shrink-0" width="12" height="12" fill="none" stroke="#60a5fa" strokeWidth="2" viewBox="0 0 24 24">
              <circle cx="12" cy="12" r="10" strokeOpacity="0.3"/><path d="M12 2a10 10 0 0 1 10 10" strokeLinecap="round"/>
            </svg>
            <span className="text-[11px] text-blue-400 flex-1 truncate">
              Pipeline running{bgRunId ? ` · Run #${bgRunId}` : ""}…
            </span>
            {bgRunId && (
              <button
                onClick={() => setRunStatusId(bgRunId)}
                className="text-[10px] text-blue-400 hover:text-blue-300 font-semibold shrink-0"
              >
                View
              </button>
            )}
            <button
              onClick={() => { if (bgPollRef.current) clearInterval(bgPollRef.current); setBgRunning(false); }}
              className="text-[var(--text-muted)] hover:text-[var(--text-secondary)] shrink-0"
            >
              <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
              </svg>
            </button>
          </div>
        )}

        {/* Period tabs */}
        <div className="flex border-b border-[var(--border)]">
          {(["daily", "weekly", "monthly"] as const).map(p => (
            <button
              key={p}
              onClick={() => { setActivePeriod(p); setSelectedId(null); }}
              className={`flex-1 py-2 text-[11px] font-semibold capitalize transition-colors ${
                activePeriod === p
                  ? "text-[var(--primary)] border-b-2 border-[var(--primary)] -mb-px bg-[var(--primary-light)]/40"
                  : "text-[var(--text-muted)] hover:text-[var(--text-secondary)]"
              }`}
            >
              {p}
            </button>
          ))}
        </div>

        {/* List */}
        <div className="flex-1 overflow-y-auto py-2">
          {loading ? (
            <div className="flex items-center justify-center py-12">
              <div className="w-6 h-6 rounded-full bg-[var(--primary)] animate-pulse" />
            </div>
          ) : filteredDigests.length === 0 ? (
            <div className="px-4 py-10 text-center">
              <div className="text-3xl mb-3">📡</div>
              <p className="text-sm font-medium text-[var(--text-primary)]">No {activePeriod} briefs yet</p>
              <p className="text-xs text-[var(--text-muted)] mt-1">
                {activePeriod === "daily" ? 'Click "New Brief" to generate one' : `Select "${activePeriod}" in the New Brief modal`}
              </p>
            </div>
          ) : (
            filteredDigests.map((d, i) => {
              const isSelected = d.id === selectedId;
              return (
                <div
                  key={d.id}
                  className={`relative border-l-2 transition-all ${
                    isSelected ? "border-l-[var(--primary)] bg-[var(--primary-light)]" : "border-l-transparent hover:bg-[var(--primary-light)]/50"
                  }`}
                >
                  <button
                    onClick={() => setSelectedId(d.id)}
                    className="w-full text-left px-4 py-3.5 pr-10"
                  >
                    <div className="flex items-center justify-between mb-1">
                      <span className={`text-xs font-bold ${isSelected ? "text-[var(--primary)]" : "text-[var(--text-muted)]"}`}>
                        {i === 0 ? "LATEST" : `BRIEF #${filteredDigests.length - i}`}
                      </span>
                      <span className="text-[10px] text-[var(--text-muted)]">{timeAgo(d.created_at)}</span>
                    </div>
                    <p className={`text-sm font-semibold truncate ${isSelected ? "text-[var(--primary)]" : "text-[var(--text-primary)]"}`}>
                      {shortDate(d.date)}
                    </p>
                    <p className="text-xs text-[var(--text-muted)] mt-0.5">{d.findings_count} findings</p>
                  </button>

                  {/* Status dot — click to open RunStatusModal */}
                  <button
                    onClick={(e) => { e.stopPropagation(); setRunStatusId(d.run_id); }}
                    title="View pipeline status"
                    className="absolute right-3 top-1/2 -translate-y-1/2 w-6 h-6 rounded-full flex items-center justify-center hover:bg-[var(--border)] transition-colors group"
                  >
                    <div className="w-2 h-2 rounded-full bg-green-400 group-hover:scale-125 transition-transform" />
                  </button>
                </div>
              );
            })
          )}
        </div>
      </div>

      {/* ── Right: greeting + cards ── */}
      <div className="flex-1 overflow-y-auto px-8 py-8">
        {/* Greeting */}
        <div className="mb-8">
          <h1 className="text-2xl font-bold text-[var(--text-primary)]">
            {greeting()},{" "}
            <span className="text-[var(--primary)]">{user?.name?.split(" ")[0] || "there"}.</span>
          </h1>
          <p className="text-[var(--text-secondary)] mt-1 text-sm">
            Select a brief from the left to access PDF, audio, and interactive AI.
          </p>
        </div>

        {/* Cards or empty state */}
        {!selected ? (
          <div className="rounded-2xl border-2 border-dashed border-[var(--border)] p-16 text-center max-w-xl">
            <div className="text-4xl mb-4">📡</div>
            <h2 className="text-lg font-semibold text-[var(--text-primary)] mb-2">No briefing selected</h2>
            <p className="text-sm text-[var(--text-secondary)]">
              {digests.length === 0 ? "No briefs yet — click \"New Brief\" to generate one." : "Pick a briefing from the left panel."}
            </p>
          </div>
        ) : (
          <DigestActionCards
            digest={selected}
            onPdf={() => selected.pdf_url && setPdfModal({ url: selected.pdf_url, date: selected.date })}
            onAudio={() => setAudioModal({ runId: selected.run_id, date: selected.date })}
          />
        )}
      </div>
    </div>
  );
}
