"use client";

import { useAuth } from "../context/AuthContext";
import BackButton from "../components/BackButton";

export default function ProfilePage() {
  const { user } = useAuth();

  // Derive initials
  const initials = user
    ? user.name
        .split(" ")
        .map((w) => w[0])
        .join("")
        .toUpperCase()
        .slice(0, 2)
    : "U";

  return (
    <div className="min-h-screen px-4 py-6 md:px-6 lg:px-8 max-w-2xl mx-auto">
      <div className="flex items-center gap-4 mb-6">
        <BackButton href="/" />
        <h1 className="text-2xl font-semibold text-[var(--text-primary)]">Profile</h1>
      </div>

      {/* Profile Card */}
      <div className="rounded-xl border border-[var(--border)] bg-[var(--bg-card)] shadow-sm overflow-hidden">
        {/* Header banner */}
        <div className="h-28 bg-gradient-to-r from-[var(--primary)] to-[#7c3aed] relative">
          <div className="absolute -bottom-10 left-6">
            <div className="w-20 h-20 rounded-full bg-[var(--primary)] border-4 border-[var(--bg-card)] flex items-center justify-center text-white text-2xl font-bold shadow-lg">
              {initials}
            </div>
          </div>
        </div>

        {/* User details */}
        <div className="pt-14 pb-6 px-6">
          <h2 className="text-xl font-bold text-[var(--text-primary)]">{user?.name || "User"}</h2>
          <p className="text-sm text-[var(--text-secondary)] mt-0.5">{user?.email || "—"}</p>

          {/* Details grid */}
          <div className="mt-6 grid grid-cols-1 sm:grid-cols-2 gap-4">
            {/* Full Name */}
            <div className="rounded-lg border border-[var(--border)] bg-[var(--bg)] p-4">
              <div className="flex items-center gap-2 mb-1.5">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--text-muted)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
                  <circle cx="12" cy="7" r="4" />
                </svg>
                <span className="text-xs font-medium text-[var(--text-muted)] uppercase tracking-wider">Full Name</span>
              </div>
              <p className="text-sm font-semibold text-[var(--text-primary)]">{user?.name || "—"}</p>
            </div>

            {/* Email */}
            <div className="rounded-lg border border-[var(--border)] bg-[var(--bg)] p-4">
              <div className="flex items-center gap-2 mb-1.5">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--text-muted)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z" />
                  <polyline points="22,6 12,13 2,6" />
                </svg>
                <span className="text-xs font-medium text-[var(--text-muted)] uppercase tracking-wider">Email Address</span>
              </div>
              <p className="text-sm font-semibold text-[var(--text-primary)]">{user?.email || "—"}</p>
            </div>

            {/* Account ID */}
            <div className="rounded-lg border border-[var(--border)] bg-[var(--bg)] p-4">
              <div className="flex items-center gap-2 mb-1.5">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--text-muted)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
                  <path d="M7 11V7a5 5 0 0 1 10 0v4" />
                </svg>
                <span className="text-xs font-medium text-[var(--text-muted)] uppercase tracking-wider">Account ID</span>
              </div>
              <p className="text-sm font-semibold text-[var(--text-primary)]">#{user?.id || "—"}</p>
            </div>

            {/* Role */}
            <div className="rounded-lg border border-[var(--border)] bg-[var(--bg)] p-4">
              <div className="flex items-center gap-2 mb-1.5">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--text-muted)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" />
                </svg>
                <span className="text-xs font-medium text-[var(--text-muted)] uppercase tracking-wider">Role</span>
              </div>
              <p className="text-sm font-semibold text-[var(--text-primary)]">
                <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium bg-[var(--primary-light)] text-[var(--primary)]">
                  Admin
                </span>
              </p>
            </div>
          </div>

          {/* Account Status */}
          <div className="mt-6 rounded-lg border border-[var(--border)] bg-[var(--bg)] p-4">
            <div className="flex items-center gap-2 mb-2">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--text-muted)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
                <polyline points="22 4 12 14.01 9 11.01" />
              </svg>
              <span className="text-xs font-medium text-[var(--text-muted)] uppercase tracking-wider">Account Status</span>
            </div>
            <div className="flex items-center gap-2">
              <span className="w-2.5 h-2.5 rounded-full bg-green-500 animate-pulse" />
              <p className="text-sm font-semibold text-green-600">Active</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
