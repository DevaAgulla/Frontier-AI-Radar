"use client";

import { useEffect, useState } from "react";
import BackButton from "../components/BackButton";
import { api } from "@/lib/api";
import type { Digest } from "@/lib/types";

export default function ArchivePage() {
  const [digests, setDigests] = useState<Digest[]>([]);
  const [loading, setLoading] = useState(true);
  const [q, setQ] = useState("");

  useEffect(() => {
    api.getDigests({ q: q.trim() || undefined }).then((res) => {
      if (res.data) setDigests(res.data);
      setLoading(false);
    });
  }, [q]);

  return (
    <div className="min-h-full min-w-0 max-w-full py-4">
        <div className="flex items-center gap-4 mb-2">
          <BackButton href="/" label="Back" />
          <h1 className="text-2xl font-semibold text-[var(--text-primary)]">Digest Archive</h1>
        </div>
        <p className="text-sm text-[var(--text-secondary)] mb-6">
          Past PDF digests. Search and download.
        </p>

        <div className="mb-6">
          <input
            type="search"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search digests"
            className="w-full max-w-md rounded-[var(--radius)] border border-[var(--border)] px-3 py-2 text-sm text-[var(--text-primary)] placeholder-[var(--text-muted)] focus:border-[var(--primary)] focus:outline-none"
          />
        </div>

        {loading ? (
          <p className="text-sm text-[var(--text-muted)]">Loading…</p>
        ) : digests.length === 0 ? (
          <p className="text-sm text-[var(--text-muted)]">No digests found.</p>
        ) : (
          <ul className="space-y-3">
            {digests.map((d) => (
              <li
                key={d.id}
                className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--bg-card)] p-4 hover:border-[var(--primary)] transition-colors"
                style={{ boxShadow: "var(--shadow-card)" }}
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <span className="font-medium text-[var(--text-primary)]">{d.date}</span>
                    <span className="text-xs text-[var(--text-muted)] ml-2">Run {d.run_id}</span>
                  </div>
                  <a
                    href={d.pdf_url ?? "#"}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-[var(--radius)] text-sm font-medium bg-[var(--primary)] text-white hover:bg-[var(--primary-hover)]"
                  >
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><polyline points="7 10 12 15 17 10" /><line x1="12" y1="15" x2="12" y2="3" /></svg>
                    PDF
                  </a>
                </div>
                <p className="text-sm text-[var(--text-secondary)] mt-2">{d.executive_summary}</p>
                <p className="text-xs text-[var(--text-muted)] mt-1">{d.findings_count} findings</p>
              </li>
            ))}
          </ul>
        )}
    </div>
  );
}
