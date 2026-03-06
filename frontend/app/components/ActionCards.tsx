"use client";

import { useState } from "react";

const cards = [
  {
    id: "runs",
    title: "Runs",
    description: "Pipeline execution history, status, and logs",
    badge: "Live",
    badgeBg: "#dcfce7",
    badgeColor: "#16a34a",
    stat: "24",
    statLabel: "this week",
    trend: "+12%",
    trendUp: true,
    icon: (
      <svg width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24" strokeLinecap="round" strokeLinejoin="round">
        <polygon points="5,3 19,12 5,21" />
      </svg>
    ),
  },
  {
    id: "report",
    title: "Report",
    description: "AI competitive intelligence reports & briefings",
    badge: "PDF",
    badgeBg: "#fef3c7",
    badgeColor: "#d97706",
    stat: "8",
    statLabel: "generated today",
    trend: "+3",
    trendUp: true,
    icon: (
      <svg width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24" strokeLinecap="round" strokeLinejoin="round">
        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
        <polyline points="14,2 14,8 20,8" />
        <line x1="16" y1="13" x2="8" y2="13" />
        <line x1="16" y1="17" x2="8" y2="17" />
      </svg>
    ),
  },
  {
    id: "benchmarks",
    title: "HF Benchmarks",
    description: "Frontier model scores across HF leaderboards",
    badge: "HF",
    badgeBg: "#ede9fe",
    badgeColor: "#7c3aed",
    stat: "142",
    statLabel: "models tracked",
    trend: "+5 new",
    trendUp: true,
    icon: (
      <svg width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24" strokeLinecap="round" strokeLinejoin="round">
        <line x1="18" y1="20" x2="18" y2="10" />
        <line x1="12" y1="20" x2="12" y2="4" />
        <line x1="6" y1="20" x2="6" y2="14" />
      </svg>
    ),
  },
];

export default function ActionCards() {
  const [active, setActive] = useState<string | null>(null);

  return (
    <div className="w-full">
      <p className="text-xs font-medium text-gray-400 uppercase tracking-widest mb-4">Quick Access</p>
      <div className="grid grid-cols-3 gap-3">
        {cards.map(card => {
          const isActive = active === card.id;
          return (
            <button
              key={card.id}
              onClick={() => { console.log(`API will be connected here - ${card.title}`); setActive(isActive ? null : card.id); }}
              className="text-left rounded-2xl p-5 border transition-all duration-200 group"
              style={{
                background: isActive ? "#111827" : "#ffffff",
                borderColor: isActive ? "#111827" : "#e5e7eb",
                boxShadow: isActive ? "0 4px 20px rgba(0,0,0,0.15)" : "0 1px 3px rgba(0,0,0,0.04)",
              }}
              onMouseEnter={e => { if (!isActive) { (e.currentTarget as HTMLElement).style.borderColor = "#d1d5db"; (e.currentTarget as HTMLElement).style.boxShadow = "0 4px 12px rgba(0,0,0,0.08)"; } }}
              onMouseLeave={e => { if (!isActive) { (e.currentTarget as HTMLElement).style.borderColor = "#e5e7eb"; (e.currentTarget as HTMLElement).style.boxShadow = "0 1px 3px rgba(0,0,0,0.04)"; } }}
            >
              {/* Top */}
              <div className="flex items-start justify-between mb-4">
                <div
                  className="w-9 h-9 rounded-xl flex items-center justify-center"
                  style={{ background: isActive ? "rgba(255,255,255,0.12)" : "#f3f4f6", color: isActive ? "white" : "#374151" }}
                >
                  {card.icon}
                </div>
                <span
                  className="text-[10px] font-semibold px-2 py-0.5 rounded-full"
                  style={{ background: isActive ? "rgba(255,255,255,0.15)" : card.badgeBg, color: isActive ? "rgba(255,255,255,0.9)" : card.badgeColor }}
                >
                  {card.badge}
                </span>
              </div>

              {/* Content */}
              <h3 className="text-sm font-semibold mb-1" style={{ color: isActive ? "white" : "#111827" }}>
                {card.title}
              </h3>
              <p className="text-xs leading-relaxed mb-4" style={{ color: isActive ? "rgba(255,255,255,0.55)" : "#9ca3af" }}>
                {card.description}
              </p>

              {/* Stat */}
              <div className="flex items-end justify-between">
                <div>
                  <div className="text-xl font-bold" style={{ color: isActive ? "white" : "#111827" }}>{card.stat}</div>
                  <div className="text-[10px]" style={{ color: isActive ? "rgba(255,255,255,0.4)" : "#9ca3af" }}>{card.statLabel}</div>
                </div>
                <span
                  className="text-[10px] font-semibold px-1.5 py-0.5 rounded"
                  style={{ background: isActive ? "rgba(52,211,153,0.2)" : "#f0fdf4", color: isActive ? "#6ee7b7" : "#16a34a" }}
                >
                  {card.trend}
                </span>
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}
