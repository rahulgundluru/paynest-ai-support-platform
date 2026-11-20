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
  | "ingestion:read"
  | "knowledge:read"
  | "knowledge:manage"
  | "incidents:manage"
  | "tickets:process"
  | "approvals:read"
  | "approvals:edit"
  | "approvals:decide"
  | "pii:reveal"
  | "settings:read"
  | "settings:manage"
  | "evaluations:read"
  | "evaluations:run";

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

export interface KnowledgeDocument {
  id: string;
  doc_type: string;
  title: string;
  region: string;
  topic: string | null;
  owner: string | null;
  source_file: string;
  last_reviewed: string | null;
  status: string;
  version_count: number;
  in_force_today: boolean;
  content_complete: boolean;
}

export interface KnowledgeVersion {
  id: string;
  version: number;
  content_complete: boolean;
  effective_from: string | null;
  effective_to: string | null;
  validity_source: string;
  superseded_by: string | null;
  approval_status: string;
  indexed_at: string | null;
  content: string;
}

export interface KnowledgeDocumentDetail extends KnowledgeDocument {
  metadata: Record<string, unknown>;
  versions: KnowledgeVersion[];
}

export interface SearchHit {
  rank: number;
  document_id: string;
  doc_type: string;
  title: string;
  version: number;
  heading: string | null;
  text: string;
  content_complete: boolean;
  effective_from: string | null;
  effective_to: string | null;
  validity_source: string;
  score: number;
}

export interface SearchResponse {
  retrieval_id: string;
  query_redacted: string;
  mode: string;
  hits: SearchHit[];
}

export interface RateInForce {
  rule_id: string;
  topic: string;
  title: string;
  value: string;
  in_force_since: string | null;
  in_force_until: string | null;
  source: string;
}

export interface Incident {
  id: string;
  kind: "resubmission" | "incident";
  customer_id: string | null;
  customer_name: string | null;
  region: string | null;
  master_external_id: string | null;
  owner_queue: string | null;
  category: string | null;
  rule_id: string;
  first_ticket_at: string;
  declared_at: string;
  status: string;
  ticket_count: number;
}

export interface IncidentLink {
  ticket_id: string;
  external_id: string | null;
  channel: string;
  created_at: string;
  subject_redacted: string | null;
  role: string;
  rule_id: string;
  reason: string;
  confidence: number;
  active: boolean;
  manual: boolean;
}

export interface IncidentDetail extends Incident {
  links: IncidentLink[];
}

export interface Classification {
  id: string;
  status: string;
  provider: string;
  model: string | null;
  prompt_version: string;
  category: string | null;
  subcategory: string | null;
  intent: string | null;
  priority: string | null;
  language: string | null;
  is_injection: boolean | null;
  confidence: number | null;
  requires_human: boolean;
  explanation: string | null;
  error: string | null;
  created_at: string;
}

export interface RoutingDecision {
  lane: string;
  queue: string;
  support_level: string;
  rule_id: string;
  rule_version: string;
  reason: string;
  requires_approval: boolean;
  inputs: Record<string, unknown>;
  decided_at: string;
}

export interface TicketRouting {
  classification: Classification | null;
  routing: RoutingDecision | null;
  incidents: Incident[];
}

export interface ApprovalSummary {
  id: string;
  ticket_id: string;
  ticket_external_id: string | null;
  region: string | null;
  status: string;
  lane: string;
  queue: string;
  rule_id: string;
  escalation_reason: string;
  summary: string;
  sla_breached: boolean | null;
  draft_source: string;
  validation_passed: boolean | null;
  created_at: string;
  decided_at: string | null;
}

export interface ValidationCheck {
  name: string;
  passed: boolean;
  detail: string;
}

export interface ApprovalDetail extends ApprovalSummary {
  evidence: {
    summary: string;
    ticket: Record<string, string | null>;
    customer: { id: string; name: string; tier: string; region: string } | null;
    sla: Record<string, string | boolean | null> | null;
    routing: { lane: string; queue: string; rule_id: string; reason: string } | null;
    incidents: { kind: string; owner_queue: string; role: string }[];
    knowledge_in_force: {
      document_id: string;
      version: number;
      title: string;
      excerpt: string;
      content_complete: boolean;
      effective_from: string | null;
      effective_to: string | null;
    }[];
    statutory_rates_in_force: { rule_id: string; title: string; value: string }[];
    pii_tokens: string[];
    injection_signals: string[];
    suggested_response: string | null;
    suggested_response_note: string;
  };
  draft_text: string | null;
  validation: { passed: boolean; validator_version: string; checks: ValidationCheck[] } | null;
  events: { action: string; from_status: string | null; to_status: string; note: string | null; occurred_at: string }[];
  requires_second_person: boolean;
}

export interface RevealResponse {
  token: string;
  entity_type: string;
  value: string;
  revealed_at: string;
  retention_until: string;
}

export interface Customer {
  customer_id: string;
  name: string;
  tier: string;
  region: string;
  monthly_fee_usd: string;
  employees_paid: number | null;
  ticket_count: number;
  sla_breaches: number;
  credits_usd: string;
}
