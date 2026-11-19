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

export type Permission = "audit:read" | "users:manage";

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
