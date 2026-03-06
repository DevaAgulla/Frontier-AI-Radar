/**
 * API client for Frontier AI Radar. All endpoints use relative /api/* paths.
 * Replace baseUrl with your backend URL when integrating.
 */

import type {
  AgentId,
  ApiResponse,
  Digest,
  Finding,
  Run,
  CompareResult,
  SchedulerSubscriber,
  Source,
  TriggerRunPayload,
  SendDigestPayload,
} from "./types";

const BASE = "";

async function request<T>(path: string, options?: RequestInit): Promise<ApiResponse<T>> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...options?.headers },
    ...options,
  });
  const json = await res.json().catch(() => ({}));
  if (!res.ok) {
    return { error: json.error ?? res.statusText, status: res.status };
  }
  return { data: json.data ?? json, status: res.status };
}

export const api = {
  /** GET /api/dashboard — last run + top 10 findings */
  getDashboard: () =>
    request<{ last_run: Run | null; top_findings: Finding[] }>("/api/dashboard"),

  /** GET /api/sources */
  getSources: () => request<Source[]>("/api/sources"),

  /** POST /api/sources — body: { url, agent_id, label?, source_type? } */
  createSource: (body: { url: string; agent_id: AgentId; label?: string; source_type?: "rss" | "webpage" }) =>
    request<Source>("/api/sources", { method: "POST", body: JSON.stringify(body) }),

  /** GET /api/runs — query: status?, start_date?, end_date? */
  getRuns: (params?: { status?: string; start_date?: string; end_date?: string }) => {
    const q = new URLSearchParams();
    if (params?.status) q.set("status", params.status);
    if (params?.start_date) q.set("start_date", params.start_date);
    if (params?.end_date) q.set("end_date", params.end_date);
    return request<Run[]>("/api/runs" + (q.toString() ? `?${q}` : ""));
  },

  /** GET /api/runs/[id] */
  getRun: (id: string) => request<Run>(`/api/runs/${id}`),

  /** POST /api/runs — trigger run. body: TriggerRunPayload */
  triggerRun: (body: TriggerRunPayload) =>
    request<Run>("/api/runs", { method: "POST", body: JSON.stringify(body) }),

  /** GET /api/findings — query: agent_id?, entity?, category?, run_id?, limit? */
  getFindings: (params?: {
    agent_id?: AgentId;
    entity?: string;
    category?: string;
    run_id?: string;
    limit?: number;
  }) => {
    const q = new URLSearchParams();
    if (params?.agent_id) q.set("agent_id", params.agent_id);
    if (params?.entity) q.set("entity", params.entity);
    if (params?.category) q.set("category", params.category);
    if (params?.run_id) q.set("run_id", params.run_id);
    if (params?.limit) q.set("limit", String(params.limit));
    return request<Finding[]>("/api/findings" + (q.toString() ? `?${q}` : ""));
  },

  /** GET /api/digests — query: from_date?, to_date?, q? */
  getDigests: (params?: { from_date?: string; to_date?: string; q?: string }) => {
    const q = new URLSearchParams();
    if (params?.from_date) q.set("from_date", params.from_date);
    if (params?.to_date) q.set("to_date", params.to_date);
    if (params?.q) q.set("q", params.q);
    return request<Digest[]>("/api/digests" + (q.toString() ? `?${q}` : ""));
  },

  /** POST /api/digests/send — send digest email. body: SendDigestPayload */
  sendDigest: (body: SendDigestPayload) =>
    request<{ sent_at: string; message: string }>("/api/digests/send", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  /** POST /api/scheduler/subscribe — register email for daily job */
  schedulerSubscribe: (body: { email: string; name?: string }) =>
    request<{ id: number; email: string; name: string; schedule_time: string; timezone: string; message: string }>(
      "/api/scheduler/subscribe",
      { method: "POST", body: JSON.stringify(body) }
    ),

  /** GET /api/scheduler/subscribers */
  getSchedulerSubscribers: () =>
    request<{ schedule_time: string; timezone: string; subscribers: SchedulerSubscriber[] }>(
      "/api/scheduler/subscribers"
    ),

  /** GET /api/users */
  getUsers: () => request<Array<{ id: number; name: string; email: string }>>("/api/users"),

  /** PUT /api/sources/:id — toggle active status */
  toggleSource: (id: string | number, isActive: boolean) =>
    request<Source>(`/api/sources/${id}`, {
      method: "PUT",
      body: JSON.stringify({ is_active: isActive }),
    }),

  /** DELETE /api/sources/:id — remove a source */
  deleteSource: (id: string | number) =>
    request<{ ok: boolean }>(`/api/sources/${id}`, { method: "DELETE" }),

  /** POST /api/compare */
  compareRuns: (body: {
    date_a: string;
    date_b: string;
    run_a_id?: number;
    run_b_id?: number;
  }) => request<CompareResult>("/api/compare", { method: "POST", body: JSON.stringify(body) }),
};
