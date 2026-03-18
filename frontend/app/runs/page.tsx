"use client";

import { useState, useMemo, useEffect } from "react";
import type { CSSProperties } from "react";
import { useSearchParams } from "next/navigation";
import BackButton from "../components/BackButton";
import { useToast } from "../context/ToastContext";
import { api } from "@/lib/api";
import type { Run, AgentId } from "@/lib/types";

type SortKey = "id" | "date" | "status" | "period" | "url" | "recipients";
type SortDir = "asc" | "desc";

const AGENT_LABELS: Record<AgentId, string> = {
  competitor: "Competitor releases",
  foundation: "Foundation model provider releases",
  research: "Latest research publications",
  huggingface: "Hugging Face benchmarking results",
};

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

function visibleRecipients(emails: string[]): string[] {
  return (emails || []).filter((e) => !isDummyEmail(e));
}

function formatRunDate(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}
function formatRunTime(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
}

function statusBadgeStyle(status: Run["status"]): CSSProperties {
  if (status === "completed") return { background: "var(--status-success-bg)", color: "var(--status-success-text)" };
  if (status === "running") return { background: "var(--status-running-bg)", color: "var(--status-running-text)" };
  return { background: "var(--status-failed-bg)", color: "var(--status-failed-text)" };
}
function StatusBadge({ status }: { readonly status: Run["status"] }) {
  return (
    <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium" style={statusBadgeStyle(status)}>
      {status}
    </span>
  );
}

function isDateInRange(startedAt: string, start?: string, end?: string): boolean {
  if (!start && !end) return true;
  const d = startedAt.slice(0, 10);
  if (start && d < start) return false;
  if (end && d > end) return false;
  return true;
}

function SortIcon({ sortDir, active }: { readonly sortDir: SortDir | null; readonly active: boolean }) {
  const mutedClass = "text-[var(--text-muted)]";
  const primaryClass = "text-[var(--text-secondary)]";
  if (!active || sortDir === null) {
    return (
      <span className={`inline-flex flex-col ml-1 ${mutedClass}`} aria-hidden>
        <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M18 15l-6-6-6 6" /></svg>
        <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="-mt-1"><path d="M6 9l6 6 6-6" /></svg>
      </span>
    );
  }
  return sortDir === "asc" ? (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className={`ml-1 ${primaryClass}`} aria-hidden><path d="M18 15l-6-6-6 6" /></svg>
  ) : (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className={`ml-1 ${primaryClass}`} aria-hidden><path d="M6 9l6 6 6-6" /></svg>
  );
}

export default function RunsPage() {
  const searchParams = useSearchParams();
  const { pushToast } = useToast();
  const [runs, setRuns] = useState<Run[]>([]);
  const [loading, setLoading] = useState(true);
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [viewRun, setViewRun] = useState<Run | null>(null);
  const [sortBy, setSortBy] = useState<SortKey>("date");
  const [sortDir, setSortDir] = useState<SortDir>("desc");

  useEffect(() => {
    let active = true;
    const fetchRuns = async () => {
      const res = await api.getRuns({ start_date: startDate || undefined, end_date: endDate || undefined });
      if (!active) return;
      if (res.data) setRuns(res.data);
      setLoading(false);
    };
    setLoading(true);
    fetchRuns();
    const interval = globalThis.setInterval(fetchRuns, 30000);
    return () => {
      active = false;
      globalThis.clearInterval(interval);
    };
  }, [startDate, endDate]);

  useEffect(() => {
    const highlight = searchParams.get("highlight");
    if (highlight) pushToast(`Run ${highlight} created. Monitoring live status...`, "success");
  }, [searchParams, pushToast]);

  useEffect(() => {
    if (!viewRun) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setViewRun(null); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [viewRun]);

  const filteredRuns = useMemo(() => {
    return runs.filter((run) => isDateInRange(run.started_at, startDate || undefined, endDate || undefined));
  }, [runs, startDate, endDate]);

  const sortedRuns = useMemo(() => {
    const list = [...filteredRuns];
    list.sort((a, b) => {
      let cmp = 0;
      if (sortBy === "id") cmp = a.id.localeCompare(b.id);
      else if (sortBy === "date") cmp = a.started_at.localeCompare(b.started_at);
      else if (sortBy === "status") cmp = a.status.localeCompare(b.status);
      else if (sortBy === "period") cmp = (a.period ?? "daily").localeCompare(b.period ?? "daily");
      else if (sortBy === "url") cmp = (a.source_url ?? "").localeCompare(b.source_url ?? "");
      else if (sortBy === "recipients") cmp = visibleRecipients(a.recipient_emails).length - visibleRecipients(b.recipient_emails).length;
      return sortDir === "asc" ? cmp : -cmp;
    });
    return list;
  }, [filteredRuns, sortBy, sortDir]);

  const handleSort = (key: SortKey) => {
    if (sortBy === key) setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else { setSortBy(key); setSortDir("asc"); }
  };

  const handleExportPdf = (run: Run) => {
    if (run.status === "completed") {
      globalThis.window.open(`/api/digests/${run.id}/pdf`, "_blank");
    }
  };

  return (
    <div className="min-h-full min-w-0 max-w-full py-4">
        <div className="flex items-center gap-4 mb-2">
          <BackButton href="/" label="Back" />
          <h1 className="text-2xl font-semibold text-[var(--text-primary)]">Runs</h1>
        </div>
        <p className="text-sm text-[var(--text-secondary)] mb-6" title="Filter and sort your past report runs.">History of executed runs. Filter by date and export or view details.</p>

        {/* Filters */}
        <div className="bg-[var(--bg-card)] rounded-[var(--radius)] border border-[var(--border)] p-4 mb-6" style={{ boxShadow: "var(--shadow-card)" }}>
          <p className="text-xs font-semibold uppercase tracking-wider text-[var(--text-secondary)] mb-3">Filter by date</p>
          <div className="flex flex-wrap items-end gap-4">
            <div>
              <label htmlFor="start-date" className="block text-xs font-medium text-[var(--text-secondary)] mb-1">Start date</label>
              <input
                id="start-date"
                type="date"
                value={startDate}
                onChange={(e) => setStartDate(e.target.value)}
                title="Show runs from this date"
                className="rounded-[var(--radius)] border border-[var(--border)] px-3 py-2 text-sm text-[var(--text-primary)] focus:border-[var(--primary)] focus:outline-none focus:ring-1 focus:ring-[var(--primary)]"
              />
            </div>
            <div>
              <label htmlFor="end-date" className="block text-xs font-medium text-[var(--text-secondary)] mb-1">End date</label>
              <input
                id="end-date"
                type="date"
                value={endDate}
                onChange={(e) => setEndDate(e.target.value)}
                title="Show runs until this date"
                className="rounded-[var(--radius)] border border-[var(--border)] px-3 py-2 text-sm text-[var(--text-primary)] focus:border-[var(--primary)] focus:outline-none focus:ring-1 focus:ring-[var(--primary)]"
              />
            </div>
            <button
              type="button"
              onClick={() => { setStartDate(""); setEndDate(""); }}
              title="Reset date filters"
              className="px-3 py-2 text-sm font-medium text-[var(--text-secondary)] hover:text-[var(--primary)] hover:bg-[var(--primary-light)] rounded-[var(--radius)] transition-colors cursor-pointer"
            >
              Clear filters
            </button>
          </div>
        </div>

        {/* Table */}
        {loading ? (
          <p className="text-sm text-[var(--text-muted)] py-4">Loading runs…</p>
        ) : (
        <div className="bg-[var(--bg-card)] rounded-[var(--radius)] border border-[var(--border)] overflow-hidden min-w-0" style={{ boxShadow: "var(--shadow-card)" }}>
          <div className="overflow-x-auto overflow-y-visible">
            <table className="w-full min-w-[700px] border-collapse">
              <thead>
                <tr className="bg-[var(--primary-light)]/30 border-b-2 border-[var(--border)]">
                  <th className="text-left py-3.5 px-4 text-xs font-semibold uppercase tracking-wider text-[var(--text-secondary)] border-r border-[var(--border)] last:border-r-0">
                    <button type="button" onClick={() => handleSort("id")} title="Sort by run ID" className="inline-flex items-center cursor-pointer hover:text-[var(--primary)] transition-colors">
                      Run ID
                      <SortIcon sortDir={sortBy === "id" ? sortDir : null} active={sortBy === "id"} />
                    </button>
                  </th>
                  <th className="text-left py-3.5 px-4 text-xs font-semibold uppercase tracking-wider text-[var(--text-secondary)] border-r border-[var(--border)] last:border-r-0">
                    <button type="button" onClick={() => handleSort("date")} title="Sort by date and time" className="inline-flex items-center cursor-pointer hover:text-[var(--primary)] transition-colors">
                      Date & time
                      <SortIcon sortDir={sortBy === "date" ? sortDir : null} active={sortBy === "date"} />
                    </button>
                  </th>
                  <th className="text-left py-3.5 px-4 text-xs font-semibold uppercase tracking-wider text-[var(--text-secondary)] border-r border-[var(--border)] last:border-r-0">
                    <button type="button" onClick={() => handleSort("status")} title="Sort by status" className="inline-flex items-center cursor-pointer hover:text-[var(--primary)] transition-colors">
                      Status
                      <SortIcon sortDir={sortBy === "status" ? sortDir : null} active={sortBy === "status"} />
                    </button>
                  </th>
                  <th className="text-left py-3.5 px-4 text-xs font-semibold uppercase tracking-wider text-[var(--text-secondary)] border-r border-[var(--border)] last:border-r-0">
                    <button type="button" onClick={() => handleSort("period")} title="Sort by period" className="inline-flex items-center cursor-pointer hover:text-[var(--primary)] transition-colors">
                      Period
                      <SortIcon sortDir={sortBy === "period" ? sortDir : null} active={sortBy === "period"} />
                    </button>
                  </th>
                  <th className="text-left py-3.5 px-4 text-xs font-semibold uppercase tracking-wider text-[var(--text-secondary)] border-r border-[var(--border)] last:border-r-0">
                    <button type="button" onClick={() => handleSort("url")} title="Sort by URL" className="inline-flex items-center cursor-pointer hover:text-[var(--primary)] transition-colors">
                      URL
                      <SortIcon sortDir={sortBy === "url" ? sortDir : null} active={sortBy === "url"} />
                    </button>
                  </th>
                  <th className="text-left py-3.5 px-4 text-xs font-semibold uppercase tracking-wider text-[var(--text-secondary)] border-r border-[var(--border)] last:border-r-0">
                    <button type="button" onClick={() => handleSort("recipients")} title="Sort by recipient count" className="inline-flex items-center cursor-pointer hover:text-[var(--primary)] transition-colors">
                      Recipients
                      <SortIcon sortDir={sortBy === "recipients" ? sortDir : null} active={sortBy === "recipients"} />
                    </button>
                  </th>
                  <th className="text-left py-3.5 px-4 text-xs font-semibold uppercase tracking-wider text-[var(--text-secondary)] border-r border-[var(--border)]" title="View agents used in this run">View</th>
                  <th className="text-left py-3.5 px-4 text-xs font-semibold uppercase tracking-wider text-[var(--text-secondary)]" title="Export PDF for this run">Export PDF</th>
                </tr>
              </thead>
              <tbody>
                {sortedRuns.length === 0 ? (
                  <tr>
                    <td colSpan={8} className="py-12 text-center text-sm text-[var(--text-secondary)] border-b border-[var(--border)]">
                      No runs found for the selected date range.
                    </td>
                  </tr>
                ) : (
                  sortedRuns.map((run, index) => (
                    <tr
                      key={run.id}
                      className={`border-b border-[var(--border)] hover:bg-[var(--primary-light)]/20 transition-colors ${index % 2 === 1 ? "bg-[var(--bg)]" : "bg-[var(--bg-card)]"}`}
                    >
                      <td className="py-3.5 px-4 text-sm font-medium text-[var(--text-primary)] border-r border-[var(--border)]">{run.id}</td>
                      <td className="py-3.5 px-4 text-sm text-[var(--text-secondary)] border-r border-[var(--border)]">{formatRunDate(run.started_at)} · {formatRunTime(run.started_at)}</td>
                      <td className="py-3.5 px-4 border-r border-[var(--border)]">
                        <StatusBadge status={run.status} />
                      </td>
                      <td className="py-3.5 px-4 border-r border-[var(--border)]">
                        <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium capitalize" style={{ background: "var(--primary-light)", color: "var(--primary)" }}>
                          {run.period ?? "daily"}
                        </span>
                      </td>
                      <td className="py-3.5 px-4 text-sm text-[var(--text-secondary)] truncate max-w-[140px] border-r border-[var(--border)]" title={run.source_url ?? ""}>{run.source_url ?? run.mode ?? "—"}</td>
                      <td className="py-3.5 px-4 text-sm text-[var(--text-secondary)] border-r border-[var(--border)]">{visibleRecipients(run.recipient_emails).length} email{visibleRecipients(run.recipient_emails).length === 1 ? "" : "s"}</td>
                      <td className="py-3.5 px-4 border-r border-[var(--border)]">
                        <button
                          type="button"
                          onClick={() => setViewRun(run)}
                          title="See which agents were used"
                          className="text-sm font-medium text-[var(--primary)] hover:underline transition-colors cursor-pointer no-underline"
                        >
                          View agents
                        </button>
                      </td>
                      <td className="py-3.5 px-4">
                        <button
                          type="button"
                          onClick={() => handleExportPdf(run)}
                          disabled={run.status === "failed" || run.status === "running"}
                          title={run.status === "completed" ? "Export PDF for this run" : "Export available when run is completed"}
                          className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-[var(--radius)] text-sm font-medium bg-[var(--primary)] text-white hover:bg-[var(--primary-hover)] disabled:opacity-50 disabled:cursor-not-allowed transition-colors cursor-pointer"
                        >
                          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                            <polyline points="7 10 12 15 17 10" />
                            <line x1="12" y1="15" x2="12" y2="3" />
                          </svg>
                          Export
                        </button>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
        )}

        {sortedRuns.length > 0 && (
          <p className="mt-3 text-xs text-[var(--text-secondary)]">
            Showing {sortedRuns.length} run{sortedRuns.length === 1 ? "" : "s"}
          </p>
        )}

      {/* View Run modal — agents used for this run */}
      {viewRun && (
        <div
          role="dialog"
          aria-modal="true"
          aria-labelledby="run-detail-title"
          className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50"
        >
          <button
            type="button"
            className="absolute inset-0 cursor-pointer"
            onClick={() => setViewRun(null)}
            aria-label="Close modal"
          />
          <div
            role="document"
            className="relative bg-[var(--bg-card)] rounded-[var(--radius)] border border-[var(--border)] w-full max-w-md overflow-hidden"
            style={{ boxShadow: "var(--shadow-card)" }}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="px-5 py-4 border-b border-[var(--border)] flex items-center justify-between">
              <h3 id="run-detail-title" className="text-lg font-semibold text-[var(--text-primary)]">Run details · {viewRun.id}</h3>
              <button
                type="button"
                onClick={() => setViewRun(null)}
                className="p-1 rounded-[var(--radius)] text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--primary-light)] cursor-pointer"
                aria-label="Close"
                title="Close"
              >
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <line x1="18" y1="6" x2="6" y2="18" />
                  <line x1="6" y1="6" x2="18" y2="18" />
                </svg>
              </button>
            </div>
            <div className="px-5 py-4 space-y-4">
              <div>
                <p className="text-xs font-semibold uppercase tracking-wider text-[var(--text-secondary)] mb-1">URL</p>
                <p className="text-sm text-[var(--text-primary)]">{viewRun.source_url ?? "—"}</p>
              </div>
              <div>
                <p className="text-xs font-semibold uppercase tracking-wider text-[var(--text-secondary)] mb-1">Recipients</p>
                <p className="text-sm text-[var(--text-secondary)]">{visibleRecipients(viewRun.recipient_emails).length ? visibleRecipients(viewRun.recipient_emails).join(", ") : "—"}</p>
              </div>
              <div>
                <p className="text-xs font-semibold uppercase tracking-wider text-[var(--text-secondary)] mb-2">Agents used in this run</p>
                <ul className="space-y-1.5">
                  {viewRun.agent_ids.map((id) => (
                    <li key={id} className="text-sm text-[var(--text-primary)] flex items-center gap-2">
                      <span className="w-1.5 h-1.5 rounded-full bg-[var(--primary)]" />
                      {AGENT_LABELS[id]}
                    </li>
                  ))}
                </ul>
                {viewRun.agent_statuses && viewRun.agent_statuses.length > 0 && (
                  <div className="pt-3">
                    <p className="text-xs font-semibold uppercase tracking-wider text-[var(--text-secondary)] mb-2">Agent runtime status</p>
                    <ul className="space-y-1">
                      {viewRun.agent_statuses.map((s) => (
                        <li key={s.agent} className="text-xs text-[var(--text-secondary)]">
                          <div className="flex items-center justify-between">
                            <span>{s.label}</span>
                            <span>{s.status} · {s.findings_count} findings</span>
                          </div>
                          {(s as any).error && (
                            <p className="text-red-400 text-[11px] mt-0.5 pl-2 border-l-2 border-red-400/30">
                              {(s as any).error}
                            </p>
                          )}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                {/* Agent Errors (from agent_errors field) */}
                {viewRun.agent_errors && viewRun.agent_errors.length > 0 && (
                  <div className="pt-3">
                    <p className="text-xs font-semibold uppercase tracking-wider text-red-400 mb-2">Agent Errors</p>
                    <ul className="space-y-1">
                      {viewRun.agent_errors.map((err, idx) => (
                        <li key={idx} className="text-xs text-red-400 flex items-start gap-2">
                          <span className="font-medium shrink-0">{AGENT_LABELS[err.agent_id] ?? err.agent_id}:</span>
                          <span className="text-red-300">{err.message}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            </div>
            <div className="px-5 py-4 border-t border-[var(--border)] flex justify-end">
              <button
                type="button"
                onClick={() => handleExportPdf(viewRun)}
                disabled={viewRun.status === "failed" || viewRun.status === "running"}
                title="Export PDF for this run"
                className="inline-flex items-center gap-2 px-4 py-2 rounded-[var(--radius)] text-sm font-medium bg-[var(--primary)] text-white hover:bg-[var(--primary-hover)] disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer"
              >
                Export PDF for this run
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
