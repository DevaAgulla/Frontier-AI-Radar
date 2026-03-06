"use client";

import BackButton from "../components/BackButton";

export default function ReportsPage() {
  return (
    <div className="min-h-screen px-4 py-6 md:px-6 lg:px-8">
        <div className="flex items-center gap-4 mb-2">
          <BackButton href="/" />
          <h1 className="text-2xl font-semibold text-[var(--text-primary)]">Reports</h1>
        </div>
        <p className="text-sm text-[var(--text-secondary)] mb-6">Coming soon.</p>
    </div>
  );
}
