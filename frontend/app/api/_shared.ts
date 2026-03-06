import type { AgentId, Run, RunStatus } from "@/lib/types";

export function backendAgentToUi(agent: string): AgentId {
  if (agent === "model") return "foundation";
  if (agent === "benchmark") return "huggingface";
  return agent as AgentId;
}

export function uiAgentToBackend(agent: AgentId): string {
  if (agent === "foundation") return "model";
  if (agent === "huggingface") return "benchmark";
  return agent;
}

export function normalizeStatus(status: string): RunStatus {
  if (status === "success" || status === "completed") return "completed";
  if (status === "failure" || status === "failed") return "failed";
  if (status === "running") return "running";
  return "pending";
}

export function buildRunFromBackend(item: any): Run {
  const selected = Array.isArray(item.selected_agents)
    ? item.selected_agents
    : Array.isArray(item.agent_statuses)
      ? item.agent_statuses
          .filter((x: any) => x.status !== "skipped")
          .map((x: any) => x.agent)
      : [];

  const uiAgentIds = selected.map((a: string) => backendAgentToUi(a));

  const sourceUrl = Array.isArray(item.custom_urls) && item.custom_urls.length > 0
    ? item.custom_urls[0]
    : undefined;

  return {
    id: String(item.run_id ?? item.id ?? ""),
    status: normalizeStatus(item.status ?? ""),
    started_at: item.started_at ?? "",
    finished_at: item.finished_at ?? undefined,
    mode: item.mode ?? "full",
    source_url: sourceUrl,
    agent_ids: uiAgentIds,
    recipient_emails: Array.isArray(item.recipient_emails) ? item.recipient_emails : [],
    findings_count: Number(item.findings_count || 0),
    pdf_available: Boolean(item.pdf_available),
    pdf_path: item.pdf_path || undefined,
    user_name: item.user_name ?? null,
    agent_statuses: Array.isArray(item.agent_statuses)
      ? item.agent_statuses.map((s: any) => ({
          agent: s.agent,
          label: s.label,
          status: s.status,
          findings_count: Number(s.findings_count || 0),
        }))
      : [],
  };
}

