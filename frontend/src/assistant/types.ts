// Mirrors backend/ask/contracts.py.
import type { Source } from '../types/consensus'

export type Stage = 'context' | 'clarify' | 'generate_sql' | 'web_search' | 'retrieve' | 'execute' | 'draft' | 'review' | 'correct' | 'council' | 'adjudicate' | 'complete'
export type StageStatus = 'running' | 'succeeded' | 'failed' | 'skipped'
export interface StageEvent { stage: Stage; status: StageStatus; ms: number; detail: string }

export interface ConversationState {
  active_datasets: string[]
  applied_filters: string[]
  resolved_definitions: Record<string, string>
  last_query_id: string | null
  last_sql: string | null
  last_question: string | null
  pending_clarification: string | null
}

export interface Issue { severity: 'high' | 'medium' | 'low'; category: string; description: string }
export interface Check { name: string; status: 'passed' | 'failed' | 'warning' | 'skipped'; detail: string }
export interface ModelOption { id: string; family: string; available: boolean; note: string }
export interface ModelCall {
  role: 'analyst' | 'reviewer' | 'adjudicator' | 'council'; purpose: string; endpoint: string
  status: 'ok' | 'failed' | 'timed_out' | 'skipped_budget'; latency_ms: number
  prompt_tokens: number; completion_tokens: number; reasoning_tokens: number; cost_estimate_usd: number | null; error: string | null
}
export interface Verification {
  analyst: 'OK' | 'FAILED' | 'NOT_RUN'
  reviewer: 'APPROVED' | 'REJECTED' | 'DEGRADED' | 'NOT_RUN'
  adjudicator: 'NOT_NEEDED' | 'RESOLVED' | 'CORRECTIVE_QUERY' | 'UNRESOLVED' | 'DEGRADED'
  reviewed: boolean
  degraded_reasons: string[]
  correction_cycles: number
  open_issues: Issue[]
  checks: Check[]
  calls: ModelCall[]
  total_tokens: number
  total_model_calls: number
  sql_attempts: number
  cost_estimate_usd: number | null
}
export type Cell = string | number | boolean | null
export interface ResultPreview {
  columns: string[]; column_types: string[]; rows: Record<string, Cell>[]; row_count: number; truncated: boolean
  from_cache: boolean; statement_id: string | null; runtime_ms: number
}
export interface SourceInfo {
  table: string; updated_at: string | null; kind: 'shared' | 'upload'; row_count: number | null
  date_range: string[] | null; warnings: string[]; expires_at: string | null
}
export type AskStatus = 'ANSWERED' | 'NEEDS_CLARIFICATION' | 'INSUFFICIENT_SCHEMA' | 'UNRESOLVED' | 'BUDGET_EXHAUSTED' | 'ERROR'
export interface CouncilCandidate { label: string; endpoint: string; status: 'executed' | 'failed' | 'abstained'; sql: string | null; row_count: number | null; group: number | null; note: string }
export interface CouncilInfo {
  trigger: 'dispute' | 'requested'; agreement: 'full' | 'partial' | 'conflict' | 'single'; candidates: CouncilCandidate[]
  judge: string; chosen: string | null; rationale: string; disagreement: string | null
}
export interface DocSource { n: number; file: string; section: string; excerpt: string }
export interface CodeInfo { language: 'sql' | 'python' | 'other'; code: string; validation: 'validated' | 'syntax_ok' | 'not_run' | 'failed' | 'untested'; detail: string; destructive: boolean }
export interface AskResponse {
  request_id?: string; from_cache?: boolean
  kind: 'data' | 'web' | 'docs' | 'code' | 'chat'
  status: AskStatus; answer: string; answer_truncated: boolean; clarifying_question: string | null; hypotheses: string[]
  assumptions: string[]; query_id: string | null; sql: string | null; filters: string[]; result: ResultPreview | null
  sources: SourceInfo[]; web_sources?: Source[]; council?: CouncilInfo | null; doc_sources?: DocSource[]; code?: CodeInfo | null; verification: Verification; auth: { mode: 'user' | 'service_principal'; disclosure: string }
  state: ConversationState; events: StageEvent[]; total_ms: number
}

export interface ColumnProfile {
  name: string; type: string; nulls: number; null_rate: number; distinct_approx: number | null
  min: string | null; max: string | null; anomalies: string[]
}
export interface Profile {
  row_count: number; columns: ColumnProfile[]; duplicates: Record<string, number>; date_range: string[] | null
  profiled_at: string; warnings: string[]
}
export interface Dataset {
  dataset: string; kind: 'shared' | 'upload'; conversation_id: string | null; description: string; grain: string
  date_column: string | null; column_descriptions: Record<string, string>; original_names: Record<string, string>
  profile: Profile | null; warnings: string[]; created_at: string | null; refreshed_at: string | null; expires_at: string | null
}
export interface ColumnPlan { name: string; original: string; type: string; notes: string[] }
export interface UploadResult {
  status: 'INGESTED' | 'NEEDS_SHEET'; dataset: string | null; file_name: string; sheet: string | null
  sheets: { name: string; rows: number; columns: number }[]; columns: ColumnPlan[]; row_count: number
  rejected_rows: number[]; rejected_row_count: number; warnings: string[]; profile: Profile | null; expires_at: string | null
}

export interface Turn {
  id: string
  question: string
  stages: StageEvent[]
  response?: AskResponse
  error?: string
  cancelled?: boolean
  datasets: string[]
}
export interface Conversation { id: string; title: string; updatedAt: number; turns: Turn[]; state: ConversationState | null; datasets: string[] }
