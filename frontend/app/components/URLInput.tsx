"use client";

import { useState } from "react";

interface URLInputProps {
  readonly url: string;
  readonly onURLChange: (url: string) => void;
  readonly onGetPDF?: () => void;
  /** When true, only show the URL input (no submit button). Use on Competitor report page. */
  readonly configOnly?: boolean;
}

export default function URLInput({ url, onURLChange, onGetPDF, configOnly }: URLInputProps) {
  const [isFocused, setIsFocused] = useState(false);

  return (
    <div className="w-full">
      <div
        className="w-full rounded-[var(--radius)] border transition-all duration-150 px-4 py-3 flex items-center gap-3"
        style={{
          background: "var(--bg-card)",
          borderColor: isFocused ? "var(--primary)" : "var(--border)",
          boxShadow: isFocused ? "0 0 0 2px var(--primary-light)" : "var(--shadow-card)",
        }}
      >
        <input
          type="text"
          value={url}
          onChange={e => onURLChange(e.target.value)}
          onFocus={() => setIsFocused(true)}
          onBlur={() => setIsFocused(false)}
          onKeyDown={e => {
            if (e.key === "Enter" && onGetPDF && !configOnly) onGetPDF();
          }}
          placeholder="Enter competitor URL (e.g. openai.com, anthropic.com)"
          className="flex-1 bg-transparent text-sm text-[var(--text-primary)] placeholder-[var(--text-muted)] outline-none min-w-0"
          style={{ caretColor: "var(--text-primary)" }}
        />
        {!configOnly && onGetPDF && (
          <button
            type="button"
            onClick={onGetPDF}
            title="Generate report and send PDF to the email recipients above"
            className="flex-shrink-0 px-4 py-2 rounded-[10px] text-sm font-medium bg-[var(--primary)] text-white hover:bg-[var(--primary-hover)] active:scale-[0.98] transition-all duration-150"
          >
            Send PDF to Recipients
          </button>
        )}
      </div>
    </div>
  );
}
