"use client";

import { useState } from "react";

interface EmailRecipientsProps {
  readonly emails: readonly string[];
  readonly onEmailsChange: (emails: string[]) => void;
}

function isValidEmail(value: string): boolean {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value.trim());
}

export default function EmailRecipients({ emails, onEmailsChange }: EmailRecipientsProps) {
  const [inputValue, setInputValue] = useState("");
  const [isFocused, setIsFocused] = useState(false);

  const handleAdd = () => {
    const trimmed = inputValue.trim();
    if (!trimmed) return;
    if (!isValidEmail(trimmed)) return;
    if (emails.includes(trimmed)) return;
    onEmailsChange([...emails, trimmed]);
    setInputValue("");
  };

  const handleRemove = (email: string) => {
    onEmailsChange(emails.filter((e) => e !== email));
  };

  return (
    <div className="w-full space-y-3">
      <div
        className="w-full rounded-[var(--radius)] border transition-all duration-150 px-4 py-3 flex items-center gap-3"
        style={{
          background: "var(--bg-card)",
          borderColor: isFocused ? "var(--primary)" : "var(--border)",
          boxShadow: isFocused ? "0 0 0 2px var(--primary-light)" : "var(--shadow-card)",
        }}
      >
        <span className="flex-shrink-0 text-[var(--text-secondary)]" aria-hidden title="Email recipients for the PDF">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z" />
            <polyline points="22,6 12,13 2,6" />
          </svg>
        </span>
        <input
          type="email"
          value={inputValue}
          onChange={(e) => setInputValue(e.target.value)}
          onFocus={() => setIsFocused(true)}
          onBlur={() => setIsFocused(false)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              handleAdd();
            }
          }}
          placeholder="Enter email address to receive the PDF"
          title="Add addresses that will receive the report PDF"
          className="flex-1 bg-transparent text-sm text-[var(--text-primary)] placeholder-[var(--text-muted)] outline-none min-w-0"
          style={{ caretColor: "var(--text-primary)" }}
        />
        <button
          type="button"
          onClick={handleAdd}
          disabled={!inputValue.trim() || !isValidEmail(inputValue.trim())}
          className="flex-shrink-0 w-9 h-9 rounded-[var(--radius)] border border-[var(--border)] bg-[var(--bg-card)] text-[var(--text-secondary)] flex items-center justify-center hover:border-[var(--primary)] hover:bg-[var(--primary-light)] disabled:opacity-40 disabled:cursor-not-allowed transition-all duration-150"
          title="Add this email to recipients"
          aria-label="Add email"
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
            <line x1="12" y1="5" x2="12" y2="19" />
            <line x1="5" y1="12" x2="19" y2="12" />
          </svg>
        </button>
      </div>

      {emails.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {emails.map((email) => (
            <span
              key={email}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-[var(--radius)] bg-[var(--primary-light)] text-[var(--text-primary)] text-sm border border-[var(--border)]"
            >
              {email}
              <button
                type="button"
                onClick={() => handleRemove(email)}
                className="text-[var(--text-muted)] hover:text-[var(--text-primary)] rounded p-0.5 hover:bg-[var(--border)] transition-colors"
                title="Remove this recipient"
                aria-label={`Remove ${email}`}
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <line x1="18" y1="6" x2="6" y2="18" />
                  <line x1="6" y1="6" x2="18" y2="18" />
                </svg>
              </button>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
