"use client";

import { useEffect, useState } from "react";
import BackButton from "../components/BackButton";
import { api } from "@/lib/api";
import type { Finding } from "@/lib/types";
import type { AgentId } from "@/lib/types";

const AGENT_LABELS: Record<AgentId, string> = {
  competitor: "Competitor",
  foundation: "Foundation",
  research: "Research",
  huggingface: "Hugging Face",
};

const CATEGORY_OPTIONS = [
  { value: "", label: "All categories" },
  { value: "release", label: "Release" },
  { value: "research", label: "Research" },
  { value: "benchmark", label: "Benchmark" },
  { value: "api", label: "API" },
  { value: "pricing", label: "Pricing" },
  { value: "safety", label: "Safety" },
];

export default function FindingsPage() {
  const [findings, setFindings] = useState<Finding[]>([]);
  const [loading, setLoading] = useState(true);
  const [agentFilter, setAgentFilter] = useState<AgentId | "">("");
  const [entityFilter, setEntityFilter] = useState("");
  const [categoryFilter, setCategoryFilter] = useState("");

  useEffect(() => {
    setLoading(true);
    api.getFindings({
      agent_id: agentFilter || undefined,
      entity: entityFilter.trim() || undefined,
      category: categoryFilter || undefined,
      limit: 50,
    }).then((res) => {
      if (res.data) setFindings(res.data);
      setLoading(false);
    });
  }, [agentFilter, entityFilter, categoryFilter]);

  return (
    <div className="min-h-full min-w-0 max-w-full py-4">
        <div className="flex items-center gap-4 mb-2">
          <BackButton href="/" label="Back" />
          <h1 className="text-2xl font-semibold text-[var(--text-primary)]">Findings</h1>
        </div>
        <p className="text-sm text-[var(--text-secondary)] mb-6">
          Explore findings by agent, entity, or category. Filter and browse.
        </p>

        <div className="flex flex-wrap gap-3 mb-6">
          <select
            value={agentFilter}
            onChange={(e) => setAgentFilter(e.target.value as AgentId | "")}
            className="rounded-[var(--radius)] border border-[var(--border)] px-3 py-2 text-sm text-[var(--text-primary)] focus:border-[var(--primary)] focus:outline-none"
          >
            <option value="">All agents</option>
            {(Object.keys(AGENT_LABELS) as AgentId[]).map((id) => (
              <option key={id} value={id}>{AGENT_LABELS[id]}</option>
            ))}
          </select>
          <input
            type="text"
            value={entityFilter}
            onChange={(e) => setEntityFilter(e.target.value)}
            placeholder="Filter by entity or publisher"
            className="rounded-[var(--radius)] border border-[var(--border)] px-3 py-2 text-sm text-[var(--text-primary)] min-w-[200px] focus:border-[var(--primary)] focus:outline-none"
          />
          <select
            value={categoryFilter}
            onChange={(e) => setCategoryFilter(e.target.value)}
            className="rounded-[var(--radius)] border border-[var(--border)] px-3 py-2 text-sm text-[var(--text-primary)] focus:border-[var(--primary)] focus:outline-none"
          >
            {CATEGORY_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>{opt.label}</option>
            ))}
          </select>
        </div>

        {loading ? (
          <p className="text-sm text-[var(--text-muted)]">Loading…</p>
        ) : findings.length === 0 ? (
          <p className="text-sm text-[var(--text-muted)]">No findings match the filters.</p>
        ) : (
          <div className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--bg-card)] overflow-hidden" style={{ boxShadow: "var(--shadow-card)" }}>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[700px] border-collapse">
                <thead>
                  <tr className="bg-[var(--primary-light)]/30 border-b-2 border-[var(--border)]">
                    <th className="text-left py-3 px-4 text-xs font-semibold uppercase tracking-wider text-[var(--text-secondary)]">Title</th>
                    <th className="text-left py-3 px-4 text-xs font-semibold uppercase tracking-wider text-[var(--text-secondary)]">Agent</th>
                    <th className="text-left py-3 px-4 text-xs font-semibold uppercase tracking-wider text-[var(--text-secondary)]">Category</th>
                    <th className="text-left py-3 px-4 text-xs font-semibold uppercase tracking-wider text-[var(--text-secondary)]">Date</th>
                    <th className="text-left py-3 px-4 text-xs font-semibold uppercase tracking-wider text-[var(--text-secondary)]">Impact</th>
                  </tr>
                </thead>
                <tbody>
                  {findings.map((f, i) => (
                    <tr key={`${f.id}-${f.agent_id}-${f.source_url || "na"}-${i}`} className={`border-b border-[var(--border)] hover:bg-[var(--primary-light)]/20 ${i % 2 === 1 ? "bg-[var(--bg)]" : ""}`}>
                      <td className="py-3 px-4">
                        <a href={f.source_url} target="_blank" rel="noopener noreferrer" className="text-sm font-medium text-[var(--primary)] hover:underline line-clamp-2">{f.title}</a>
                        <p className="text-xs text-[var(--text-muted)] mt-0.5 line-clamp-1">{f.summary_short}</p>
                      </td>
                      <td className="py-3 px-4 text-sm text-[var(--text-secondary)]">{AGENT_LABELS[f.agent_id]}</td>
                      <td className="py-3 px-4 text-sm text-[var(--text-secondary)]">{f.category}</td>
                      <td className="py-3 px-4 text-sm text-[var(--text-secondary)]">{f.date_detected}</td>
                      <td className="py-3 px-4 text-sm">{f.impact_score != null ? (f.impact_score * 100).toFixed(0) + "%" : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
    </div>
  );
}
