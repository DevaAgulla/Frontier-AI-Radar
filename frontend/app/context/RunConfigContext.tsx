"use client";

import { createContext, useContext, useState, useMemo, type ReactNode } from "react";

interface RunConfigContextValue {
  competitorUrl: string;
  setCompetitorUrl: (url: string) => void;
  recipientEmails: string[];
  setRecipientEmails: (emails: string[]) => void;
}

const RunConfigContext = createContext<RunConfigContextValue | null>(null);

export function RunConfigProvider({ children }: { readonly children: ReactNode }) {
  const [competitorUrl, setCompetitorUrl] = useState("");
  const [recipientEmails, setRecipientEmails] = useState<string[]>([]);
  const value = useMemo(
    () => ({ competitorUrl, setCompetitorUrl, recipientEmails, setRecipientEmails }),
    [competitorUrl, recipientEmails]
  );
  return (
    <RunConfigContext.Provider value={value}>
      {children}
    </RunConfigContext.Provider>
  );
}

export function useRunConfig() {
  const ctx = useContext(RunConfigContext);
  if (!ctx) throw new Error("useRunConfig must be used within RunConfigProvider");
  return ctx;
}
