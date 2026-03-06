/**
 * Shared domain types for Frontier AI Radar (Daily Multi-Agent Intelligence System).
 * Aligns with spec: agents, findings, runs, digests, sources.
 */

export type AgentId = "competitor" | "foundation" | "research" | "huggingface";

export type RunStatus = "completed" | "running" | "failed" | "pending";

export type FindingCategory = "release" | "research" | "benchmark" | "api" | "pricing" | "safety";

export interface Finding {
  id: string;
  title: string;
  date_detected: string;
  source_url: string;
  publisher: string;
  agent_id: AgentId;
  category: FindingCategory;
  summary_short: string;
  summary_long: string;
  why_it_matters: string;
  evidence: string;
  confidence: number;
  tags: string[];
  entities: string[];
  impact_score?: number;
}

export interface Source {
  id: string | number;
  url: string;
  agent_id: AgentId;
  label?: string;
  source_type?: "rss" | "webpage";
  is_active?: boolean;
  is_default?: boolean;
  crawl_frequency?: "daily" | "weekly";
  rate_limit_per_min?: number;
  created_at: string;
  updated_at: string;
}

export interface AgentRunStatus {
  agent: "research" | "competitor" | "model" | "benchmark";
  label: string;
  status: RunStatus | "skipped";
  findings_count: number;
}

export interface Run {
  id: string;
  status: RunStatus;
  started_at: string;
  finished_at?: string;
  mode?: string;
  source_url?: string;
  agent_ids: AgentId[];
  recipient_emails: string[];
  findings_count?: number;
  pdf_available?: boolean;
  pdf_path?: string;
  user_name?: string | null;
  agent_statuses?: AgentRunStatus[];
  error_message?: string;
  agent_errors?: { agent_id: AgentId; message: string }[];
}

export interface Digest {
  id: string;
  run_id: string;
  date: string;
  executive_summary: string;
  findings_count: number;
  pdf_url?: string;
  created_at: string;
}

export interface TriggerRunPayload {
  agent_ids: AgentId[];
  user_id?: number;
  recipient_emails?: string[];
  extra_recipients?: string[];
  urls?: string[];
  url_mode?: "default" | "append" | "custom";
  since_days?: number;
  async_run?: boolean;
}

export interface SendDigestPayload {
  run_id: string;
  recipient_emails: string[];
  include_pdf_attachment?: boolean;
}

export interface ApiResponse<T> {
  data?: T;
  error?: string;
  status: number;
}

export interface SchedulerSubscriber {
  id: number;
  name: string;
  email: string;
  subscribed_at?: string;
}

export interface CompareSummary {
  baseline_findings: number;
  candidate_findings: number;
  added_count: number;
  removed_count: number;
  impact_changes_count: number;
  major_highlights: string[];
}

export interface CompareDelta {
  agent: string;
  label: string;
  before: number;
  after: number;
  delta: number;
}

export interface CompareFinding {
  id?: string;
  title: string;
  agent: string;
  impact_score?: number;
  impact_before?: number;
  impact_after?: number;
  delta?: number;
  source_url?: string;
  category?: string;
  summary?: string;
}

export interface CompareResult {
  status: "running" | "completed";
  message?: string;
  date_a: string;
  date_b: string;
  user_a_id?: number | null;
  user_b_id?: number | null;
  mode?: string;
  pending_run_ids?: number[];
  baseline_run_id?: number;
  candidate_run_id?: number;
  summary?: CompareSummary;
  agent_deltas?: CompareDelta[];
  section_comparison?: Array<{
    section: string;
    date_a_summary: string;
    date_b_summary: string;
    compared_result: string;
    major_updates: string[];
  }>;
  added_findings?: CompareFinding[];
  removed_findings?: CompareFinding[];
  impact_changed_findings?: CompareFinding[];
}
