/** API 类型定义，与后端 Pydantic schema 对齐。 */

export type Severity = "low" | "medium" | "high" | "critical";
export type AlertStatus =
  | "new"
  | "triaging"
  | "triaged"
  | "confirmed_true"
  | "incident_created"
  | "confirmed_false"
  | "triage_failed";
export type Classification =
  | "true_positive"
  | "false_positive"
  | "suspicious"
  | "needs_investigation";

export interface User {
  id: string;
  email: string;
  display_name: string;
  is_active: boolean;
  roles: string[];
  last_login_at: string | null;
  created_at: string;
}

export interface Alert {
  id: string;
  source: string;
  external_id: string;
  title: string;
  description: string | null;
  severity: Severity;
  status: AlertStatus;
  alert_type: string;
  src_ip: string | null;
  dst_ip: string | null;
  src_host: string | null;
  user_account: string | null;
  occurred_at: string;
  confirmed_as: string | null;
  confirm_reason: string | null;
  degraded: boolean;
  created_at: string;
}

export interface AlertPage {
  items: Alert[];
  total: number;
  offset: number;
  limit: number;
}

export interface Evidence {
  source: string;
  detail: string;
}

export interface RecommendedAction {
  action: string;
  target: string | null;
  reason: string;
}

export interface TriageResult {
  id: string;
  run_id: string;
  classification: Classification;
  severity: Severity;
  confidence: number;
  reasoning: string;
  evidence: Evidence[];
  recommended_actions: RecommendedAction[];
  degraded: boolean;
  model_key: string;
  prompt_version: string;
  created_at: string;
}

export interface TriageStep {
  step_no: number;
  kind: string;
  thought: string | null;
  tool: string | null;
  tool_args: Record<string, unknown> | null;
  tool_result: Record<string, unknown> | null;
  tool_error: string | null;
}

export interface TriageRun {
  id: string;
  status: string;
  model_key: string;
  prompt_version: string;
  total_prompt_tokens: number;
  total_completion_tokens: number;
  total_cost_usd: number;
  step_count: number;
  started_at: string;
  finished_at: string | null;
}

export interface TriageReport {
  result: TriageResult | null;
  run: TriageRun | null;
  steps: TriageStep[];
}

export interface Incident {
  id: string;
  title: string;
  description: string | null;
  severity: Severity;
  status: string;
  assigned_to: string | null;
  source_alert_id: string | null;
  opened_by: string;
  closed_at: string | null;
  close_summary: string | null;
  reopened_count: number;
  created_at: string;
  updated_at: string;
}

export interface Task {
  id: string;
  incident_id: string;
  title: string;
  description: string | null;
  status: string;
  assignee: string | null;
  due_at: string | null;
  blocked_reason: string | null;
  completed_at: string | null;
  created_at: string;
}

export interface Comment {
  id: string;
  incident_id: string | null;
  task_id: string | null;
  body: string;
  author_id: string;
  created_at: string;
}

export interface KbDocument {
  id: string;
  title: string;
  status: "pending" | "indexed" | "failed";
  chunk_count: number;
  size_bytes: number;
  sha256: string;
  error: string | null;
  created_at: string;
}

export interface AskResponse {
  answer: string;
  citations: {
    document_id: string;
    document_title: string;
    heading: string | null;
    score: number;
  }[];
  model_key: string;
  degraded: boolean;
}

export interface Dashboard {
  alerts_total: number;
  alerts_by_status: { status: string; count: number }[];
  alerts_by_severity: { severity: string; count: number }[];
  noise_reduction_rate: number | null;
  ai_adoption_rate: number | null;
  triaged_pending_confirmation: number;
  mttr_hours: number | null;
  llm_cost_usd_total: number;
  llm_cost_by_day: { day: string; cost_usd: number; calls: number }[];
  llm_calls_total: number;
}

export interface ApiKey {
  id: string;
  name: string;
  key_prefix: string;
  scopes: string[];
  rate_limit_per_min: number;
  is_active: boolean;
  expires_at: string | null;
  created_at: string;
}

export interface AuditLog {
  id: number;
  actor_id: string | null;
  actor_type: string;
  action: string;
  resource_type: string;
  resource_id: string | null;
  detail: Record<string, unknown>;
  ip: string | null;
  request_id: string | null;
  created_at: string;
}

export interface ActionApproval {
  id: string;
  alert_id: string | null;
  action: string;
  target: string | null;
  reason: string;
  status: string;
  proposed_by: string;
  approved_l1_by: string | null;
  approved_l2_by: string | null;
  rejected_by: string | null;
  rejected_reason: string | null;
  executed_by: string | null;
  executed_at: string | null;
  execution_mode: string | null;
  execution_result: Record<string, unknown> | null;
  created_at: string;
}
