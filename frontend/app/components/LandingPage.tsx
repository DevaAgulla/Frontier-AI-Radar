"use client";

import Link from "next/link";
import { useState, useEffect } from "react";

const FEATURES = [
  {
    title: "Multi-Agent Intelligence",
    desc: "Four specialized AI agents — Research, Competitor, Foundation Model, and Benchmark — work in parallel to scan the entire AI landscape daily.",
    icon: (
      <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="12" cy="5" r="3" />
        <circle cx="5" cy="19" r="3" />
        <circle cx="19" cy="19" r="3" />
        <line x1="12" y1="8" x2="5" y2="16" />
        <line x1="12" y1="8" x2="19" y2="16" />
      </svg>
    ),
  },
  {
    title: "Impact-Ranked Findings",
    desc: "Every finding is scored with a deterministic formula — Relevance, Novelty, Credibility, Actionability — so you see what matters most first.",
    icon: (
      <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <polyline points="22 12 18 12 15 21 9 3 6 12 2 12" />
      </svg>
    ),
  },
  {
    title: "Automated PDF Digests",
    desc: "Professional-grade reports generated automatically — executive summary, ranked findings, evidence, and charts — delivered to your inbox.",
    icon: (
      <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
        <polyline points="14 2 14 8 20 8" />
        <line x1="16" y1="13" x2="8" y2="13" />
        <line x1="16" y1="17" x2="8" y2="17" />
        <polyline points="10 9 9 9 8 9" />
      </svg>
    ),
  },
  {
    title: "Email Delivery",
    desc: "Automated email distribution with PDF attachments — SMTP and HTTP API support — so your team never misses a breakthrough.",
    icon: (
      <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z" />
        <polyline points="22,6 12,13 2,6" />
      </svg>
    ),
  },
  {
    title: "Smart Scheduling",
    desc: "Set it and forget it — daily cron jobs run the full pipeline at your preferred time and deliver fresh intelligence automatically.",
    icon: (
      <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="12" cy="12" r="10" />
        <polyline points="12 6 12 12 16 14" />
      </svg>
    ),
  },
  {
    title: "Compare & Track",
    desc: "Compare reports across dates with LLM-powered diff analysis. Track how the AI landscape evolves day by day.",
    icon: (
      <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="8" cy="12" r="3" />
        <circle cx="16" cy="12" r="3" />
        <path d="M11 12h2" />
      </svg>
    ),
  },
];

const STATS = [
  { value: "4", label: "AI Agents" },
  { value: "100+", label: "Sources Scanned" },
  { value: "5min", label: "Full Pipeline" },
  { value: "24/7", label: "Monitoring" },
];

export default function LandingPage() {
  const [darkMode, setDarkMode] = useState(false);

  useEffect(() => {
    setDarkMode(document.documentElement.classList.contains("dark"));
  }, []);

  return (
    <div className="min-h-screen bg-[var(--bg)] text-[var(--text-primary)] overflow-x-hidden">
      {/* ── Top Nav ─────────────────────────────────────────────── */}
      <nav className="fixed top-0 left-0 right-0 z-50 h-16 border-b border-[var(--border)] bg-[var(--header-bg)]/80 backdrop-blur-lg">
        <div className="max-w-6xl mx-auto h-full px-6 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-[var(--primary)] flex items-center justify-center shadow-lg">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="12" r="2.5" />
                <circle cx="12" cy="12" r="6" strokeOpacity="0.6" fill="none" />
                <line x1="12" y1="12" x2="12" y2="2" />
              </svg>
            </div>
            <span className="text-lg font-bold tracking-tight">Frontier AI Radar</span>
          </div>
          <div className="flex items-center gap-3">
            {/* Dark mode toggle */}
            <button
              type="button"
              onClick={() => {
                const next = !darkMode;
                setDarkMode(next);
                document.documentElement.classList.toggle("dark", next);
                localStorage.setItem("theme", next ? "dark" : "light");
              }}
              className="p-2 rounded-lg text-[var(--text-secondary)] hover:bg-[var(--primary-light)] hover:text-[var(--primary)] transition-colors"
              aria-label="Toggle dark mode"
            >
              {darkMode ? (
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <circle cx="12" cy="12" r="5" /><line x1="12" y1="1" x2="12" y2="3" /><line x1="12" y1="21" x2="12" y2="23" />
                  <line x1="4.22" y1="4.22" x2="5.64" y2="5.64" /><line x1="18.36" y1="18.36" x2="19.78" y2="19.78" />
                  <line x1="1" y1="12" x2="3" y2="12" /><line x1="21" y1="12" x2="23" y2="12" />
                  <line x1="4.22" y1="19.78" x2="5.64" y2="18.36" /><line x1="18.36" y1="5.64" x2="19.78" y2="4.22" />
                </svg>
              ) : (
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
                </svg>
              )}
            </button>
            <Link
              href="/auth/signin"
              className="text-sm font-medium text-[var(--text-secondary)] hover:text-[var(--primary)] transition-colors px-4 py-2"
            >
              Sign In
            </Link>
            <Link
              href="/auth/signup"
              className="text-sm font-semibold text-white bg-[var(--primary)] hover:bg-[var(--primary-hover)] px-5 py-2.5 rounded-lg transition-colors shadow-md"
            >
              Get Started
            </Link>
          </div>
        </div>
      </nav>

      {/* ── Hero ───────────────────────────────────────────────── */}
      <section className="relative pt-32 pb-20 px-6">
        {/* Gradient background effect */}
        <div className="absolute inset-0 overflow-hidden pointer-events-none" aria-hidden>
          <div
            className="absolute top-0 left-1/2 -translate-x-1/2 w-[800px] h-[600px] rounded-full opacity-20"
            style={{
              background: "radial-gradient(ellipse at center, var(--primary) 0%, transparent 70%)",
              filter: "blur(80px)",
            }}
          />
          <div
            className="absolute top-40 right-10 w-[300px] h-[300px] rounded-full opacity-10"
            style={{
              background: "radial-gradient(circle, #06b6d4 0%, transparent 70%)",
              filter: "blur(60px)",
            }}
          />
        </div>

        <div className="relative max-w-4xl mx-auto text-center">
          {/* Badge */}
          <div className="inline-flex items-center gap-2 px-4 py-1.5 rounded-full border border-[var(--border)] bg-[var(--bg-card)] text-xs font-medium text-[var(--text-secondary)] mb-8 shadow-sm">
            <span className="w-2 h-2 rounded-full bg-green-500 animate-pulse" />
            Multi-Agent AI Intelligence System
          </div>

          <h1 className="text-4xl sm:text-5xl lg:text-6xl font-extrabold tracking-tight leading-[1.1] mb-6">
            Track the{" "}
            <span className="bg-gradient-to-r from-[var(--primary)] via-purple-400 to-cyan-400 bg-clip-text text-transparent">
              AI Frontier
            </span>
            <br />
            Before Everyone Else
          </h1>

          <p className="text-lg sm:text-xl text-[var(--text-secondary)] max-w-2xl mx-auto mb-10 leading-relaxed">
            Four autonomous AI agents scan research papers, competitor moves, model releases, and benchmarks
            — then rank, summarize, and deliver a professional digest to your inbox. Every single day.
          </p>

          <div className="flex flex-col sm:flex-row items-center justify-center gap-4 mb-16">
            <Link
              href="/auth/signup"
              className="inline-flex items-center gap-2 text-base font-semibold text-white bg-[var(--primary)] hover:bg-[var(--primary-hover)] px-8 py-3.5 rounded-xl transition-all shadow-lg hover:shadow-xl"
            >
              Start Monitoring
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <line x1="5" y1="12" x2="19" y2="12" /><polyline points="12 5 19 12 12 19" />
              </svg>
            </Link>
            <Link
              href="/auth/signin"
              className="inline-flex items-center gap-2 text-base font-medium text-[var(--text-primary)] border border-[var(--border)] hover:border-[var(--primary)] bg-[var(--bg-card)] px-8 py-3.5 rounded-xl transition-all"
            >
              Sign In
            </Link>
          </div>

          {/* Stats */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-6 max-w-2xl mx-auto">
            {STATS.map((s) => (
              <div key={s.label} className="text-center">
                <div className="text-2xl font-bold text-[var(--primary)]">{s.value}</div>
                <div className="text-xs text-[var(--text-muted)] mt-1">{s.label}</div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── Pipeline Visualization ─────────────────────────────── */}
      <section className="py-16 px-6 border-t border-[var(--border)]">
        <div className="max-w-5xl mx-auto">
          <h2 className="text-center text-2xl sm:text-3xl font-bold mb-4">How It Works</h2>
          <p className="text-center text-[var(--text-secondary)] mb-12 max-w-xl mx-auto">
            An autonomous pipeline powered by LangGraph orchestrates specialized agents through a ReAct reasoning loop.
          </p>

          <div className="flex flex-col sm:flex-row items-stretch gap-3 justify-center">
            {[
              { step: "1", name: "Mission Control", desc: "Plans strategy & selects agents", color: "#8b5cf6" },
              { step: "2", name: "Intel Agents", desc: "Research, Competitor, Model, Benchmark", color: "#3b82f6" },
              { step: "3", name: "Ranking Engine", desc: "Score, deduplicate, cluster", color: "#06b6d4" },
              { step: "4", name: "PDF Digest", desc: "Professional report generation", color: "#10b981" },
              { step: "5", name: "Email Delivery", desc: "SMTP / HTTP API with attachment", color: "#f59e0b" },
            ].map((item, idx) => (
              <div key={item.step} className="flex items-center gap-2 flex-1">
                <div
                  className="flex-1 rounded-xl border border-[var(--border)] bg-[var(--bg-card)] p-4 text-center shadow-sm hover:shadow-md transition-shadow"
                  style={{ borderTopColor: item.color, borderTopWidth: "3px" }}
                >
                  <div
                    className="w-8 h-8 rounded-full mx-auto mb-2 flex items-center justify-center text-white text-sm font-bold"
                    style={{ background: item.color }}
                  >
                    {item.step}
                  </div>
                  <div className="text-sm font-semibold mb-1">{item.name}</div>
                  <div className="text-xs text-[var(--text-muted)]">{item.desc}</div>
                </div>
                {idx < 4 && (
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="var(--text-muted)" strokeWidth="2" className="shrink-0 hidden sm:block">
                    <polyline points="9 18 15 12 9 6" />
                  </svg>
                )}
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── Features Grid ──────────────────────────────────────── */}
      <section className="py-16 px-6 border-t border-[var(--border)] bg-[var(--bg-card)]/50">
        <div className="max-w-5xl mx-auto">
          <h2 className="text-center text-2xl sm:text-3xl font-bold mb-4">Everything You Need</h2>
          <p className="text-center text-[var(--text-secondary)] mb-12 max-w-xl mx-auto">
            Built for AI teams, researchers, and decision-makers who need to stay ahead of the curve.
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">
            {FEATURES.map((f) => (
              <div
                key={f.title}
                className="rounded-xl border border-[var(--border)] bg-[var(--bg-card)] p-6 hover:border-[var(--primary)]/50 hover:shadow-lg transition-all group"
              >
                <div className="w-12 h-12 rounded-xl bg-[var(--primary-light)] border border-[var(--border-purple)] flex items-center justify-center text-[var(--primary)] mb-4 group-hover:scale-110 transition-transform">
                  {f.icon}
                </div>
                <h3 className="text-base font-semibold mb-2">{f.title}</h3>
                <p className="text-sm text-[var(--text-secondary)] leading-relaxed">{f.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── CTA Section ────────────────────────────────────────── */}
      <section className="py-20 px-6 border-t border-[var(--border)]">
        <div className="max-w-2xl mx-auto text-center">
          <h2 className="text-2xl sm:text-3xl font-bold mb-4">Ready to Monitor the AI Frontier?</h2>
          <p className="text-[var(--text-secondary)] mb-8">
            Create your account and start receiving daily AI intelligence digests powered by multi-agent reasoning.
          </p>
          <Link
            href="/auth/signup"
            className="inline-flex items-center gap-2 text-base font-semibold text-white bg-[var(--primary)] hover:bg-[var(--primary-hover)] px-10 py-4 rounded-xl transition-all shadow-lg hover:shadow-xl"
          >
            Create Free Account
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <line x1="5" y1="12" x2="19" y2="12" /><polyline points="12 5 19 12 12 19" />
            </svg>
          </Link>
        </div>
      </section>

      {/* ── Footer ─────────────────────────────────────────────── */}
      <footer className="border-t border-[var(--border)] py-8 px-6">
        <div className="max-w-5xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-4">
          <div className="flex items-center gap-2 text-sm text-[var(--text-muted)]">
            <div className="w-6 h-6 rounded-md bg-[var(--primary)] flex items-center justify-center">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2.5">
                <circle cx="12" cy="12" r="2.5" /><circle cx="12" cy="12" r="6" strokeOpacity="0.6" /><line x1="12" y1="12" x2="12" y2="2" />
              </svg>
            </div>
            Frontier AI Radar &copy; {new Date().getFullYear()}
          </div>
          <div className="text-xs text-[var(--text-muted)]">
            Multi-Agent Intelligence System &middot; Built with LangGraph + Next.js + FastAPI
          </div>
        </div>
      </footer>
    </div>
  );
}
