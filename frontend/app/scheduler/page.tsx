"use client";

import { useEffect, useState } from "react";
import BackButton from "../components/BackButton";
import { api } from "@/lib/api";
import { useToast } from "../context/ToastContext";
import { useAuth } from "../context/AuthContext";
import type { SchedulerSubscriber } from "@/lib/types";

function isDummyEmail(email: string): boolean {
  const v = (email || "").trim().toLowerCase();
  if (!v) return true;
  const markers = [
    "your-email",
    "example.com",
    "test@",
    "demo@",
    "sample@",
    "placeholder",
  ];
  return markers.some((m) => v.includes(m));
}

export default function SchedulerPage() {
  const { pushToast } = useToast();
  const { user } = useAuth();
  const [email, setEmail] = useState(user?.email ?? "");
  const [scheduled, setScheduled] = useState<{ message: string; time: string } | null>(null);
  const [subscribers, setSubscribers] = useState<SchedulerSubscriber[]>([]);
  const [loadingSubscribers, setLoadingSubscribers] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const loadSubscribers = async () => {
    setLoadingSubscribers(true);
    const res = await api.getSchedulerSubscribers();
    setLoadingSubscribers(false);
    if (res.data) {
      setSubscribers((res.data.subscribers || []).filter((s) => !isDummyEmail(s.email)));
    }
  };

  useEffect(() => {
    loadSubscribers();
  }, []);

  const handleSchedule = async () => {
    if (!email.trim()) return;
    setSubmitting(true);
    const res = await api.schedulerSubscribe({ email: email.trim() });
    setSubmitting(false);
    if (res.error) {
      pushToast(res.error, "error");
      return;
    }
    if (res.data) {
      setScheduled({ message: res.data.message, time: res.data.schedule_time });
      pushToast("Scheduler subscription saved", "success");
      setEmail("");
      await loadSubscribers();
    }
  };

  return (
    <div className="min-h-full min-w-0 max-w-full py-4">
      <div className="flex items-center gap-4 mb-2">
        <BackButton href="/" label="Back" />
        <h1 className="text-2xl font-semibold text-[var(--text-primary)]">Scheduler</h1>
      </div>
      <p className="text-sm text-[var(--text-secondary)] mb-6">
        Get your daily report at 5:00 PM with AI, research, models, and Hugging Face updates delivered to your email.
      </p>

      <div className="flex flex-col gap-6 max-w-xl min-w-0">
        <div className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--primary-light)]/20 px-4 py-3 text-sm text-[var(--text-secondary)]">
          Your daily report is sent at <strong className="text-[var(--text-primary)]">5:00 PM</strong> and includes AI, research, model, and Hugging Face updates. Enter your email below to receive it.
        </div>

        <div>
          <label htmlFor="scheduler-email" className="block text-sm font-semibold text-[var(--text-primary)] mb-2">
            Email
          </label>
          <input
            id="scheduler-email"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="Enter email to receive daily updates"
            className="w-full rounded-[var(--radius)] border border-[var(--border)] bg-[var(--bg-card)] px-4 py-3 text-sm text-[var(--text-primary)] placeholder-[var(--text-muted)] focus:border-[var(--primary)] focus:outline-none focus:ring-1 focus:ring-[var(--primary)]"
          />
        </div>

        <div className="pt-1">
          <button
            type="button"
            onClick={handleSchedule}
            disabled={!email.trim() || submitting}
            className="inline-flex items-center gap-2 px-5 py-2.5 rounded-[var(--radius)] text-sm font-medium bg-[var(--primary)] text-white hover:bg-[var(--primary-hover)] disabled:opacity-50 disabled:cursor-not-allowed transition-all shadow-md"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="12" cy="12" r="10" />
              <polyline points="12 6 12 12 16 14" />
            </svg>
            {submitting ? "Saving..." : "Submit"}
          </button>
          <button
            type="button"
            onClick={loadSubscribers}
            className="ml-2 inline-flex items-center gap-2 px-4 py-2.5 rounded-[var(--radius)] text-sm font-medium border border-[var(--border)] text-[var(--text-secondary)] hover:text-[var(--primary)] hover:border-[var(--primary)] transition-all"
          >
            Refresh subscribers
          </button>
        </div>

        {scheduled && (
          <p className="text-sm text-[var(--success-text)] bg-[var(--success-bg)] px-3 py-2 rounded-[var(--radius)]">
            {scheduled.message}. Daily report will be sent at {scheduled.time}.
          </p>
        )}

        <div className="mt-8 pt-6 border-t border-[var(--border)]">
          <span className="inline-block text-xs font-semibold uppercase tracking-wider text-[var(--primary)] mb-2">Active subscribers</span>
          {loadingSubscribers ? (
            <p className="text-sm text-[var(--text-muted)]">Loading subscribers...</p>
          ) : subscribers.length === 0 ? (
            <p className="text-sm text-[var(--text-muted)]">No subscribers yet.</p>
          ) : (
            <ul className="space-y-1.5">
              {subscribers.map((s) => (
                <li key={s.id} className="text-sm text-[var(--text-secondary)]">
                  {s.name} — {s.email}
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}
