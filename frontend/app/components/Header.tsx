"use client";

import { useState, useEffect } from "react";
import Link from "next/link";

const MOCK_NOTIFICATIONS = [
  { id: "1", title: "Run completed", message: "Report run-001 finished successfully.", time: "10 min ago", read: false },
  { id: "2", title: "Email sent", message: "PDF delivered to 2 recipients.", time: "1 hour ago", read: false },
  { id: "3", title: "Run completed", message: "Report run-002 finished successfully.", time: "Yesterday", read: true },
];

const PROFILE_MENU = [
  { label: "Profile", href: "#" },
  { label: "Settings", href: "/settings" },
  { label: "API Keys", href: "#" },
  { label: "Preferences", href: "#" },
  { label: "Sign out", href: "#", destructive: true },
];

export const HEADER_HEIGHT = 56;

export default function Header() {
  const [profileOpen, setProfileOpen] = useState(false);
  const [notificationOpen, setNotificationOpen] = useState(false);
  const [darkMode, setDarkMode] = useState(false);

  useEffect(() => {
    const stored = globalThis.localStorage?.getItem("theme");
    const preferDark = stored === "dark" || (stored === null && globalThis.matchMedia?.("(prefers-color-scheme: dark)").matches);
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

  const unreadCount = MOCK_NOTIFICATIONS.filter((n) => !n.read).length;

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

          {/* Notifications */}
          <div className="relative">
            <button
              type="button"
              onClick={() => setNotificationOpen(!notificationOpen)}
              className="relative p-2 rounded-lg text-[var(--text-secondary)] hover:bg-[var(--primary-light)] hover:text-[var(--primary)] transition-colors"
              aria-label="Notifications"
            >
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
                <path d="M13 21a1 1 0 0 1-2 0" />
              </svg>
              {unreadCount > 0 && (
                <span className="absolute top-0.5 right-0.5 min-w-[18px] h-[18px] px-1 flex items-center justify-center rounded-full bg-[var(--primary)] text-white text-[10px] font-medium">
                  {unreadCount}
                </span>
              )}
            </button>
            {notificationOpen && (
              <>
                <div className="fixed inset-0 z-40" aria-hidden onClick={() => setNotificationOpen(false)} />
                <div className="absolute right-0 top-full mt-1 w-80 rounded-xl border border-[var(--border)] bg-[var(--bg-card)] shadow-lg py-2 z-50">
                  <div className="px-4 py-2 border-b border-[var(--border)]">
                    <p className="text-sm font-semibold text-[var(--text-primary)]">Notifications</p>
                  </div>
                  {MOCK_NOTIFICATIONS.length === 0 ? (
                    <p className="px-4 py-6 text-sm text-[var(--text-muted)] text-center">No notifications yet.</p>
                  ) : (
                    <ul className="max-h-72 overflow-y-auto">
                      {MOCK_NOTIFICATIONS.map((n) => (
                        <li key={n.id} className={`px-4 py-3 hover:bg-[var(--primary-light)]/30 border-b border-[var(--border)] last:border-0 ${n.read ? "" : "bg-[var(--primary-light)]/10"}`}>
                          <p className="text-sm font-medium text-[var(--text-primary)]">{n.title}</p>
                          <p className="text-xs text-[var(--text-secondary)] mt-0.5">{n.message}</p>
                          <p className="text-[10px] text-[var(--text-muted)] mt-1">{n.time}</p>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              </>
            )}
          </div>

          {/* User profile dropdown (Settings, etc.) */}
          <div className="relative">
            <button
              type="button"
              onClick={() => setProfileOpen(!profileOpen)}
              className="flex items-center gap-2 p-1.5 pr-2 rounded-lg hover:bg-[var(--primary-light)] transition-colors"
              aria-expanded={profileOpen}
              aria-haspopup="true"
            >
              <span className="w-8 h-8 rounded-full bg-[var(--primary)] flex items-center justify-center text-white text-sm font-semibold shrink-0">
                UR
              </span>
              <span className="hidden md:block text-sm font-medium text-[var(--text-primary)] truncate max-w-[120px]">User</span>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className={`shrink-0 text-[var(--text-muted)] transition-transform ${profileOpen ? "rotate-180" : ""}`}>
                <path d="M6 9l6 6 6-6" />
              </svg>
            </button>
            {profileOpen && (
              <>
                <div className="fixed inset-0 z-40" aria-hidden onClick={() => setProfileOpen(false)} />
                <div className="absolute right-0 top-full mt-1 w-52 rounded-xl border border-[var(--border)] bg-[var(--bg-card)] shadow-lg py-1 z-50">
                  {PROFILE_MENU.map((item) =>
                    item.href.startsWith("/") ? (
                      <Link
                        key={item.label}
                        href={item.href}
                        onClick={() => setProfileOpen(false)}
                        className={`block w-full text-left px-4 py-2.5 text-sm transition-colors hover:bg-[var(--primary-light)]/50 ${item.destructive ? "text-red-600 hover:bg-red-50" : "text-[var(--text-primary)]"}`}
                      >
                        {item.label}
                      </Link>
                    ) : (
                      <button
                        key={item.label}
                        type="button"
                        onClick={() => setProfileOpen(false)}
                        className={`block w-full text-left px-4 py-2.5 text-sm transition-colors hover:bg-[var(--primary-light)]/50 ${item.destructive ? "text-red-600 hover:bg-red-50" : "text-[var(--text-primary)]"}`}
                      >
                        {item.label}
                      </button>
                    )
                  )}
                </div>
              </>
            )}
          </div>
        </div>
      </div>
    </header>
  );
}
