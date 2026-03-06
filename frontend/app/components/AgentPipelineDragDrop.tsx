"use client";

import { useCallback } from "react";
import type { AgentId } from "@/lib/types";
import { AGENTS } from "./AgentCards";

interface AgentPipelineDragDropProps {
  readonly selectedIds: AgentId[];
  readonly onChange: (ids: AgentId[]) => void;
}

/* ── Parallel-fork icon (one line splitting into many) ───────────── */
function ForkIcon({ className }: { className?: string }) {
  return (
    <svg className={className} width="32" height="60" viewBox="0 0 32 60" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
      <path d="M16 0 V20" />
      <path d="M16 20 Q16 30 4 30" />
      <path d="M16 20 Q16 30 28 30" />
      <circle cx="16" cy="14" r="3" fill="currentColor" strokeWidth="0" />
    </svg>
  );
}

/* ── Merge icon (many lines joining into one) ────────────────────── */
function MergeIcon({ className }: { className?: string }) {
  return (
    <svg className={className} width="32" height="60" viewBox="0 0 32 60" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
      <path d="M4 10 Q16 10 16 25" />
      <path d="M28 10 Q16 10 16 25" />
      <path d="M16 25 V45" />
      <circle cx="16" cy="38" r="3" fill="currentColor" strokeWidth="0" />
    </svg>
  );
}

export default function AgentPipelineDragDrop({ selectedIds, onChange }: AgentPipelineDragDropProps) {
  const agentMap = new Map(AGENTS.map((a) => [a.id, a]));

  const handleDragStart = useCallback((e: React.DragEvent, agentId: AgentId, fromPipeline: boolean) => {
    e.dataTransfer.setData("application/agent-id", agentId);
    e.dataTransfer.setData("application/from-pipeline", String(fromPipeline));
    e.dataTransfer.effectAllowed = "move";
  }, []);

  const handleDropOnPipeline = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      const id = e.dataTransfer.getData("application/agent-id") as AgentId | "";
      if (!id || !agentMap.has(id)) return;
      const fromPipeline = e.dataTransfer.getData("application/from-pipeline") === "true";
      if (fromPipeline) {
        return;
      } else {
        if (selectedIds.includes(id)) return;
        onChange([...selectedIds, id]);
      }
    },
    [selectedIds, onChange, agentMap]
  );

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
  }, []);

  const removeFromPipeline = useCallback(
    (index: number) => {
      onChange(selectedIds.filter((_, i) => i !== index));
    },
    [selectedIds, onChange]
  );

  /* Click-to-add: toggle agent in/out of pipeline */
  const handleAgentClick = useCallback(
    (agentId: AgentId) => {
      if (selectedIds.includes(agentId)) {
        onChange(selectedIds.filter((id) => id !== agentId));
      } else {
        onChange([...selectedIds, agentId]);
      }
    },
    [selectedIds, onChange]
  );

  return (
    <div className="grid grid-cols-1 lg:grid-cols-[280px_1fr] gap-6 w-full">
      {/* Left: Available report agents (draggable + clickable) */}
      <div className="rounded-xl border-2 border-[var(--border)] bg-[var(--bg-card)] p-4 shadow-sm">
        <h3 className="text-sm font-bold text-[var(--text-primary)] mb-1">Report agents</h3>
        <p className="text-xs font-medium text-[var(--text-muted)] mb-3">
          Click or drag agents into the pipeline. All selected agents run <strong>in parallel</strong>.
        </p>
        <ul className="space-y-2">
          {AGENTS.map((agent) => {
            const inPipeline = selectedIds.includes(agent.id);
            return (
              <li
                key={agent.id}
                draggable
                onDragStart={(e) => handleDragStart(e, agent.id, false)}
                onClick={() => handleAgentClick(agent.id)}
                className={`rounded-lg border-2 px-3 py-2.5 flex items-center gap-3 cursor-pointer active:scale-[0.98] transition-all select-none ${
                  inPipeline
                    ? "border-[var(--primary)] bg-[var(--primary-light)] opacity-90 ring-2 ring-[var(--primary)]/20"
                    : "border-[var(--border)] bg-[var(--bg-card)] hover:border-[var(--border-purple)] hover:shadow-md"
                }`}
                title={`${agent.label}: ${agent.description}. Click or drag to ${inPipeline ? "remove from" : "add to"} pipeline.`}
              >
                <span className="flex items-center justify-center w-8 h-8 rounded-lg bg-[var(--primary-light)] shrink-0 [&_svg]:w-4 [&_svg]:h-4 text-[var(--primary)]">
                  {agent.placeholderIcon}
                </span>
                <div className="min-w-0 flex-1">
                  <span className="text-sm font-semibold text-[var(--text-primary)] block truncate">{agent.shortLabel}</span>
                  <span className="text-xs text-[var(--text-muted)] truncate block">{agent.description}</span>
                </div>
                {inPipeline && (
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--primary)" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" className="shrink-0">
                    <polyline points="20 6 9 17 4 12" />
                  </svg>
                )}
              </li>
            );
          })}
        </ul>
      </div>

      {/* Right: Pipeline (drop zone) — parallel execution layout */}
      <div className="rounded-xl border-2 border-dashed border-[var(--border)] bg-[var(--bg)] min-h-[200px] p-4">
        <h3 className="text-sm font-bold text-[var(--text-primary)] mb-1">Your pipeline</h3>
        <p className="text-xs font-medium text-[var(--text-muted)] mb-4">
          Drop agents here. All agents execute <strong>in parallel</strong>.
        </p>
        <div
          onDrop={handleDropOnPipeline}
          onDragOver={handleDragOver}
          className={`rounded-lg border-2 min-h-[140px] p-4 transition-colors ${
            selectedIds.length === 0
              ? "border-dashed border-[var(--border)] bg-[var(--primary-light)]/10"
              : "border-[var(--border)] bg-[var(--bg-card)]"
          }`}
        >
          {selectedIds.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-[120px] text-center text-[var(--text-muted)]">
              <svg className="w-10 h-10 mb-2 opacity-50" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                <path d="M12 5v14M5 12h14" strokeLinecap="round" />
              </svg>
              <span className="text-sm font-semibold">Drop agents here or click to add</span>
              <span className="text-xs font-medium mt-0.5">All agents run in parallel</span>
            </div>
          ) : (
            <div className="flex items-center justify-center gap-4">
              {/* Fork: single input splits into parallel lanes */}
              <div className="flex flex-col items-center shrink-0">
                <span className="text-[10px] font-semibold uppercase tracking-widest text-[var(--text-muted)] mb-1">Start</span>
                <ForkIcon className="text-[var(--primary)] opacity-70" />
              </div>

              {/* Parallel agent lanes */}
              <div className="flex flex-col gap-2 min-w-0">
                {/* Parallel execution banner */}
                <div className="flex items-center gap-1.5 mb-1">
                  <span className="relative flex h-2.5 w-2.5">
                    <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75" />
                    <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-green-500" />
                  </span>
                  <span className="text-[10px] font-semibold uppercase tracking-widest text-green-600">
                    Parallel execution
                  </span>
                </div>

                {/* Bracket + agent cards stacked vertically */}
                <div className="relative flex items-stretch">
                  {/* Left bracket bar */}
                  <div className="w-1 rounded-full bg-[var(--primary)] opacity-40 mr-3 shrink-0" />

                  <div className="flex flex-col gap-2 flex-1 min-w-0">
                    {selectedIds.map((id, index) => {
                      const agent = agentMap.get(id);
                      if (!agent) return null;
                      return (
                        <div
                          key={id}
                          draggable
                          onDragStart={(e) => handleDragStart(e, id, true)}
                          onDragOver={handleDragOver}
                          className="flex items-center gap-2 rounded-lg border-2 border-[var(--primary)] bg-[var(--primary-light)] px-3 py-2 cursor-grab active:cursor-grabbing group transition-all hover:shadow-md"
                        >
                          {/* Parallel indicator dot */}
                          <span className="flex items-center justify-center w-5 h-5 rounded-full bg-[var(--primary)] text-white text-[10px] font-bold shrink-0">
                            &#x2225;
                          </span>
                          <span className="[&_svg]:w-4 [&_svg]:h-4 text-[var(--primary)]">{agent.placeholderIcon}</span>
                          <span className="text-sm font-medium text-[var(--text-primary)]">{agent.shortLabel}</span>
                          <button
                            type="button"
                            onClick={() => removeFromPipeline(index)}
                            className="ml-auto p-1 rounded text-[var(--text-muted)] hover:opacity-80 hover:text-red-500 transition-colors"
                            title="Remove from pipeline"
                            aria-label={`Remove ${agent.shortLabel} from pipeline`}
                          >
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                              <path d="M18 6L6 18M6 6l12 12" />
                            </svg>
                          </button>
                        </div>
                      );
                    })}
                  </div>

                  {/* Right bracket bar */}
                  <div className="w-1 rounded-full bg-[var(--primary)] opacity-40 ml-3 shrink-0" />
                </div>
              </div>

              {/* Merge: parallel lanes join back into single output */}
              <div className="flex flex-col items-center shrink-0">
                <MergeIcon className="text-[var(--primary)] opacity-70" />
                <span className="text-[10px] font-semibold uppercase tracking-widest text-[var(--text-muted)] mt-1">Merge</span>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
