"use client";

import { useEffect, useMemo, useState } from "react";
import BackButton from "../components/BackButton";
import { api } from "@/lib/api";
import { useToast } from "../context/ToastContext";
import type { CompareResult } from "@/lib/types";

function todayISO() {
  return new Date().toISOString().slice(0, 10);
}

function yesterdayISO() {
  const d = new Date();
  d.setDate(d.getDate() - 1);
  return d.toISOString().slice(0, 10);
}

export default function ComparePage() {
  const { pushToast } = useToast();
  const [dateA, setDateA] = useState(yesterdayISO());
  const [dateB, setDateB] = useState(todayISO());
  const [runAId, setRunAId] = useState<number | null>(null);
  const [runBId, setRunBId] = useState<number | null>(null);
  const [loadingCompare, setLoadingCompare] = useState(false);
  const [compare, setCompare] = useState<CompareResult | null>(null);
  const [polling, setPolling] = useState(false);

  useEffect(() => {
    if (!compare || compare.status !== "running") return;
    const interval = globalThis.setInterval(async () => {
      const res = await api.compareRuns({
        date_a: dateA,
        date_b: dateB,
        run_a_id: runAId ?? undefined,
        run_b_id: runBId ?? undefined,
      });
      if (res.data) {
        setCompare(res.data);
        if (typeof (res.data as any).run_a_id === "number") setRunAId((res.data as any).run_a_id);
        if (typeof (res.data as any).run_b_id === "number") setRunBId((res.data as any).run_b_id);
        if (res.data.status === "completed") {
          setPolling(false);
          pushToast("Comparison ready.", "success");
        }
      }
    }, 5000);
    return () => globalThis.clearInterval(interval);
  }, [compare, dateA, dateB, runAId, runBId, pushToast]);

  const runCompare = async () => {
    if (!dateA || !dateB) {
      pushToast("Select both dates.", "error");
      return;
    }
    setRunAId(null);
    setRunBId(null);
    setCompare(null);
    setPolling(true);
    setLoadingCompare(true);
    const res = await api.compareRuns({
      date_a: dateA,
      date_b: dateB,
    });
    setLoadingCompare(false);
    if (res.error) {
      setPolling(false);
      pushToast(res.error, "error");
      return;
    }
    if (res.data) {
      setCompare(res.data);
      if (typeof (res.data as any).run_a_id === "number") setRunAId((res.data as any).run_a_id);
      if (typeof (res.data as any).run_b_id === "number") setRunBId((res.data as any).run_b_id);
      if (res.data.status === "running") {
        pushToast("Compare runs started in parallel. Polling for result...", "info");
      } else {
        setPolling(false);
        pushToast("Comparison generated successfully.", "success");
      }
    }
  };

  const agentDeltas = useMemo(() => compare?.agent_deltas ?? [], [compare]);
  const sectionRows = useMemo(() => compare?.section_comparison ?? [], [compare]);

  return (
    <div className="min-h-full min-w-0 max-w-full py-4">
      <div className="flex items-center gap-4 mb-2">
        <BackButton href="/" label="Back" />
        <h1 className="text-2xl font-semibold text-[var(--text-primary)]">Compare Reports</h1>
      </div>
      <p className="text-sm text-[var(--text-secondary)] mb-6">
        Select two dates and click Compare Report. The system runs all 4 agents for both dates in parallel, then shows highlighted differences below.
      </p>

      <div className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--bg-card)] p-4 mb-5" style={{ boxShadow: "var(--shadow-card)" }}>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 max-w-3xl">
          <div>
            <label className="block text-xs font-semibold text-[var(--text-secondary)] mb-1">Baseline date</label>
            <input type="date" value={dateA} onChange={(e) => setDateA(e.target.value)} className="w-full rounded-[var(--radius)] border border-[var(--border)] px-3 py-2 text-sm" />
          </div>
          <div>
            <label className="block text-xs font-semibold text-[var(--text-secondary)] mb-1">Candidate date</label>
            <input type="date" value={dateB} onChange={(e) => setDateB(e.target.value)} className="w-full rounded-[var(--radius)] border border-[var(--border)] px-3 py-2 text-sm" />
          </div>
        </div>

        <button
          type="button"
          onClick={runCompare}
          disabled={loadingCompare}
          className="mt-4 inline-flex items-center gap-2 px-5 py-2.5 rounded-[var(--radius)] text-sm font-medium bg-[var(--primary)] text-white hover:bg-[var(--primary-hover)] disabled:opacity-60"
        >
          {loadingCompare ? "Preparing..." : "Compare Report"}
        </button>
        {(loadingCompare || polling) && (
          <div className="mt-3 text-sm text-[var(--text-secondary)]">
            <span className="inline-flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-[var(--primary)] animate-pulse" />
              Running both reports in parallel and computing diff...
            </span>
          </div>
        )}
      </div>

      {compare?.status === "running" && (
        <div className="mb-5 rounded-[var(--radius)] border border-[var(--border)] bg-[var(--primary-light)]/40 p-3 text-sm text-[var(--text-primary)]">
          {compare.message || "Comparison runs are in progress. Polling every 5 seconds..."}
        </div>
      )}

      {compare?.status === "completed" && (
        <div className="space-y-5">
          <div className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--bg-card)] p-4" style={{ boxShadow: "var(--shadow-card)" }}>
            <h3 className="text-base font-semibold text-[var(--text-primary)] mb-3">Major Highlights</h3>
            <ul className="space-y-1.5">
              {(compare.summary?.major_highlights || []).map((h, idx) => (
                <li key={`${h}-${idx}`} className="text-sm text-[var(--text-primary)]">• {h}</li>
              ))}
            </ul>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            <div className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--bg-card)] p-3">
              <p className="text-xs text-[var(--text-secondary)]">Added Findings</p>
              <p className="text-xl font-semibold text-green-600">{compare.summary?.added_count ?? 0}</p>
            </div>
            <div className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--bg-card)] p-3">
              <p className="text-xs text-[var(--text-secondary)]">Removed Findings</p>
              <p className="text-xl font-semibold text-red-600">{compare.summary?.removed_count ?? 0}</p>
            </div>
            <div className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--bg-card)] p-3">
              <p className="text-xs text-[var(--text-secondary)]">Impact Changes</p>
              <p className="text-xl font-semibold text-[var(--primary)]">{compare.summary?.impact_changes_count ?? 0}</p>
            </div>
          </div>

          <div className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--bg-card)] p-4" style={{ boxShadow: "var(--shadow-card)" }}>
            <h3 className="text-base font-semibold text-[var(--text-primary)] mb-3">Section-wise LLM Comparison</h3>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[860px] border-collapse">
                <thead>
                  <tr className="bg-[var(--primary-light)]/30 border-b border-[var(--border)]">
                    <th className="text-left text-xs font-semibold text-[var(--text-secondary)] px-3 py-2">Section</th>
                    <th className="text-left text-xs font-semibold text-[var(--text-secondary)] px-3 py-2">Date 1 ({dateA})</th>
                    <th className="text-left text-xs font-semibold text-[var(--text-secondary)] px-3 py-2">Date 2 ({dateB})</th>
                    <th className="text-left text-xs font-semibold text-[var(--text-secondary)] px-3 py-2">Compared Result</th>
                    <th className="text-left text-xs font-semibold text-[var(--text-secondary)] px-3 py-2">Major Updates</th>
                  </tr>
                </thead>
                <tbody>
                  {sectionRows.length > 0 ? sectionRows.map((row, i) => (
                    <tr key={`${row.section}-${i}`} className={`border-b border-[var(--border)] ${i % 2 ? "bg-[var(--bg)]" : ""}`}>
                      <td className="px-3 py-2 text-sm font-medium text-[var(--text-primary)]">{row.section}</td>
                      <td className="px-3 py-2 text-sm text-[var(--text-secondary)]">{row.date_a_summary}</td>
                      <td className="px-3 py-2 text-sm text-[var(--text-secondary)]">{row.date_b_summary}</td>
                      <td className="px-3 py-2 text-sm text-[var(--text-primary)]">{row.compared_result}</td>
                      <td className="px-3 py-2 text-sm text-[var(--text-primary)]">
                        {(row.major_updates || []).length > 0 ? (row.major_updates || []).join(" | ") : "No major update"}
                      </td>
                    </tr>
                  )) : agentDeltas.map((d, i) => (
                    <tr key={d.agent} className={`border-b border-[var(--border)] ${i % 2 ? "bg-[var(--bg)]" : ""}`}>
                      <td className="px-3 py-2 text-sm font-medium text-[var(--text-primary)]">{d.label}</td>
                      <td className="px-3 py-2 text-sm text-[var(--text-secondary)]">{d.before} key items</td>
                      <td className="px-3 py-2 text-sm text-[var(--text-secondary)]">{d.after} key items</td>
                      <td className="px-3 py-2 text-sm text-[var(--text-primary)]">
                        {d.delta > 0 ? `Increased by ${d.delta}` : d.delta < 0 ? `Decreased by ${Math.abs(d.delta)}` : "No major change"}
                      </td>
                      <td className="px-3 py-2 text-sm text-[var(--text-primary)]">
                        {Math.abs(d.delta) >= 2 ? "Major change" : d.delta !== 0 ? "Minor change" : "No change"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

