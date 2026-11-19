/** Types mirroring the backend Pydantic schemas (app/schemas). Keep in sync with /api/openapi.json. */

export type RoleName =
  | "agent_l1"
  | "agent_l2"
  | "engineer_l3"
  | "support_lead"
  | "kb_owner"
  | "dpo"
  | "finance_viewer"
  | "admin";

export type Region = "IN" | "UAE";

export type Permission =
  | "audit:read"
  | "users:manage"
  | "tickets:read"
  | "customers:read"
  | "sla:read"
  | "ingestion:run"
  | "ingestion:read";

export interface Sla {
  applicable: boolean;
  not_applicable_reason: string | null;
  template_version: string | null;
  tier: string | null;
  priority: string | null;
  first_response_target_h: string | null;
  resolution_target_h: string | null;
  first_response_due_at: string | null;
  resolution_due_at: string | null;
  first_response_hours: string | null;
  resolution_hours: string | null;
  first_response_breached: boolean | null;
  resolution_breached: boolean | null;
  severity_multiplier: string | null;
  credit_pct: string | null;
  credit_usd: string | null;
  rule_version: string;
}

export interface TicketSummary {
  id: string;
  external_id: string | null;
  channel: string;
  customer_id: string | null;
  customer_name: string | null;
  customer_tier: string | null;
  region: string | null;
  subject_redacted: string | null;
  priority: string | null;
  customer_category: string | null;
  first_queue: string | null;
  final_queue: string | null;
  status: string | null;
  created_at: string;
  reassignment_count: number;
  reopen_count: number;
  in_payroll_window: boolean;
  ingestion_status: string;
  pii_entity_count: number;
  sla_resolution_breached: boolean | null;
}

export interface TicketDetail extends TicketSummary {
  customer_resolution: string;
  region_source: string | null;
  partner_id: string | null;
  body_redacted: string | null;
  language_hint: string | null;
  final_category_label: string | null;
  first_response_at: string | null;
  resolved_at: string | null;
  review_reasons: string[];
  attributes: Record<string, unknown>;
  source_file: string;
  source_record_index: number;
  messages: { seq: number; author_type: string; sent_at: string | null; body_redacted: string }[];
  events: { seq: number; event_type: string; occurred_at: string; actor: string | null; data: Record<string, unknown> }[];
  pii_detections: {
    field: string;
    entity_type: string;
    token: string;
    method: string;
    confidence: number;
    checksum_valid: boolean | null;
  }[];
  normalization: { field: string; original_value: string | null; normalized_value: string | null; rule: string }[];
  sla: Sla | null;
}

export interface IngestionBatch {
  id: string;
  started_at: string;
  finished_at: string | null;
  status: string;
  source_commit: string | null;
  summary: {
    reference?: Record<string, number>;
    sources?: Record<string, Record<string, number>>;
    totals?: Record<string, number>;
    review_reasons?: Record<string, number>;
    pii?: Record<string, Record<string, number>>;
  };
}

export interface User {
  id: string;
  email: string;
  full_name: string;
  roles: RoleName[];
  regions: Region[];
  permissions: Permission[];
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  expires_at: string;
  user: User;
}

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface AuditLogEntry {
  id: number;
  occurred_at: string;
  actor_user_id: string | null;
  action: string;
  entity_type: string | null;
  entity_id: string | null;
  region: string | null;
  request_id: string | null;
  details: Record<string, unknown>;
}

export interface ReadyResponse {
  status: "ok" | "unavailable";
  checks: Record<string, string | null>;
}

export interface ApiErrorBody {
  error: { code: string; message: string; request_id: string | null };
}
