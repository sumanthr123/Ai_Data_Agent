// Mirrors backend/schemas.py.
export type Mode = 'live' | 'demo'
export type View = 'consensus' | 'arena'
/** Per-model stages; each appears only once it actually runs (route-specific). */
export type Stage = 'plan' | 'execute' | 'answer'
export type PipelineStage = 'route' | 'search' | 'compare' | 'validate' | 'write'
/** 'pending' is client-side (expected but not started); "not applicable" stages are simply never shown. */
export type StageStatus = 'pending' | 'running' | 'succeeded' | 'failed' | 'skipped'
export type Route = 'data' | 'web' | 'general' | 'arithmetic'
export type Layer = 'bronze' | 'silver' | 'gold' | 'other'

export interface ModelInfo { id: string; name: string; provider: string; color: string }
export type Row = Record<string, string | number | null>

export interface ResultSet {
  columns: string[]
  column_types: string[]
  rows: Row[]
  row_count: number
  truncated: boolean
  dimension: string | null
  measures: string[]
}

export interface ModelResult {
  lane: number
  model: ModelInfo
  needs_data: boolean
  needs_web: boolean
  search_query: string
  sql: string
  reasoning: string
  answer: string
  confidence: number
  result: ResultSet | null
  result_hash: string | null
  latency_ms: number
  warehouse_ms: number
  tokens: number
  tokens_per_second: number
  cost_usd: number | null
  statement_id: string | null
  error: string | null
  issues: string[]
  reused_query: boolean
}

export interface Agreement { kind: 'match' | 'partial' | 'conflict' | 'different' | 'incomplete' | 'none' | 'text' | 'single'; message: string }
export interface Check { id: string; label: string; status: 'passed' | 'warning' | 'failed' | 'not_run'; detail: string }
export interface DataContext { tables: string[]; coverage: string; filters: string; freshness: string; currency: string }
export interface Source { n: number; title: string; publisher: string; url: string; published: string; retrieved_at: string }
export interface ModelUsage { model: string; purpose: string; latency_ms: number; prompt_tokens: number; completion_tokens: number; status: 'ok' | 'failed' | 'timed_out' }
export interface RunMetrics { total_ms: number; calls: ModelUsage[]; queries_executed: number; queries_reused: number }
export interface Kpi { label: string; value: string; delta: number; spark: number[] }
export interface LineageNode { id: string; label: string; kind: Layer | 'warehouse' | 'output' }
export interface Lineage { nodes: LineageNode[]; edges: [string, string][]; statement_id: string | null; runtime_ms: number; bytes_scanned: number | null }

export interface Consensus {
  winner_lane: number
  lead_lane: number
  reliability: number
  agreement: Agreement
  groups: number[][]
  narrative: string
  insights: string[]
  sql: string
  result: ResultSet | null
  kpis: Kpi[]
  lineage: Lineage | null
  sources: Source[]
  mode: Mode
  route: Route
  checks: Check[]
  limitations: string[]
  data_context: DataContext | null
  metrics: RunMetrics | null
  strict_format: boolean
}

export type StreamEvent =
  | { type: 'lane'; lane: number; model: ModelInfo; stage: Stage; status: Exclude<StageStatus, 'pending'>; detail: string; route: Route | null }
  | { type: 'pipeline'; stage: PipelineStage; status: Exclude<StageStatus, 'pending'>; detail: string }
  | { type: 'lane_result'; result: ModelResult }
  | { type: 'arbiter'; status: 'running' | 'done'; detail: string }
  | { type: 'consensus'; consensus: Consensus }
  | { type: 'rewrite'; question: string }
  | { type: 'error'; message: string }

export interface LaneState {
  lane: number
  model: ModelInfo
  /** Only stages that have actually started, in the order they happened. */
  stages: Partial<Record<Stage, { status: StageStatus; detail: string }>>
  route?: Route
  result?: ModelResult
}

export interface Turn {
  id: string
  question: string
  mode: Mode
  lanes: LaneState[]
  arbiter: 'idle' | 'running' | 'done'
  pipeline: Partial<Record<PipelineStage, { status: StageStatus; detail: string }>>
  route?: Route
  consensus?: Consensus
  /** The follow-up restated as a standalone question, when the server rewrote it. */
  rewritten?: string
  attachments?: Attachment[]
  /** The model the user picked when asking ('auto' or a model id). */
  lead?: string
  error?: string
  done: boolean
}

/** A file attached to a question. Mirrors /api/files' response; status/error are client-only. */
export interface Attachment {
  id: string
  name: string
  size: number
  kind?: 'data' | 'document' | 'code' | 'text' | 'image'
  text?: string
  table?: string
  status: 'uploading' | 'ready' | 'error'
  error?: string
}

export interface ColumnNode { name: string; type: string; comment?: string }
export interface TableNode { full_name: string; name: string; layer: Layer; comment: string; row_count: number | null; updated_at: string | null; columns: ColumnNode[] }
export interface SchemaNode { name: string; layer: Layer; tables: TableNode[] }
export interface CatalogTree { mode: Mode; catalogs: { name: string; schemas: SchemaNode[] }[] }

export interface AppConfig {
  default_mode: Mode
  catalog: string
  warehouse_id: string
  live_models: ModelOption[]
  routing: string
  council_size: number
  demo_models: ModelInfo[]
}

export interface ModelOption { id: string; name: string; provider: string; available?: boolean; checked?: boolean; reason?: string }

export interface Health { mode: Mode; unity_catalog?: string; warehouse?: string; council: string[] }

/** What the right-hand canvas shows: the consensus result, or a promoted lane. */
export interface CanvasItem { title: string; source: string; result: ResultSet | null; sql: string; kpis: Kpi[]; lineage: Lineage | null; compare: ModelResult[] }
