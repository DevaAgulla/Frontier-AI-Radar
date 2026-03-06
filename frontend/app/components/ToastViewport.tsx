"use client";

import { useToast } from "../context/ToastContext";

function styles(type: "success" | "error" | "info") {
  if (type === "success") return "bg-[var(--success-bg)] text-[var(--success-text)] border-[var(--success-text)]/20";
  if (type === "error") return "bg-[var(--error-bg)] text-[var(--error-text)] border-[var(--error-text)]/20";
  return "bg-[var(--primary-light)] text-[var(--primary)] border-[var(--primary)]/20";
}

export default function ToastViewport() {
  const { toasts, removeToast } = useToast();
  if (toasts.length === 0) return null;

  return (
    <div className="fixed right-4 top-20 z-[100] w-[min(360px,calc(100vw-2rem))] space-y-2">
      {toasts.map((toast) => (
        <div
          key={toast.id}
          className={`rounded-[var(--radius)] border px-3 py-2.5 text-sm shadow-md flex items-start justify-between gap-3 ${styles(toast.type)}`}
          role="status"
        >
          <span>{toast.message}</span>
          <button
            type="button"
            onClick={() => removeToast(toast.id)}
            className="text-xs opacity-70 hover:opacity-100 transition-opacity"
            aria-label="Close notification"
          >
            ✕
          </button>
        </div>
      ))}
    </div>
  );
}

