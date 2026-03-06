"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import AgentPipelineDragDrop from "../components/AgentPipelineDragDrop";
import { useRunConfig } from "../context/RunConfigContext";
import { useToast } from "../context/ToastContext";
import { api } from "@/lib/api";
import type { AgentId } from "@/lib/types";

export default function BuildReportPage() {
  const { competitorUrl, recipientEmails, setRecipientEmails } = useRunConfig();
  const router = useRouter();
  const { pushToast } = useToast();
  const [selectedAgents, setSelectedAgents] = useState<AgentId[]>([]);
  const [running, setRunning] = useState(false);
  const [urlMode, setUrlMode] = useState<"default" | "append" | "custom">("default");
  const [customUrlsText, setCustomUrlsText] = useState("");
  const [message, setMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);

  const parsedCustomUrls = customUrlsText
    .split(/\r?\n|,/)
    .map((u) => u.trim())
    .filter(Boolean);

  const allUrls = Array.from(
    new Set([
      ...(competitorUrl.trim() ? [competitorUrl.trim()] : []),
      ...parsedCustomUrls,
    ])
  );

  const handleRun = async () => {
    if (selectedAgents.length === 0) {
      setMessage({ type: "error", text: "Add at least one agent to the pipeline." });
      return;
    }
    if (urlMode === "custom" && allUrls.length === 0) {
      setMessage({ type: "error", text: "In custom mode, add at least one URL." });
      return;
    }
    setRunning(true);
    setMessage(null);
    try {
      const res = await api.triggerRun({
        agent_ids: selectedAgents,
        urls: allUrls,
        url_mode: urlMode,
        recipient_emails: recipientEmails,
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

  const handleExportPDF = () => {
    if (selectedAgents.length === 0) return;
    setMessage({ type: "success", text: "Export triggered; PDF will appear in Archive when run completes." });
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
        Drag agents into the pipeline. All selected agents run <strong>in parallel</strong>. Configure URL mode and recipients, then run to generate digest PDF and status records.
      </p>

      {/* Sticky action bar: stays below header so "Run pipeline" is always visible */}
      <div className="sticky top-14 z-10 flex flex-wrap items-center justify-between gap-3 py-3 mb-4 -mx-4 px-4 md:-mx-6 md:px-6 lg:-mx-8 lg:px-8 bg-[var(--bg)]/95 backdrop-blur-sm border-b border-[var(--border)] shrink-0">
        <span className="text-sm text-[var(--text-muted)]">
          {selectedAgents.length} agent{selectedAgents.length === 1 ? "" : "s"} in pipeline
        </span>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={handleExportPDF}
            disabled={selectedAgents.length === 0}
            title={selectedAgents.length > 0 ? "Export PDF with pipeline agents" : "Add agents to pipeline first"}
            className="flex items-center gap-2 px-4 py-2 rounded-[var(--radius)] text-sm font-medium border-2 border-[var(--border)] bg-[var(--bg-card)] text-[var(--text-secondary)] hover:border-[var(--primary)] hover:text-[var(--primary)] disabled:opacity-50 disabled:cursor-not-allowed transition-all"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
              <polyline points="7 10 12 15 17 10" />
              <line x1="12" y1="15" x2="12" y2="3" />
            </svg>
            Export PDF
          </button>
          <button
            type="button"
            onClick={handleRun}
            disabled={running || selectedAgents.length === 0}
            title="Run pipeline and optionally send digest email"
            className="flex items-center gap-2 px-5 py-2 rounded-[var(--radius)] text-sm font-medium bg-[var(--primary)] text-white hover:bg-[var(--primary-hover)] disabled:opacity-50 disabled:cursor-not-allowed transition-all shadow-md"
          >
            {running ? "Running…" : "Run agents"}
          </button>
        </div>
      </div>

      {/* Drag-and-drop pipeline */}
      <section className="mb-6 min-w-0">
        <AgentPipelineDragDrop selectedIds={selectedAgents} onChange={setSelectedAgents} />
      </section>

      <section className="grid grid-cols-1 lg:grid-cols-2 gap-4 max-w-5xl">
        <div className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--bg-card)] p-4" style={{ boxShadow: "var(--shadow-card)" }}>
          <h3 className="text-sm font-semibold text-[var(--text-primary)] mb-2">URL Mode</h3>
          <select
            value={urlMode}
            onChange={(e) => setUrlMode(e.target.value as "default" | "append" | "custom")}
            className="w-full rounded-[var(--radius)] border border-[var(--border)] px-3 py-2 text-sm text-[var(--text-primary)] focus:border-[var(--primary)] focus:outline-none"
          >
            <option value="default">Default (agent defaults only)</option>
            <option value="append">Append (defaults + custom URLs)</option>
            <option value="custom">Custom (only custom URLs)</option>
          </select>
          <p className="text-xs text-[var(--text-muted)] mt-2">
            Current config URL from Competitor report is auto-included: {competitorUrl.trim() || "none"}.
          </p>
        </div>

        <div className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--bg-card)] p-4" style={{ boxShadow: "var(--shadow-card)" }}>
          <h3 className="text-sm font-semibold text-[var(--text-primary)] mb-2">Custom URLs</h3>
          <textarea
            value={customUrlsText}
            onChange={(e) => setCustomUrlsText(e.target.value)}
            rows={5}
            placeholder="https://openai.com/blog&#10;https://www.anthropic.com/news"
            className="w-full rounded-[var(--radius)] border border-[var(--border)] px-3 py-2 text-sm text-[var(--text-primary)] focus:border-[var(--primary)] focus:outline-none"
          />
          <p className="text-xs text-[var(--text-muted)] mt-2">{allUrls.length} URL(s) will be sent in this run.</p>
        </div>
      </section>

      <section className="mt-4 max-w-5xl rounded-[var(--radius)] border border-[var(--border)] bg-[var(--bg-card)] p-4" style={{ boxShadow: "var(--shadow-card)" }}>
        <h3 className="text-sm font-semibold text-[var(--text-primary)] mb-2">Recipient Email</h3>
        <input
          type="email"
          value={recipientEmails[0] ?? ""}
          onChange={(e) => setRecipientEmails(e.target.value.trim() ? [e.target.value.trim()] : [])}
          placeholder="Optional: user@example.com"
          className="w-full max-w-md rounded-[var(--radius)] border border-[var(--border)] px-3 py-2 text-sm text-[var(--text-primary)] focus:border-[var(--primary)] focus:outline-none"
        />
        <p className="text-xs text-[var(--text-muted)] mt-2">
          If provided, digest is emailed to this address. If empty, backend uses subscribed users for scheduled/owner flow.
        </p>
      </section>

      {message && (
        <div className={`mt-6 p-3 rounded-[var(--radius)] text-sm max-w-2xl min-w-0 ${message.type === "success" ? "bg-[var(--success-bg)] text-[var(--success-text)]" : "bg-[var(--error-bg)] text-[var(--error-text)]"}`}>
          {message.text}
        </div>
      )}
    </div>
  );
}
