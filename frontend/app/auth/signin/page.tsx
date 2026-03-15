"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuth } from "@/app/context/AuthContext";

export default function SigninPage() {
  const { signin } = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");

    if (!email.includes("@")) {
      setError("Please enter a valid email address.");
      return;
    }
    if (!password) {
      setError("Please enter your password.");
      return;
    }

    setLoading(true);
    const result = await signin(email.trim().toLowerCase(), password);
    setLoading(false);

    if (result.ok) {
      // Route based on role: non-admin users go to the user digest view
      try {
        const stored = globalThis.localStorage?.getItem("frontier_ai_radar_user");
        const u = stored ? JSON.parse(stored) : null;
        router.push(u?.is_admin === false ? "/digest" : "/");
      } catch {
        router.push("/");
      }
    } else {
      setError(result.error || "Sign in failed. Please try again.");
    }
  };

  return (
    <div className="min-h-screen flex bg-[var(--bg)]">
      {/* Left: Visual panel */}
      <div className="hidden lg:flex lg:w-1/2 relative overflow-hidden">
        <div className="absolute inset-0 bg-gradient-to-br from-[var(--primary)] via-purple-600 to-cyan-500" />
        <div className="absolute inset-0 opacity-10">
          <div className="absolute top-20 left-20 w-72 h-72 rounded-full border border-white/30" />
          <div className="absolute top-40 left-40 w-48 h-48 rounded-full border border-white/20" />
          <div className="absolute bottom-20 right-20 w-64 h-64 rounded-full border border-white/20" />
          <div className="absolute top-1/3 right-1/4 w-32 h-32 rounded-full bg-white/10" />
        </div>
        <div className="relative z-10 flex flex-col justify-center px-12 text-white">
          <div className="flex items-center gap-3 mb-8">
            <div className="w-10 h-10 rounded-xl bg-white/20 backdrop-blur flex items-center justify-center">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2.5">
                <circle cx="12" cy="12" r="2.5" /><circle cx="12" cy="12" r="6" strokeOpacity="0.6" /><line x1="12" y1="12" x2="12" y2="2" />
              </svg>
            </div>
            <span className="text-xl font-bold">Frontier AI Radar</span>
          </div>
          <h2 className="text-3xl font-bold leading-tight mb-4">
            Welcome Back
          </h2>
          <p className="text-white/80 text-base leading-relaxed max-w-md">
            Your AI intelligence dashboard is ready. Sign in to view the latest findings,
            trigger new pipeline runs, and manage your daily digests.
          </p>

          {/* Pipeline mini-viz */}
          <div className="mt-10 flex items-center gap-3">
            {[
              { emoji: "🔬", label: "Research" },
              { emoji: "🏢", label: "Competitor" },
              { emoji: "🤖", label: "Models" },
              { emoji: "📊", label: "Benchmarks" },
            ].map((a, i) => (
              <div key={a.label} className="flex items-center gap-2">
                <div className="bg-white/15 backdrop-blur rounded-lg px-3 py-2 text-center">
                  <div className="text-lg">{a.emoji}</div>
                  <div className="text-[10px] text-white/70 mt-0.5">{a.label}</div>
                </div>
                {i < 3 && (
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2" strokeOpacity="0.4">
                    <polyline points="9 18 15 12 9 6" />
                  </svg>
                )}
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Right: Form */}
      <div className="flex-1 flex items-center justify-center px-6 py-12">
        <div className="w-full max-w-md">
          {/* Mobile logo */}
          <div className="flex items-center gap-2.5 mb-8 lg:hidden">
            <div className="w-9 h-9 rounded-xl bg-[var(--primary)] flex items-center justify-center">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2.5">
                <circle cx="12" cy="12" r="2.5" /><circle cx="12" cy="12" r="6" strokeOpacity="0.6" /><line x1="12" y1="12" x2="12" y2="2" />
              </svg>
            </div>
            <span className="text-lg font-bold text-[var(--text-primary)]">Frontier AI Radar</span>
          </div>

          <h1 className="text-2xl font-bold text-[var(--text-primary)] mb-2">Sign in to your account</h1>
          <p className="text-sm text-[var(--text-secondary)] mb-8">
            Don&apos;t have an account?{" "}
            <Link href="/auth/signup" className="text-[var(--primary)] hover:underline font-medium">
              Create one
            </Link>
          </p>

          {error && (
            <div className="mb-4 px-4 py-3 rounded-lg bg-[var(--error-bg)] border border-red-200 text-sm text-[var(--error-text)]">
              {error}
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-5">
            <div>
              <label htmlFor="email" className="block text-sm font-medium text-[var(--text-primary)] mb-1.5">
                Email Address
              </label>
              <input
                id="email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@example.com"
                required
                autoComplete="email"
                className="w-full px-4 py-3 rounded-lg border border-[var(--border)] bg-[var(--bg-card)] text-[var(--text-primary)] text-sm placeholder:text-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-[var(--primary)]/30 focus:border-[var(--primary)] transition-colors"
              />
            </div>
            <div>
              <label htmlFor="password" className="block text-sm font-medium text-[var(--text-primary)] mb-1.5">
                Password
              </label>
              <input
                id="password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Enter your password"
                required
                autoComplete="current-password"
                className="w-full px-4 py-3 rounded-lg border border-[var(--border)] bg-[var(--bg-card)] text-[var(--text-primary)] text-sm placeholder:text-[var(--text-muted)] focus:outline-none focus:ring-2 focus:ring-[var(--primary)]/30 focus:border-[var(--primary)] transition-colors"
              />
            </div>

            <button
              type="submit"
              disabled={loading}
              className="w-full py-3.5 rounded-lg bg-[var(--primary)] hover:bg-[var(--primary-hover)] text-white font-semibold text-sm transition-colors disabled:opacity-50 disabled:cursor-not-allowed shadow-md"
            >
              {loading ? (
                <span className="flex items-center justify-center gap-2">
                  <svg className="animate-spin w-4 h-4" viewBox="0 0 24 24" fill="none">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                  </svg>
                  Signing in…
                </span>
              ) : (
                "Sign In"
              )}
            </button>
          </form>

          <div className="mt-8 pt-6 border-t border-[var(--border)]">
            <Link
              href="/"
              className="flex items-center justify-center gap-2 text-sm text-[var(--text-secondary)] hover:text-[var(--primary)] transition-colors"
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <line x1="19" y1="12" x2="5" y2="12" /><polyline points="12 19 5 12 12 5" />
              </svg>
              Back to home
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}
