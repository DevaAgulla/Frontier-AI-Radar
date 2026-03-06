"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import AgentPipelineDragDrop from "../components/AgentPipelineDragDrop";
import { useRunConfig } from "../context/RunConfigContext";
import { useToast } from "../context/ToastContext";
import { useAuth } from "../context/AuthContext";
import { api } from "@/lib/api";
import type { AgentId } from "@/lib/types";

export default function BuildReportPage() {
  const { recipientEmails } = useRunConfig();
  const { user } = useAuth();
  const router = useRouter();
  const { pushToast } = useToast();
  const [selectedAgents, setSelectedAgents] = useState<AgentId[]>([]);
  const [running, setRunning] = useState(false);
  const [message, setMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);

  const handleRun = async () => {
    if (selectedAgents.length === 0) {
      setMessage({ type: "error", text: "Add at least one agent to the pipeline." });
      return;
    }
    setRunning(true);
    setMessage(null);
    try {
      const res = await api.triggerRun({
        agent_ids: selectedAgents,
        urls: [],
        url_mode: "default",
        ...(user ? { user_id: user.id } : { recipient_emails: recipientEmails }),
        async_run: true,
      });
      if (res.error) {
        setMessage({ type: "error", text: res.error });
        pushToast(res.error, "error");
        return;
      }
      const runId = res.data?.id ?? "latest";
      setMessage({ type: "success", text: `Run ${runId} queued. Redirecting to Runs for live status...` });
      pushToast(`Run ${runId} queued. Tracking in Runs...`, "success");
      router.push(`/runs?highlight=${encodeURIComponent(String(runId))}`);
    } catch (e) {
      setMessage({ type: "error", text: e instanceof Error ? e.message : "Request failed." });
      pushToast(e instanceof Error ? e.message : "Request failed.", "error");
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="min-h-full min-w-0 max-w-full flex flex-col">
      <div className="flex items-center gap-3 mb-2 shrink-0">
        <Link href="/" className="text-sm font-medium text-[var(--primary)] hover:underline flex items-center gap-1">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M19 12H5M12 19l-7-7 7-7" /></svg>
          Back
        </Link>
        <span className="text-[var(--text-muted)]">|</span>
        <h1 className="text-2xl font-semibold text-[var(--text-primary)]">Build Report</h1>
      </div>
      <p className="text-sm text-[var(--text-secondary)] mb-4 max-w-3xl shrink-0">
        Click or drag agents into the pipeline. All selected agents run <strong>in parallel</strong>. Then hit <strong>Run agents</strong> to generate a digest PDF and status records.
      </p>

      {/* Sticky action bar */}
      <div className="sticky top-14 z-10 flex flex-wrap items-center justify-between gap-3 py-3 mb-4 -mx-4 px-4 md:-mx-6 md:px-6 lg:-mx-8 lg:px-8 bg-[var(--bg)]/95 backdrop-blur-sm border-b border-[var(--border)] shrink-0">
        <span className="text-sm font-medium text-[var(--text-muted)]">
          {selectedAgents.length} agent{selectedAgents.length === 1 ? "" : "s"} in pipeline
        </span>
        <button
          type="button"
          onClick={handleRun}
          disabled={running || selectedAgents.length === 0}
          title="Run pipeline and generate digest report"
          className="flex items-center gap-2 px-5 py-2 rounded-[var(--radius)] text-sm font-medium bg-[var(--primary)] text-white hover:bg-[var(--primary-hover)] disabled:opacity-50 disabled:cursor-not-allowed transition-all shadow-md"
        >
          {running ? "Running…" : "Run agents"}
        </button>
      </div>

      {/* Drag-and-drop pipeline */}
      <section className="mb-6 min-w-0">
        <AgentPipelineDragDrop selectedIds={selectedAgents} onChange={setSelectedAgents} />
      </section>

      {message && (
        <div className={`mt-2 p-3 rounded-[var(--radius)] text-sm max-w-2xl min-w-0 ${message.type === "success" ? "bg-[var(--success-bg)] text-[var(--success-text)]" : "bg-[var(--error-bg)] text-[var(--error-text)]"}`}>
          {message.text}
        </div>
      )}
    </div>
  );
}
