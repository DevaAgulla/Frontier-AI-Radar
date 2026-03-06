"use client";

import { useEffect, useState } from "react";
import BackButton from "../components/BackButton";
import { api } from "@/lib/api";
import { useToast } from "../context/ToastContext";
import type { Source } from "@/lib/types";
import type { AgentId } from "@/lib/types";

const AGENT_LABELS: Record<AgentId, string> = {
  competitor: "Competitor",
  foundation: "Foundation",
  research: "Research",
  huggingface: "Hugging Face",
};

export default function SourcesPage() {
  const { pushToast } = useToast();
  const [sources, setSources] = useState<Source[]>([]);
  const [loading, setLoading] = useState(true);
  const [newUrl, setNewUrl] = useState("");
  const [newAgent, setNewAgent] = useState<AgentId>("competitor");
  const [newSourceType, setNewSourceType] = useState<"rss" | "webpage">("webpage");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    api.getSources().then((res) => {
      if (res.data) setSources(res.data);
      setLoading(false);
    });
  }, []);

  const handleAdd = async () => {
    const url = newUrl.trim();
    if (!url) return;
    setSubmitting(true);
    const res = await api.createSource({ url, agent_id: newAgent, source_type: newSourceType });
    setSubmitting(false);
    if (res.data) {
      setSources((prev) => [res.data!, ...prev]);
      setNewUrl("");
      pushToast("Source added successfully", "success");
    } else if (res.error) {
      pushToast(res.error, "error");
    }
  };

  return (
    <div className="min-h-full min-w-0 max-w-full py-4">
        <div className="flex items-center gap-4 mb-2">
          <BackButton href="/" label="Back" />
          <h1 className="text-2xl font-semibold text-[var(--text-primary)]">Sources</h1>
        </div>
        <p className="text-sm text-[var(--text-secondary)] mb-6">
          Manage URLs per agent. Add sources for crawlers to track.
        </p>

        <div className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--bg-card)] p-4 mb-6" style={{ boxShadow: "var(--shadow-card)" }}>
          <h2 className="text-sm font-semibold text-[var(--text-primary)] mb-3">Add source</h2>
          <div className="flex flex-wrap gap-3">
            <input
              type="url"
              value={newUrl}
              onChange={(e) => setNewUrl(e.target.value)}
              placeholder="https://example.com/blog"
              className="flex-1 min-w-[200px] rounded-[var(--radius)] border border-[var(--border)] px-3 py-2 text-sm text-[var(--text-primary)] focus:border-[var(--primary)] focus:outline-none focus:ring-1 focus:ring-[var(--primary)]"
            />
            <select
              value={newAgent}
              onChange={(e) => setNewAgent(e.target.value as AgentId)}
              className="rounded-[var(--radius)] border border-[var(--border)] px-3 py-2 text-sm text-[var(--text-primary)] focus:border-[var(--primary)] focus:outline-none"
            >
              <option value="competitor">{AGENT_LABELS.competitor}</option>
            </select>
            <button
              type="button"
              onClick={handleAdd}
              disabled={submitting || !newUrl.trim()}
              className="px-4 py-2 rounded-[var(--radius)] text-sm font-medium bg-[var(--primary)] text-white hover:bg-[var(--primary-hover)] disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {submitting ? "Adding…" : "Add"}
            </button>
            <select
              value={newSourceType}
              onChange={(e) => setNewSourceType(e.target.value as "rss" | "webpage")}
              className="rounded-[var(--radius)] border border-[var(--border)] px-3 py-2 text-sm text-[var(--text-primary)] focus:border-[var(--primary)] focus:outline-none"
            >
              <option value="webpage">webpage</option>
              <option value="rss">rss</option>
            </select>
          </div>
        <p className="mt-2 text-xs text-[var(--text-muted)]">
          Note: competitor sources are DB-configurable. Other agents currently use default wrapped sources.
        </p>
        </div>

        <h2 className="text-sm font-semibold text-[var(--text-secondary)] mb-2">Configured sources</h2>
        {loading ? (
          <p className="text-sm text-[var(--text-muted)]">Loading…</p>
        ) : sources.length === 0 ? (
          <p className="text-sm text-[var(--text-muted)]">No sources yet. Add one above.</p>
        ) : (
          <ul className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--bg-card)] divide-y divide-[var(--border)] overflow-hidden" style={{ boxShadow: "var(--shadow-card)" }}>
            {sources.map((s) => (
              <li key={s.id} className="flex items-center justify-between gap-4 px-4 py-3">
                <div className="min-w-0 flex-1">
                  <a href={s.url} target="_blank" rel="noopener noreferrer" className="text-sm font-medium text-[var(--primary)] hover:underline truncate block">{s.url}</a>
                  <span className="text-xs text-[var(--text-muted)]">{AGENT_LABELS[s.agent_id]} {s.label ? `· ${s.label}` : ""}</span>
                </div>
                <span className="text-xs text-[var(--text-muted)] shrink-0">{s.source_type || s.agent_id}</span>
                {/* Toggle active/inactive */}
                <button
                  type="button"
                  title={s.is_active === false ? "Enable source" : "Disable source"}
                  onClick={async () => {
                    const next = s.is_active === false;
                    const res = await api.toggleSource(s.id, next);
                    if (res.data) {
                      setSources((prev) =>
                        prev.map((x) => (x.id === s.id ? { ...x, is_active: next } : x))
                      );
                      pushToast(next ? "Source enabled" : "Source disabled", "success");
                    } else if (res.error) {
                      pushToast(res.error, "error");
                    }
                  }}
                  className={`shrink-0 w-10 h-5 rounded-full relative transition-colors ${
                    s.is_active === false
                      ? "bg-[var(--border)]"
                      : "bg-[var(--primary)]"
                  }`}
                >
                  <span
                    className={`absolute top-0.5 w-4 h-4 rounded-full bg-white transition-transform ${
                      s.is_active === false ? "left-0.5" : "left-5"
                    }`}
                  />
                </button>
                {/* Delete (user-added only) */}
                {s.is_default !== true && (
                  <button
                    type="button"
                    title="Delete source"
                    onClick={async () => {
                      if (!confirm("Remove this source?")) return;
                      const res = await api.deleteSource(s.id);
                      if (res.data) {
                        setSources((prev) => prev.filter((x) => x.id !== s.id));
                        pushToast("Source deleted", "success");
                      } else if (res.error) {
                        pushToast(res.error, "error");
                      }
                    }}
                    className="shrink-0 text-red-400 hover:text-red-300 transition-colors"
                  >
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <polyline points="3 6 5 6 21 6" />
                      <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                    </svg>
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
    </div>
  );
}
