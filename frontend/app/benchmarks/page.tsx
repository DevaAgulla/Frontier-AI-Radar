"use client";

import { useEffect, useState } from "react";
import BackButton from "../components/BackButton";
import { api } from "@/lib/api";
import type { Finding } from "@/lib/types";

export default function BenchmarksPage() {
  const [findings, setFindings] = useState<Finding[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .getFindings({ agent_id: "huggingface", limit: 50 })
      .then((res) => {
        if (res.data) setFindings(res.data);
        setLoading(false);
      });
  }, []);

  return (
    <div className="min-h-full min-w-0 max-w-full py-4">
      <div className="flex items-center gap-4 mb-2">
        <BackButton href="/" />
        <h1 className="text-2xl font-semibold text-[var(--text-primary)]">
          Benchmarks
        </h1>
      </div>
      <p className="text-sm text-[var(--text-secondary)] mb-6">
        HuggingFace benchmark findings — model evaluations, leaderboard changes, and performance data.
      </p>

      {loading ? (
        <p className="text-sm text-[var(--text-muted)]">Loading benchmark data…</p>
      ) : findings.length === 0 ? (
        <p className="text-sm text-[var(--text-muted)]">
          No benchmark findings yet. Run a report with the Benchmark agent enabled.
        </p>
      ) : (
        <div
          className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--bg-card)] overflow-hidden"
          style={{ boxShadow: "var(--shadow-card)" }}
        >
          <div className="overflow-x-auto">
            <table className="w-full min-w-[700px] border-collapse">
              <thead>
                <tr className="bg-[var(--primary-light)]/30 border-b-2 border-[var(--border)]">
                  <th className="text-left py-3 px-4 text-xs font-semibold uppercase tracking-wider text-[var(--text-secondary)]">
                    Title
                  </th>
                  <th className="text-left py-3 px-4 text-xs font-semibold uppercase tracking-wider text-[var(--text-secondary)]">
                    Category
                  </th>
                  <th className="text-left py-3 px-4 text-xs font-semibold uppercase tracking-wider text-[var(--text-secondary)]">
                    Impact
                  </th>
                  <th className="text-left py-3 px-4 text-xs font-semibold uppercase tracking-wider text-[var(--text-secondary)]">
                    Date
                  </th>
                  <th className="text-left py-3 px-4 text-xs font-semibold uppercase tracking-wider text-[var(--text-secondary)]">
                    Source
                  </th>
                </tr>
              </thead>
              <tbody>
                {findings.map((f, i) => (
                  <tr
                    key={`${f.id}-${i}`}
                    className={`border-b border-[var(--border)] hover:bg-[var(--primary-light)]/20 ${
                      i % 2 === 1 ? "bg-[var(--bg)]" : ""
                    }`}
                  >
                    <td className="py-3 px-4">
                      <span className="text-sm font-medium text-[var(--text-primary)] line-clamp-2">
                        {f.title}
                      </span>
                      <p className="text-xs text-[var(--text-muted)] mt-0.5 line-clamp-1">
                        {f.summary_short}
                      </p>
                    </td>
                    <td className="py-3 px-4">
                      <span className="text-xs px-2 py-0.5 rounded bg-[var(--primary-light)] text-[var(--primary)]">
                        {f.category}
                      </span>
                    </td>
                    <td className="py-3 px-4 text-sm">
                      {f.impact_score != null
                        ? (f.impact_score * 100).toFixed(0) + "%"
                        : "—"}
                    </td>
                    <td className="py-3 px-4 text-sm text-[var(--text-secondary)]">
                      {f.date_detected}
                    </td>
                    <td className="py-3 px-4">
                      {f.source_url ? (
                        <a
                          href={f.source_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-xs text-[var(--primary)] hover:underline truncate block max-w-[180px]"
                        >
                          {new URL(f.source_url).hostname}
                        </a>
                      ) : (
                        <span className="text-xs text-[var(--text-muted)]">—</span>
                      )}
                    </td>
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
