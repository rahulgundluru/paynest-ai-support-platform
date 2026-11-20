// Ticket intake, pipeline runs and AI management (mirrors backend/app/api/v1/intake.py and ai.py).

export type StepStatus = "pending" | "running" | "done" | "skipped" | "blocked" | "failed" | "review";

export interface PipelineStep {
  key: string;
  label: string;
  description: string;
  status: StepStatus;
  summary: string | null;
  details: Record<string, unknown>;
  started_at: string | null;
  duration_ms: number | null;
  cost_usd: string | null;
}

export interface PipelineRun {
  id: string;
  ticket_ref: string | null;
  trigger: "create" | "rerun";
  status: "running" | "completed" | "failed";
  ai_enabled: boolean;
  total_cost_usd: string;
  error: string | null;
  started_at: string;
  finished_at: string | null;
  steps: PipelineStep[];
}

export interface CreatedTicket {
  ticket_ref: string;
  run: PipelineRun;
}

export interface AiStatus {
  state: "on" | "off" | "no_key" | "no_model" | "not_configured";
  note: string;
  enabled: boolean;
  classifier_model: string | null;
  drafting_model: string | null;
  provider?: string;
  key_configured?: boolean;
  daily_budget_usd?: number;
  ticket_budget_usd?: number;
  privacy?: { data_collection: string; zdr: boolean; note: string };
}

export interface AiWindow {
  calls: number;
  successful: number;
  cost_usd: number;
  tickets: number;
}

export interface AiModelRow {
  model: string;
  operation: string;
  calls: number;
  successful: number;
  cost_usd: number;
  input_tokens: number;
  output_tokens: number;
  latency_ms_p50: number;
  latency_ms_p95: number;
  avg_cost_usd: number | null;
}

export interface AiOverview {
  status: AiStatus;
  window_days: number;
  today: AiWindow & { budget_usd: number; budget_remaining_usd: number };
  month: AiWindow;
  period: AiWindow & {
    input_tokens: number;
    output_tokens: number;
    latency_ms_p50: number;
    latency_ms_p95: number;
    provider_reported_cost_calls: number;
    avg_cost_per_ticket_usd: number | null;
    max_cost_per_ticket_usd: number | null;
    avg_cost_per_draft_usd: number | null;
    draft_target_usd: number;
  };
  by_day: { date: string; calls: number; failed: number; cost_usd: number }[];
  by_model: AiModelRow[];
  guardrails: {
    pii_blocked_calls: number;
    schema_failures: number;
    provider_errors: Record<string, number>;
    budget_stops: number;
    injection_skips: number;
    skipped_steps: { step: string; reason: string; count: number }[];
    drafts_passed_validation: number;
    drafts_failed_validation: number;
  };
  runs: { total: number; completed: number; failed: number; avg_duration_s: number | null; avg_cost_usd: number | null };
  projection: {
    avg_cost_per_ticket_usd: number;
    tickets_per_month: number;
    monthly_model_cost_usd: number;
    budget_cap_usd: number;
    share_of_cap: number;
    basis: string;
    sample_tickets: number;
  } | null;
  top_tickets: { ticket: string; cost_usd: number; calls: number }[];
}

export interface AiCall {
  id: number;
  created_at: string;
  ticket: string | null;
  operation: string;
  provider: string;
  upstream_provider: string | null;
  model: string;
  prompt_version: string | null;
  input_tokens: number;
  output_tokens: number;
  latency_ms: number;
  cost_usd: number | null;
  cost_source: string | null;
  success: boolean;
  error: string | null;
  pipeline_run_id: string | null;
}

export interface AiSetting {
  key: string;
  label: string;
  kind: "bool" | "float" | "model";
  value: boolean | number | string | null;
  default: boolean | number | string | null;
  minimum: number | null;
  maximum: number | null;
}

export interface AiConfigView {
  status: AiStatus;
  settings: AiSetting[];
  can_manage: boolean;
  credentials: string;
}

export interface AiCatalogueModel {
  id: string;
  name: string;
  context_length: number | null;
  input_usd_per_mtok: number;
  output_usd_per_mtok: number;
}

export interface TicketAiCost {
  ticket: string;
  total_cost_usd: number;
  calls: number;
  by_operation: {
    operation: string;
    calls: number;
    successful: number;
    cost_usd: number;
    input_tokens: number;
    output_tokens: number;
    latency_ms: number;
  }[];
  runs: { id: string; trigger: string; status: string; started_at: string; cost_usd: number }[];
  draft_target_usd: number;
}

export interface AiAccount {
  is_free_tier: boolean | null;
  limit_usd: number | null;
  limit_remaining_usd: number | null;
  usage_usd: number | null;
  usage_daily_usd: number | null;
  usage_monthly_usd: number | null;
}

/** USD with enough precision for per-call model costs (fractions of a cent). */
export function formatUsd(value: number | string | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  const n = typeof value === "string" ? Number(value) : value;
  if (!Number.isFinite(n)) return "—";
  if (n === 0) return "$0.00";
  if (Math.abs(n) < 0.01) return `$${n.toFixed(5)}`;
  return `$${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

export function formatMs(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "—";
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)} s` : `${ms} ms`;
}
