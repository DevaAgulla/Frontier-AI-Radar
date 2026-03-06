"use client";

import type { AgentId } from "@/lib/types";
import { AGENTS } from "./AgentCards";

interface AgentPipelineProps {
  readonly selectedIds: AgentId[];
  readonly onChange: (ids: AgentId[]) => void;
}

function AgentIcon({ agent }: { readonly agent: (typeof AGENTS)[0] }) {
  return (
    <span className="flex items-center justify-center w-4 h-4 shrink-0 text-[var(--text-secondary)] [&_svg]:w-4 [&_svg]:h-4">
      {agent.placeholderIcon}
    </span>
  );
}

export default function AgentPipeline({ selectedIds, onChange }: AgentPipelineProps) {
  const add = (id: AgentId) => {
    if (selectedIds.includes(id)) return;
    onChange([...selectedIds, id]);
  };

  const remove = (index: number) => {
    onChange(selectedIds.filter((_, i) => i !== index));
  };

  const move = (index: number, dir: -1 | 1) => {
    const next = index + dir;
    if (next < 0 || next >= selectedIds.length) return;
    const arr = [...selectedIds];
    [arr[index], arr[next]] = [arr[next], arr[index]];
    onChange(arr);
  };

  const agentMap = new Map(AGENTS.map((a) => [a.id, a]));

  return (
    <div className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--bg-card)] p-4" style={{ boxShadow: "var(--shadow-card)" }}>
      <p className="text-xs text-[var(--text-muted)] mb-3">Click an agent to add to pipeline; reorder or remove below.</p>
      <div className="flex flex-wrap gap-2 mb-4">
        {AGENTS.map((agent) => {
          const inPipeline = selectedIds.includes(agent.id);
          return (
            <button
              key={agent.id}
              type="button"
              onClick={() => add(agent.id)}
              disabled={inPipeline}
              title={`${agent.label}: ${agent.description}`}
              className={`inline-flex items-center gap-2 rounded-[var(--radius)] border px-3 py-2 text-sm font-medium transition-all focus:outline-none focus:ring-2 focus:ring-[var(--primary)] focus:ring-offset-1 ${
                inPipeline
                  ? "border-[var(--border)] bg-[var(--border-light)] text-[var(--text-muted)] cursor-default"
                  : "border-[var(--border)] bg-white text-[var(--text-secondary)] hover:border-[var(--primary)] hover:bg-[var(--primary-light)]/50"
              }`}
            >
              <AgentIcon agent={agent} />
              <span>{agent.shortLabel}</span>
            </button>
          );
        })}
      </div>
      {selectedIds.length > 0 ? (
        <ul className="space-y-2">
          {selectedIds.map((id, index) => {
            const agent = agentMap.get(id);
            if (!agent) return null;
            return (
              <li
                key={`${id}-${index}`}
                className="flex items-center gap-2 rounded-[var(--radius)] border border-[var(--border)] bg-[var(--primary-light)]/30 px-3 py-2"
              >
                <span className="text-xs text-[var(--text-muted)] w-5">{index + 1}.</span>
                <AgentIcon agent={agent} />
                <span className="flex-1 text-sm font-medium text-[var(--text-primary)]">{agent.shortLabel}</span>
                <div className="flex gap-1">
                  <button
                    type="button"
                    onClick={() => move(index, -1)}
                    disabled={index === 0}
                    title="Move up"
                    className="p-1 rounded text-[var(--text-muted)] hover:bg-[var(--border)] hover:text-[var(--text-primary)] disabled:opacity-40 disabled:cursor-not-allowed"
                  >
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M18 15l-6-6-6 6" /></svg>
                  </button>
                  <button
                    type="button"
                    onClick={() => move(index, 1)}
                    disabled={index === selectedIds.length - 1}
                    title="Move down"
                    className="p-1 rounded text-[var(--text-muted)] hover:bg-[var(--border)] hover:text-[var(--text-primary)] disabled:opacity-40 disabled:cursor-not-allowed"
                  >
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M6 9l6 6 6-6" /></svg>
                  </button>
                  <button
                    type="button"
                    onClick={() => remove(index)}
                    title="Remove from pipeline"
                    className="p-1 rounded text-[var(--text-muted)] hover:bg-red-50 hover:text-red-600"
                  >
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M18 6L6 18M6 6l12 12" /></svg>
                  </button>
                </div>
              </li>
            );
          })}
        </ul>
      ) : (
        <p className="text-sm text-[var(--text-muted)] py-2">No agents in pipeline. Add above.</p>
      )}
    </div>
  );
}
