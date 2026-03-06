"use client";

import { useState } from "react";

export default function GenerateButton({ isReady }: { isReady: boolean }) {
  const [loading, setLoading] = useState(false);
  const [done, setDone] = useState(false);

  const generate = () => {
    if (!isReady || loading) return;
    console.log("API will be connected here - Generate PDF");
    setLoading(true);
    setTimeout(() => { setLoading(false); setDone(true); setTimeout(() => setDone(false), 4000); }, 2200);
  };

  return (
    <div className="flex flex-col items-center gap-3">
      {done && (
        <div className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-green-50 border border-green-200 text-sm text-green-700 font-medium">
          <svg width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2.5" viewBox="0 0 24 24" strokeLinecap="round" strokeLinejoin="round"><polyline points="20,6 9,17 4,12" /></svg>
          Report generated — ready to download
        </div>
      )}

      <button
        onClick={generate}
        disabled={!isReady || loading}
        className="flex items-center justify-center gap-2 rounded-full text-sm font-medium transition-all duration-150 active:scale-95"
        style={{
          width: "100%",
          maxWidth: "380px",
          height: "48px",
          background: isReady && !loading ? "#111827" : "#f3f4f6",
          color: isReady && !loading ? "white" : "#9ca3af",
          cursor: isReady && !loading ? "pointer" : "not-allowed",
          boxShadow: isReady && !loading ? "0 2px 12px rgba(0,0,0,0.15)" : "none",
        }}
        onMouseEnter={e => { if (isReady && !loading) (e.currentTarget as HTMLElement).style.background = "#374151"; }}
        onMouseLeave={e => { if (isReady && !loading) (e.currentTarget as HTMLElement).style.background = "#111827"; }}
      >
        {loading ? (
          <>
            <svg className="animate-spin" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
              <circle cx="12" cy="12" r="10" strokeOpacity="0.25" />
              <path d="M12 2a10 10 0 0 1 10 10" strokeLinecap="round" />
            </svg>
            Generating report...
          </>
        ) : (
          <>
            <svg width="15" height="15" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24" strokeLinecap="round" strokeLinejoin="round">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
              <polyline points="14,2 14,8 20,8" />
              <line x1="16" y1="13" x2="8" y2="13" />
              <line x1="16" y1="17" x2="8" y2="17" />
            </svg>
            Get PDF Report
          </>
        )}
      </button>

      {!isReady && !loading && (
        <p className="text-xs text-gray-400">Enter a competitor URL above to generate a report</p>
      )}
    </div>
  );
}
