"use client";

interface ToggleOption {
  id: string;
  label: string;
  sub: string;
  icon: React.ReactNode;
}

interface ToggleOptionsProps {
  toggles: Record<string, boolean>;
  onToggle: (id: string) => void;
}

export default function ToggleOptions({ toggles, onToggle }: ToggleOptionsProps) {
  const options: ToggleOption[] = [
    {
      id: "hf_reports",
      label: "HF Reports",
      sub: "Model cards & evaluations",
      icon: (
        <svg width="15" height="15" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24" strokeLinecap="round" strokeLinejoin="round">
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
          <polyline points="14,2 14,8 20,8" />
          <line x1="16" y1="13" x2="8" y2="13" />
          <line x1="16" y1="17" x2="8" y2="17" />
        </svg>
      ),
    },
    {
      id: "foundational_models",
      label: "Foundational Models",
      sub: "Base architecture analysis",
      icon: (
        <svg width="15" height="15" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="3" />
          <path d="M12 1v4M12 19v4M4.22 4.22l2.83 2.83M16.95 16.95l2.83 2.83M1 12h4M19 12h4M4.22 19.78l2.83-2.83M16.95 7.05l2.83-2.83" />
        </svg>
      ),
    },
    {
      id: "research_papers",
      label: "Research Papers",
      sub: "ArXiv & academic sources",
      icon: (
        <svg width="15" height="15" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24" strokeLinecap="round" strokeLinejoin="round">
          <path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z" />
          <path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z" />
        </svg>
      ),
    },
  ];

  const activeCount = options.filter(o => toggles[o.id]).length;

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between mb-1">
        <p className="text-xs font-medium text-gray-400 uppercase tracking-widest">Data Sources</p>
        <span className="text-xs text-gray-400">{activeCount}/{options.length} active</span>
      </div>

      {options.map(option => {
        const isOn = toggles[option.id] ?? false;
        return (
          <div
            key={option.id}
            className="flex items-center justify-between px-4 py-3 rounded-xl border transition-all duration-150 cursor-pointer"
            style={{
              background: isOn ? "#111827" : "#ffffff",
              borderColor: isOn ? "#111827" : "#e5e7eb",
              boxShadow: isOn ? "0 2px 8px rgba(0,0,0,0.12)" : "0 1px 3px rgba(0,0,0,0.04)",
            }}
            onClick={() => onToggle(option.id)}
          >
            <div className="flex items-center gap-3">
              <span style={{ color: isOn ? "rgba(255,255,255,0.7)" : "#9ca3af" }}>{option.icon}</span>
              <div>
                <p className="text-sm font-medium" style={{ color: isOn ? "white" : "#111827" }}>{option.label}</p>
                <p className="text-[11px]" style={{ color: isOn ? "rgba(255,255,255,0.45)" : "#9ca3af" }}>{option.sub}</p>
              </div>
            </div>
            {/* Toggle pill */}
            <button
              role="switch"
              aria-checked={isOn}
              onClick={e => { e.stopPropagation(); onToggle(option.id); }}
              className="relative rounded-full transition-all duration-200 flex-shrink-0"
              style={{ width: "36px", height: "20px", background: isOn ? "rgba(255,255,255,0.25)" : "#e5e7eb" }}
            >
              <span
                className="absolute top-[2px] w-4 h-4 rounded-full shadow-sm transition-all duration-200"
                style={{ left: isOn ? "18px" : "2px", background: isOn ? "white" : "#9ca3af" }}
              />
            </button>
          </div>
        );
      })}
    </div>
  );
}
