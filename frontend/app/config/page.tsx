"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import BackButton from "../components/BackButton";
import URLInput from "../components/URLInput";
import EmailRecipients from "../components/EmailRecipients";
import { useRunConfig } from "../context/RunConfigContext";
import { useToast } from "../context/ToastContext";
import { useAuth } from "../context/AuthContext";
import { api } from "@/lib/api";

export default function CompetitorReportPage() {
  const { competitorUrl, setCompetitorUrl, recipientEmails, setRecipientEmails } = useRunConfig();
  const { user } = useAuth();
  const router = useRouter();
  const { pushToast } = useToast();
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async () => {
    const url = competitorUrl.trim();
    if (!url) {
      pushToast("Please provide competitor URL.", "error");
      return;
    }
    setSubmitting(true);
    const res = await api.triggerRun({
      agent_ids: ["competitor"],
      ...(user ? { user_id: user.id } : { recipient_emails: recipientEmails }),
      ...(user && recipientEmails.length > 0 ? { extra_recipients: recipientEmails } : {}),
      urls: [url],
      url_mode: "custom",
      async_run: true,
    });
    setSubmitting(false);

    if (res.error) {
      pushToast(res.error, "error");
      return;
    }

    const runId = res.data?.id || "latest";
    pushToast(`Competitor run ${runId} started. Tracking in Runs...`, "success");
    router.push(`/runs?highlight=${encodeURIComponent(String(runId))}`);
  };

  return (
    <div className="min-h-full min-w-0 max-w-full py-4">
      <div className="flex items-center gap-4 mb-2">
        <BackButton href="/" label="Back" />
        <h1 className="text-2xl font-semibold text-[var(--text-primary)]">Competitor report</h1>
      </div>
      <p className="text-sm text-[var(--text-secondary)] mb-6">
        Submit here to run only the competitor agent for this URL. Recipients are optional.
      </p>

      <div className="flex flex-col gap-6 max-w-2xl min-w-0">
        <div>
          <h2 className="text-sm font-semibold text-[var(--text-primary)] mb-2">Competitor URL</h2>
          <URLInput url={competitorUrl} onURLChange={setCompetitorUrl} configOnly />
        </div>
        <div>
          <h2 className="text-sm font-semibold text-[var(--text-primary)] mb-2">Recipients (optional)</h2>
          <EmailRecipients emails={recipientEmails} onEmailsChange={setRecipientEmails} />
        </div>
        <div className="pt-2">
          <button
            type="button"
            onClick={handleSubmit}
            disabled={submitting}
            className="inline-flex items-center gap-2 px-5 py-2.5 rounded-[var(--radius)] text-sm font-medium bg-[var(--primary)] text-white hover:bg-[var(--primary-hover)] transition-all shadow-md"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <polygon points="5 3 19 12 5 21 5 3" />
            </svg>
            {submitting ? "Submitting..." : "Submit"}
          </button>
        </div>
      </div>
    </div>
  );
}
