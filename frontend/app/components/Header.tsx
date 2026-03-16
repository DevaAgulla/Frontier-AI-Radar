"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { useAuth } from "../context/AuthContext";

export const HEADER_HEIGHT = 56;

export default function Header() {
  const { user, signout } = useAuth();
  const [profileOpen, setProfileOpen] = useState(false);
  const [darkMode, setDarkMode] = useState(false);

  useEffect(() => {
    // Default to dark — only switch light if user explicitly chose it
    const stored = globalThis.localStorage?.getItem("theme");
    const preferDark = stored !== "light";
    setDarkMode(preferDark);
    if (preferDark) globalThis.document.documentElement.classList.add("dark");
    else globalThis.document.documentElement.classList.remove("dark");
  }, []);

  const toggleDarkMode = () => {
    setDarkMode((prev) => {
      const next = !prev;
      globalThis.document.documentElement.classList.toggle("dark", next);
      globalThis.localStorage?.setItem("theme", next ? "dark" : "light");
      return next;
    });
  };

  // Derive initials from user name
  const initials = user
    ? user.name
        .split(" ")
        .map((w) => w[0])
        .join("")
        .toUpperCase()
        .slice(0, 2)
    : "U";

  const displayName = user?.name || "User";

  return (
    <header
      className="fixed top-0 left-0 right-0 z-50 h-14 border-b border-[var(--border)] bg-[var(--header-bg)] transition-colors"
      style={{ height: `${HEADER_HEIGHT}px` }}
    >
      <div className="h-full w-full px-4 md:px-6 flex items-center justify-between">
        {/* Logo + App name */}
        <Link href="/" className="flex items-center gap-2.5 min-w-0">
          <div className="w-8 h-8 rounded-lg bg-[var(--primary)] flex items-center justify-center shrink-0">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="12" cy="12" r="2.5" />
              <circle cx="12" cy="12" r="6" strokeOpacity="0.6" fill="none" />
              <line x1="12" y1="12" x2="12" y2="2" />
            </svg>
          </div>
          <span className="text-[15px] font-semibold text-[var(--text-primary)] tracking-tight truncate hidden sm:inline">
            Frontier AI Radar
          </span>
        </Link>

        {/* Right: Dark mode, Notifications, Profile */}
        <div className="flex items-center gap-1 md:gap-2">
          {/* Dark mode toggle */}
          <button
            type="button"
            onClick={toggleDarkMode}
            aria-label={darkMode ? "Switch to light mode" : "Switch to dark mode"}
            title={darkMode ? "Light mode" : "Dark mode"}
            className="p-2 rounded-lg text-[var(--text-secondary)] hover:bg-[var(--primary-light)] hover:text-[var(--primary)] transition-colors"
          >
            {darkMode ? (
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="12" r="5" />
                <line x1="12" y1="1" x2="12" y2="3" />
                <line x1="12" y1="21" x2="12" y2="23" />
                <line x1="4.22" y1="4.22" x2="5.64" y2="5.64" />
                <line x1="18.36" y1="18.36" x2="19.78" y2="19.78" />
                <line x1="1" y1="12" x2="3" y2="12" />
                <line x1="21" y1="12" x2="23" y2="12" />
                <line x1="4.22" y1="19.78" x2="5.64" y2="18.36" />
                <line x1="18.36" y1="5.64" x2="19.78" y2="4.22" />
              </svg>
            ) : (
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
              </svg>
            )}
          </button>

          {/* Notifications — tooltip only */}
          <div className="relative group">
            <button
              type="button"
              className="relative p-2 rounded-lg text-[var(--text-secondary)] hover:bg-[var(--primary-light)] hover:text-[var(--primary)] transition-colors cursor-default"
              aria-label="Notifications"
            >
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
                <path d="M13 21a1 1 0 0 1-2 0" />
              </svg>
            </button>
            {/* Tooltip on hover */}
            <div className="absolute right-0 top-full mt-2 w-64 px-4 py-3 rounded-xl border border-[var(--border)] bg-[var(--bg-card)] shadow-lg z-50 opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all duration-200 pointer-events-none">
              <div className="flex items-center gap-2 mb-1.5">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--primary)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
                  <path d="M13 21a1 1 0 0 1-2 0" />
                </svg>
                <p className="text-sm font-semibold text-[var(--text-primary)]">Notifications</p>
              </div>
              <p className="text-xs text-[var(--text-secondary)] leading-relaxed">
                🚀 Real-time notification system coming soon...
              </p>
              <p className="text-[10px] text-[var(--text-muted)] mt-1.5">
                Stay tuned for live alerts on run completions, email deliveries, and more.
              </p>
            </div>
          </div>

          {/* User profile dropdown */}
          <div className="relative">
            <button
              type="button"
              onClick={() => setProfileOpen(!profileOpen)}
              className="flex items-center gap-2 p-1.5 pr-2 rounded-lg hover:bg-[var(--primary-light)] transition-colors"
              aria-expanded={profileOpen}
              aria-haspopup="true"
            >
              <span className="w-8 h-8 rounded-full bg-[var(--primary)] flex items-center justify-center text-white text-sm font-semibold shrink-0">
                {initials}
              </span>
              <span className="hidden md:block text-sm font-medium text-[var(--text-primary)] truncate max-w-[120px]">{displayName}</span>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className={`shrink-0 text-[var(--text-muted)] transition-transform ${profileOpen ? "rotate-180" : ""}`}>
                <path d="M6 9l6 6 6-6" />
              </svg>
            </button>
            {profileOpen && (
              <>
                <div className="fixed inset-0 z-40" aria-hidden onClick={() => setProfileOpen(false)} />
                <div className="absolute right-0 top-full mt-1 w-52 rounded-xl border border-[var(--border)] bg-[var(--bg-card)] shadow-lg py-1 z-50">
                  {/* User info */}
                  {user && (
                    <div className="px-4 py-3 border-b border-[var(--border)]">
                      <p className="text-sm font-medium text-[var(--text-primary)] truncate">{user.name}</p>
                      <p className="text-xs text-[var(--text-muted)] truncate">{user.email}</p>
                    </div>
                  )}
                  {/* Profile link */}
                  <Link
                    href="/profile"
                    onClick={() => setProfileOpen(false)}
                    className="flex items-center gap-2.5 w-full text-left px-4 py-2.5 text-sm transition-colors hover:bg-[var(--primary-light)]/50 text-[var(--text-primary)]"
                  >
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
                      <circle cx="12" cy="7" r="4" />
                    </svg>
                    Profile
                  </Link>
                  {/* Sign out button */}
                  <button
                    type="button"
                    onClick={() => {
                      setProfileOpen(false);
                      signout();
                    }}
                    className="flex items-center gap-2.5 w-full text-left px-4 py-2.5 text-sm transition-colors hover:bg-red-50 text-red-600 border-t border-[var(--border)]"
                  >
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
                      <polyline points="16 17 21 12 16 7" />
                      <line x1="21" y1="12" x2="9" y2="12" />
                    </svg>
                    Sign out
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      </div>
    </header>
  );
}
