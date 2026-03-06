"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import type { Finding } from "@/lib/types";

interface LastRun {
  run_id: number;
  status: string;
  started_at: string | null;
  finished_at: string | null;
  time_taken: number | null;
}

function statusColor(status: string) {
  if (status === "completed") return "bg-green-500/15 text-green-400 border-green-500/30";
  if (status === "running") return "bg-yellow-500/15 text-yellow-400 border-yellow-500/30";
  return "bg-red-500/15 text-red-400 border-red-500/30";
}

export default function DashboardPage() {
  const [topFindings, setTopFindings] = useState<Finding[]>([]);
  const [lastRun, setLastRun] = useState<LastRun | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.getDashboard().then((res) => {
      if (res.data) {
        setTopFindings(res.data.top_findings ?? []);
        setLastRun(res.data.last_run ?? null);
      }
      setLoading(false);
    });
  }, []);

  return (
    <div className="min-h-full min-w-0 max-w-full py-4">
        <h1 className="text-2xl font-semibold text-[var(--text-primary)] mb-2">Dashboard</h1>
        <p className="text-sm text-[var(--text-secondary)] mb-6">
          Daily multi-agent intelligence. Top updates and quick actions.
        </p>

        {loading ? (
          <div className="flex items-center justify-center py-12">
            <span className="text-sm text-[var(--text-muted)]">Loading…</span>
          </div>
        ) : (
          <>
            {/* Quick actions: Build Report + Download PDF */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-8 max-w-5xl">
              <Link
                href="/run"
                className="rounded-[var(--radius)] border border-[var(--border)] p-5 flex items-center gap-4 bg-[var(--bg-card)] hover:border-[var(--primary)] hover:shadow-[var(--shadow-card)] transition-all"
                style={{ boxShadow: "var(--shadow-card)" }}
              >
                <div className="w-12 h-12 rounded-[var(--radius)] bg-[var(--primary-light)] border border-[var(--border-purple)] flex items-center justify-center shrink-0">
                  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="var(--primary)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <rect x="3" y="3" width="7" height="7" />
                    <rect x="14" y="3" width="7" height="7" />
                    <rect x="14" y="14" width="7" height="7" />
                    <rect x="3" y="14" width="7" height="7" />
                  </svg>
                </div>
                <div className="min-w-0">
                  <h2 className="text-base font-semibold text-[var(--text-primary)]">Build Report</h2>
                  <p className="text-sm text-[var(--text-secondary)]">Drag agents into the pipeline, then run to generate the digest.</p>
                </div>
                <span className="shrink-0 text-[var(--primary)]" aria-hidden>→</span>
              </Link>
              <Link
                href="/archive"
                className="rounded-[var(--radius)] border border-[var(--border)] p-5 flex items-center gap-4 bg-[var(--bg-card)] hover:border-[var(--primary)] transition-all"
                style={{ boxShadow: "var(--shadow-card)" }}
              >
                <div className="w-12 h-12 rounded-[var(--radius)] bg-[var(--primary-light)] border border-[var(--border-purple)] flex items-center justify-center shrink-0">
                  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="var(--primary)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                    <polyline points="7 10 12 15 17 10" />
                    <line x1="12" y1="15" x2="12" y2="3" />
                  </svg>
                </div>
                <div className="min-w-0">
                  <h2 className="text-base font-semibold text-[var(--text-primary)]">Download PDF</h2>
                  <p className="text-sm text-[var(--text-secondary)]">Browse and download past digest PDFs.</p>
                </div>
              </Link>
            </div>

            {/* Last Run Status Card */}
            {lastRun && (
              <div className="mb-6 max-w-5xl">
                <div
                  className="rounded-[var(--radius)] border border-[var(--border)] p-4 bg-[var(--bg-card)] flex flex-wrap items-center gap-4"
                  style={{ boxShadow: "var(--shadow-card)" }}
                >
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-medium text-[var(--text-secondary)] uppercase tracking-wider">Last Run</span>
                    <span className={`text-xs font-semibold px-2 py-0.5 rounded border ${statusColor(lastRun.status)}`}>
                      {lastRun.status}
                    </span>
                  </div>
                  <span className="text-xs text-[var(--text-muted)]">
                    Run #{lastRun.run_id}
                  </span>
                  {lastRun.started_at && (
                    <span className="text-xs text-[var(--text-muted)]">
                      Started: {new Date(lastRun.started_at).toLocaleString()}
                    </span>
                  )}
                  {lastRun.time_taken != null && (
                    <span className="text-xs text-[var(--text-muted)]">
                      Duration: {lastRun.time_taken}s
                    </span>
                  )}
                  <Link
                    href="/runs"
                    className="ml-auto text-xs text-[var(--primary)] hover:underline"
                  >
                    View all runs →
                  </Link>
                </div>
              </div>
            )}

            {/* Top 10 updates */}
            <section>
              <h2 className="text-sm font-semibold uppercase tracking-wider text-[var(--text-secondary)] mb-3">Top updates today</h2>
              {topFindings.length === 0 ? (
                <p className="text-sm text-[var(--text-muted)]">No findings yet. Run a report to populate.</p>
              ) : (
                <ul className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--bg-card)] divide-y divide-[var(--border)] overflow-hidden" style={{ boxShadow: "var(--shadow-card)" }}>
                  {topFindings.slice(0, 10).map((f, idx) => (
                    <li key={`${f.id}-${f.agent_id}-${f.source_url || "na"}-${idx}`} className="p-4 hover:bg-[var(--primary-light)]/20 transition-colors">
                      <div className="flex justify-between gap-2">
                        <span className="font-medium text-[var(--text-primary)]">{f.title}</span>
                        <span className="text-xs text-[var(--text-muted)] shrink-0">{f.date_detected}</span>
                      </div>
                      <p className="text-sm text-[var(--text-secondary)] mt-0.5">{f.summary_short}</p>
                      <div className="flex gap-2 mt-1.5 flex-wrap">
                        <span className="text-xs px-2 py-0.5 rounded bg-[var(--primary-light)] text-[var(--primary)]">{f.agent_id}</span>
                        {f.entities.slice(0, 2).map((e) => (
                          <span key={e} className="text-xs text-[var(--text-muted)]">{e}</span>
                        ))}
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </>
        )}
    </div>
  );
}
