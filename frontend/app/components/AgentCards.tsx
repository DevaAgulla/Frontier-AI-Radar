"use client";

export type AgentId = "competitor" | "foundation" | "research" | "huggingface";

const AGENTS: Array<{
  id: AgentId;
  shortLabel: string;
  label: string;
  description: string;
  imagePath: string;
  placeholderIcon: React.ReactNode;
}> = [
  {
    id: "competitor",
    shortLabel: "Competitor",
    label: "Competitor releases",
    description: "Product/platform updates",
    imagePath: "/agents/agent-competitor-releases.png",
    placeholderIcon: (
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
        <circle cx="12" cy="10" r="4" />
        <path d="M4 20c0-4 4-6 8-6s8 2 8 6" />
      </svg>
    ),
  },
  {
    id: "foundation",
    shortLabel: "Foundation",
    label: "Foundation model provider releases",
    description: "Model launches, API updates, pricing, eval claims",
    imagePath: "/agents/agent-foundation-model.png",
    placeholderIcon: (
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
        <rect x="4" y="4" width="16" height="16" rx="1" fill="#5929D0" fillOpacity="0.15" stroke="currentColor" />
        <path d="M8 10h8M8 14h6" stroke="currentColor" />
      </svg>
    ),
  },
  {
    id: "research",
    shortLabel: "Research",
    label: "Latest research publications",
    description: "LLMs / multimodal / agents / eval / alignment",
    imagePath: "/agents/agent-research-publications.png",
    placeholderIcon: (
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
        <circle cx="12" cy="12" r="5" />
        <path d="M12 7v2M12 15v2M7 12h2M15 12h2" />
      </svg>
    ),
  },
  {
    id: "huggingface",
    shortLabel: "Hugging Face",
    label: "Hugging Face benchmarking results",
    description: "Leaderboards, new SOTA claims, dataset/task-specific trends",
    imagePath: "/agents/agent-huggingface-benchmarks.png",
    placeholderIcon: (
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
        <circle cx="12" cy="13" r="6" fill="#FACC15" fillOpacity="0.3" stroke="currentColor" />
      </svg>
    ),
  },
];

interface AgentCardsProps {
  readonly selectedIds: readonly AgentId[];
  readonly onToggle: (id: AgentId) => void;
}

function AgentChipIcon({ agent }: { readonly agent: (typeof AGENTS)[0] }) {
  return (
    <span className="flex items-center justify-center w-4 h-4 shrink-0 text-[var(--text-secondary)] [&_svg]:w-4 [&_svg]:h-4">
      {agent.placeholderIcon}
    </span>
  );
}

export default function AgentCards({ selectedIds, onToggle }: AgentCardsProps) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      {AGENTS.map((agent) => {
        const isSelected = selectedIds.includes(agent.id);
        const tooltip = `${agent.label}: ${agent.description}`;
        return (
          <button
            key={agent.id}
            type="button"
            onClick={() => onToggle(agent.id)}
            title={tooltip}
            className={`inline-flex items-center gap-2 rounded-[var(--radius)] border px-3 py-2 text-sm font-medium transition-all duration-150 focus:outline-none focus:ring-2 focus:ring-[var(--primary)] focus:ring-offset-1 ${
              isSelected
                ? "border-[var(--primary)] bg-[var(--primary-light)] text-[var(--primary)]"
                : "border-[var(--border)] bg-[var(--bg-card)] text-[var(--text-secondary)] hover:border-[var(--border-purple)] hover:bg-[var(--primary-light)]/50"
            }`}
            style={{ boxShadow: "var(--shadow-card)" }}
          >
            <AgentChipIcon agent={agent} />
            <span>{agent.shortLabel}</span>
          </button>
        );
      })}
    </div>
  );
}

export { AGENTS };
