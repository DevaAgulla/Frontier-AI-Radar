"use client";

import { useState, useEffect, createContext, useContext } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { HEADER_HEIGHT } from "./Header";

export const SIDEBAR_WIDTH_COLLAPSED = 64;
export const SIDEBAR_WIDTH_EXPANDED = 220;

const SidebarWidthContext = createContext(SIDEBAR_WIDTH_EXPANDED);

export function useSidebarWidth() {
  return useContext(SidebarWidthContext);
}

const NAV_ITEMS: { label: string; href: string; icon: "dashboard" | "pipeline" | "config" | "scheduler" | "sources" | "runs" | "findings" | "compare" | "archive" }[] = [
  { label: "Dashboard", href: "/", icon: "dashboard" },
  { label: "Build Report", href: "/run", icon: "pipeline" },
  { label: "Competitor report", href: "/config", icon: "config" },
  { label: "Compare reports", href: "/compare", icon: "compare" },
  { label: "Scheduler", href: "/scheduler", icon: "scheduler" },
  { label: "Sources", href: "/sources", icon: "sources" },
  { label: "Runs", href: "/runs", icon: "runs" },
  { label: "Findings", href: "/findings", icon: "findings" },
  { label: "Archive", href: "/archive", icon: "archive" },
];

function NavIcon({ name, active }: { readonly name: string; readonly active: boolean }) {
  const stroke = active ? "var(--primary)" : "var(--text-primary)";
  const size = 20;
  switch (name) {
    case "dashboard":
      return (
        <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={stroke} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <rect x="3" y="3" width="7" height="7" /><rect x="14" y="3" width="7" height="7" />
          <rect x="14" y="14" width="7" height="7" /><rect x="3" y="14" width="7" height="7" />
        </svg>
      );
    case "pipeline":
      return (
        <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={stroke} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <rect x="2" y="6" width="6" height="12" rx="1" /><rect x="10" y="4" width="6" height="16" rx="1" />
          <rect x="18" y="8" width="4" height="8" rx="1" /><path d="M8 12h2M16 12h2" />
        </svg>
      );
    case "config":
      return (
        <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={stroke} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="3" />
          <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z" />
        </svg>
      );
    case "scheduler":
      return (
        <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={stroke} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="12" cy="12" r="10" />
          <polyline points="12 6 12 12 16 14" />
        </svg>
      );
    case "sources":
      return (
        <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={stroke} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71" />
          <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71" />
        </svg>
      );
    case "runs":
      return (
        <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={stroke} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <polygon points="5 3 19 12 5 21 5 3" />
        </svg>
      );
    case "findings":
      return (
        <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={stroke} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" />
        </svg>
      );
    case "archive":
      return (
        <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={stroke} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M21 8v13H3V8" /><path d="M1 3h22v5H1z" /><path d="M10 12h4" />
        </svg>
      );
    case "compare":
      return (
        <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={stroke} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="8" cy="12" r="3" />
          <circle cx="16" cy="12" r="3" />
          <path d="M11 12h2" />
          <path d="M8 9V6M16 18v-3" />
        </svg>
      );
    default:
      return <circle cx="12" cy="12" r="10" stroke={stroke} strokeWidth="2" fill="none" />;
  }
}

export default function Sidebar({ children }: { readonly children?: React.ReactNode }) {
  const pathname = usePathname();
  const [expanded, setExpanded] = useState(true);

  useEffect(() => {
    const stored = globalThis.localStorage?.getItem("sidebar-expanded");
    if (stored !== null) setExpanded(stored === "true");
  }, []);

  const toggle = () => {
    setExpanded((e) => {
      const next = !e;
      globalThis.localStorage?.setItem("sidebar-expanded", String(next));
      return next;
    });
  };

  const width = expanded ? SIDEBAR_WIDTH_EXPANDED : SIDEBAR_WIDTH_COLLAPSED;
  const sidebarHeight = `calc(100vh - ${HEADER_HEIGHT}px)`;

  return (
    <SidebarWidthContext.Provider value={width}>
      {/* Sidebar container: no overflow-hidden so toggle stays visible */}
      <div
        className="fixed left-0 z-40 flex transition-[width] duration-200 ease-out"
        style={{ top: `${HEADER_HEIGHT}px`, height: sidebarHeight, width: `${width}px` }}
      >
        <aside
          className="h-full flex flex-col border-r border-[var(--border)] bg-[var(--bg-card)] shadow-sm overflow-hidden"
          style={{ width: `${width}px` }}
        >
          <nav className="flex-1 py-4 overflow-y-auto overflow-x-hidden">
            <ul className="space-y-0.5 px-2">
              {NAV_ITEMS.map(({ label, href, icon }) => {
                const isActive = pathname === href || (href !== "/" && pathname.startsWith(href));
                return (
                  <li key={href}>
                    <Link
                      href={href}
                      className={`flex items-center gap-3 w-full py-2.5 px-3 rounded-lg transition-colors ${
                        isActive
                          ? "bg-[var(--primary-light)] text-[var(--primary)]"
                          : "text-[var(--text-primary)] hover:bg-[var(--primary-light)]/60 hover:text-[var(--primary)]"
                      }`}
                      title={expanded ? undefined : label}
                    >
                      <span className="shrink-0 flex items-center justify-center w-5 h-5">
                        <NavIcon name={icon} active={isActive} />
                      </span>
                      {expanded && <span className="text-sm font-medium truncate">{label}</span>}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </nav>
        </aside>
        {/* Toggle: outside aside so it is not clipped; sits on right edge */}
        <button
          type="button"
          onClick={toggle}
          aria-label={expanded ? "Collapse sidebar" : "Expand sidebar"}
          className="absolute top-1/2 -translate-y-1/2 w-5 h-9 flex items-center justify-center rounded-r-md bg-[var(--primary)] text-white shadow-md hover:bg-[var(--primary-hover)] transition-all duration-200 z-[60] border border-l-0 border-[var(--border)]"
          style={{ left: `${width}px` }}
        >
          <svg
            width="10"
            height="10"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            className={expanded ? "" : "rotate-180"}
          >
            <path d="M15 18l-6-6 6-6" />
          </svg>
        </button>
      </div>
      <main
        className="min-h-screen min-w-0 transition-[margin,width] duration-200 ease-out bg-[var(--bg)] pt-4 pb-8 pl-4 pr-6 md:pl-6 md:pr-8 overflow-x-auto flex flex-col"
        style={{ marginLeft: `${width}px`, marginTop: `${HEADER_HEIGHT}px`, width: `calc(100vw - ${width}px)` }}
      >
        {children}
      </main>
    </SidebarWidthContext.Provider>
  );
}
