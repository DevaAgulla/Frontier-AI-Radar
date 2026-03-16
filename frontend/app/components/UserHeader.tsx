"use client";

import { useState, useEffect, useRef } from "react";
import Link from "next/link";
import { useAuth } from "../context/AuthContext";
import { HEADER_HEIGHT } from "./Header";

export default function UserHeader() {
  const { user, signout } = useAuth();
  const [menuOpen, setMenuOpen] = useState(false);
  const [darkMode, setDarkMode] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const stored = globalThis.localStorage?.getItem("theme");
    const preferDark =
      stored === "dark" ||
      (stored === null && globalThis.matchMedia?.("(prefers-color-scheme: dark)").matches);
    setDarkMode(preferDark);
    if (preferDark) globalThis.document.documentElement.classList.add("dark");
    else globalThis.document.documentElement.classList.remove("dark");
  }, []);

  useEffect(() => {
    const handleClick = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false);
      }
    };
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  const toggleDark = () => {
    const next = !darkMode;
    setDarkMode(next);
    globalThis.localStorage?.setItem("theme", next ? "dark" : "light");
    if (next) globalThis.document.documentElement.classList.add("dark");
    else globalThis.document.documentElement.classList.remove("dark");
  };

  return (
    <header
      className="fixed top-0 left-0 right-0 z-50 flex items-center justify-between px-6 border-b border-[var(--border)] bg-[var(--header-bg)] backdrop-blur"
      style={{ height: `${HEADER_HEIGHT}px`, boxShadow: "0 1px 3px rgba(0,0,0,0.06)" }}
    >
      {/* Logo */}
      <Link href="/digest" className="flex items-center gap-2.5 select-none">
        <div className="w-8 h-8 rounded-lg bg-[var(--primary)] flex items-center justify-center">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2.5">
            <circle cx="12" cy="12" r="2.5" />
            <circle cx="12" cy="12" r="6" strokeOpacity="0.6" />
            <line x1="12" y1="12" x2="12" y2="2" />
          </svg>
        </div>
        <span className="font-bold text-[var(--text-primary)] text-sm tracking-tight">
          Frontier AI Radar
        </span>
      </Link>

      {/* Right side */}
      <div className="flex items-center gap-3">
        {/* Dark mode toggle */}
        <button
          onClick={toggleDark}
          className="w-8 h-8 rounded-lg flex items-center justify-center text-[var(--text-secondary)] hover:bg-[var(--primary-light)] hover:text-[var(--primary)] transition-colors"
          aria-label="Toggle dark mode"
        >
          {darkMode ? (
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="12" cy="12" r="5" /><line x1="12" y1="1" x2="12" y2="3" /><line x1="12" y1="21" x2="12" y2="23" />
              <line x1="4.22" y1="4.22" x2="5.64" y2="5.64" /><line x1="18.36" y1="18.36" x2="19.78" y2="19.78" />
              <line x1="1" y1="12" x2="3" y2="12" /><line x1="21" y1="12" x2="23" y2="12" />
              <line x1="4.22" y1="19.78" x2="5.64" y2="18.36" /><line x1="18.36" y1="5.64" x2="19.78" y2="4.22" />
            </svg>
          ) : (
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
            </svg>
          )}
        </button>

        {/* Profile menu */}
        <div className="relative" ref={menuRef}>
          <button
            onClick={() => setMenuOpen((o) => !o)}
            className="flex items-center gap-2 px-3 py-1.5 rounded-lg hover:bg-[var(--primary-light)] transition-colors"
          >
            <div className="w-7 h-7 rounded-full bg-[var(--primary)] flex items-center justify-center text-white text-xs font-bold">
              {user?.name?.[0]?.toUpperCase() || "U"}
            </div>
            <span className="text-sm font-medium text-[var(--text-primary)] hidden sm:block max-w-[120px] truncate">
              {user?.name}
            </span>
            <svg
              width="12"
              height="12"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              className={`text-[var(--text-muted)] transition-transform ${menuOpen ? "rotate-180" : ""}`}
            >
              <polyline points="6 9 12 15 18 9" />
            </svg>
          </button>

          {menuOpen && (
            <div className="absolute right-0 top-full mt-1.5 w-48 rounded-xl border border-[var(--border)] bg-[var(--bg-card)] shadow-lg py-1 z-50">
              <div className="px-4 py-2.5 border-b border-[var(--border)]">
                <p className="text-sm font-semibold text-[var(--text-primary)] truncate">{user?.name}</p>
                <p className="text-xs text-[var(--text-muted)] truncate">{user?.email}</p>
              </div>
              <Link
                href="/profile"
                onClick={() => setMenuOpen(false)}
                className="flex items-center gap-2.5 w-full px-4 py-2 text-sm text-[var(--text-primary)] hover:bg-[var(--primary-light)] hover:text-[var(--primary)] transition-colors"
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" /><circle cx="12" cy="7" r="4" />
                </svg>
                Profile
              </Link>
              <button
                onClick={() => { setMenuOpen(false); signout(); }}
                className="flex items-center gap-2.5 w-full px-4 py-2 text-sm text-red-500 hover:bg-red-50 dark:hover:bg-red-950/30 transition-colors"
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" /><polyline points="16 17 21 12 16 7" /><line x1="21" y1="12" x2="9" y2="12" />
                </svg>
                Sign out
              </button>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
