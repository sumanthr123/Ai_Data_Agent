// Mock turns for the /states gallery. Figures are real: queried from ai_data_agent.agent_gold.orders on 2026-11-07.
import type { AskResponse, Cell, ResultPreview, StageEvent, Turn } from './types'

const TABLE = 'ai_data_agent.agent_gold.orders'
const AS_OF = '2026-11-07T06:36:09'

const ev = (stage: StageEvent['stage'], ms: number, status: StageEvent['status'] = 'succeeded', detail = ''): StageEvent => ({ stage, status, ms, detail })
export const DATA_STAGES: StageEvent[] = [ev('context', 900), ev('generate_sql', 2100), ev('execute', 700, 'succeeded', '4 rows'), ev('draft', 3100), ev('review', 1800), ev('complete', 0)]

function response(over: Partial<AskResponse>): AskResponse {
  return {
    kind: 'data', status: 'ANSWERED', answer: '', answer_truncated: false, clarifying_question: null, hypotheses: [], assumptions: [],
    query_id: null, sql: null, filters: [], result: null, sources: [{ table: TABLE, updated_at: AS_OF, kind: 'shared', row_count: 9994, date_range: ['2014-01-03', '2017-12-30'], warnings: [], expires_at: null }],
    verification: {
      analyst: 'OK', reviewer: 'APPROVED', adjudicator: 'NOT_NEEDED', reviewed: true, degraded_reasons: [], correction_cycles: 0, open_issues: [], checks: [],
      calls: [
        { role: 'analyst', purpose: 'plan', endpoint: 'databricks-gpt-oss-120b', status: 'ok', latency_ms: 2100, prompt_tokens: 900, completion_tokens: 160, reasoning_tokens: 0, cost_estimate_usd: null, error: null },
        { role: 'reviewer', purpose: 'review', endpoint: 'databricks-llama-4-maverick', status: 'ok', latency_ms: 1800, prompt_tokens: 800, completion_tokens: 90, reasoning_tokens: 0, cost_estimate_usd: null, error: null },
      ],
      total_tokens: 2780, total_model_calls: 3, sql_attempts: 1, cost_estimate_usd: null,
    },
    auth: { mode: 'service_principal', disclosure: "Queries run as the app's service principal, not as you." },
    state: { active_datasets: [TABLE], applied_filters: [], resolved_definitions: {}, last_query_id: null, last_sql: null, last_question: null, pending_clarification: null },
    events: [], total_ms: 8600, ...over,
  }
}

const turn = (id: string, question: string, over: Partial<Turn>): Turn => ({ id, question, stages: DATA_STAGES, datasets: [TABLE], ...over })
const result = (columns: string[], types: string[], rows: Record<string, Cell>[]): ResultPreview =>
  ({ columns, column_types: types, rows, row_count: rows.length, truncated: false, from_cache: false, statement_id: null, runtime_ms: 700 })

const REGION_SQL = `SELECT region, SUM(sales) AS total_sales FROM ${TABLE} WHERE order_date >= '2017-01-01' AND order_date < '2018-01-01' GROUP BY region ORDER BY total_sales DESC`

export const GALLERY: { title: string; note: string; turn: Turn }[] = [
  {
    title: 'Answer: categories', note: 'Chart | Table toggle, editable filter chips, How I got this, follow-ups.',
    turn: turn('answer', 'What were total sales by region in 2017?', {
      response: response({
        trace_id: 'tr-gallery-example',
        answer: 'West led 2017 with **$250,128.37** in sales, followed by East at $213,082.90. Total across the four regions was $733,215.26.',
        sql: REGION_SQL, filters: ["order_date >= '2017-01-01'", "order_date < '2018-01-01'"], assumptions: ['Sales are in USD after discount.'],
        result: result(['region', 'total_sales'], ['string', 'decimal(28,4)'], [
          { region: 'West', total_sales: 250128.37 }, { region: 'East', total_sales: 213082.9 }, { region: 'Central', total_sales: 147098.13 }, { region: 'South', total_sales: 122905.86 }]),
      }),
    }),
  },
  {
    title: 'Answer: one number', note: 'A single value becomes a KPI tile.',
    turn: turn('kpi', 'How many orders were placed in 2016?', {
      response: response({ answer: 'There were **1,315** orders in 2016 (distinct order ids, not lines).', sql: `SELECT COUNT(DISTINCT order_id) AS orders FROM ${TABLE} WHERE year(order_date) = 2016`,
        result: result(['orders'], ['bigint'], [{ orders: 1315 }]) }),
    }),
  },
  {
    title: 'Answer: time series', note: 'A month column draws a line chart.',
    turn: turn('trend', 'How did total sales change by month in 2017?', {
      response: response({
        answer: 'Sales rose through the year, from **$43,971.37** in January to a peak of **$118,447.83** in November.',
        sql: `SELECT date_format(order_date, 'yyyy-MM') AS order_month, SUM(sales) AS total_sales FROM ${TABLE} WHERE year(order_date) = 2017 GROUP BY 1 ORDER BY 1`,
        result: result(['order_month', 'total_sales'], ['string', 'decimal(28,4)'], [
          ['2017-01', 43971.37], ['2017-02', 20301.13], ['2017-03', 58872.35], ['2017-04', 36521.54], ['2017-05', 44261.11], ['2017-06', 52981.73],
          ['2017-07', 45264.42], ['2017-08', 63120.89], ['2017-09', 87866.65], ['2017-10', 77776.92], ['2017-11', 118447.83], ['2017-12', 83829.32],
        ].map(([m, v]) => ({ order_month: m, total_sales: v } as Record<string, Cell>))),
      }),
    }),
  },
  {
    title: 'Clarifying question', note: 'Nothing is computed until the user answers.',
    turn: turn('clarify', 'Show me the top customers', {
      stages: [ev('context', 900), ev('generate_sql', 1900), ev('clarify', 0), ev('complete', 0)],
      response: response({ status: 'NEEDS_CLARIFICATION', clarifying_question: 'Top customers by which measure?', clarifying_options: ['Total sales', 'Number of orders', 'Profit'] }),
    }),
  },
  {
    title: 'Not in the data', note: 'An unanswerable question says so instead of guessing.',
    turn: turn('missing', 'What was our advertising spend in 2017?', {
      stages: [ev('context', 900), ev('generate_sql', 1700), ev('complete', 0)],
      response: response({ status: 'INSUFFICIENT_SCHEMA', answer: `This can't be answered from ${TABLE}: that figure isn't in these tables.`, verification: { ...response({}).verification, reviewed: false, reviewer: 'NOT_RUN' } }),
    }),
  },
  {
    title: 'Models disagreed', note: 'The council abstains rather than pick a winner.',
    turn: turn('conflict', 'What was the average discount on furniture?', {
      response: response({
        status: 'UNRESOLVED', answer: 'Two independent queries returned different values, so no answer was picked. A person will review it.',
        verification: { ...response({}).verification, reviewed: false, adjudicator: 'UNRESOLVED' },
        council: { trigger: 'dispute', agreement: 'conflict', judge: '', chosen: null, rationale: '', disagreement: 'One draft averaged per line, the other per order.',
          candidates: [
            { label: 'A', endpoint: 'databricks-gpt-oss-120b', status: 'executed', sql: `SELECT AVG(discount) FROM ${TABLE} WHERE category = 'Furniture'`, row_count: 1, group: 0, note: '' },
            { label: 'B', endpoint: 'databricks-llama-4-maverick', status: 'executed', sql: `SELECT AVG(d) FROM (SELECT order_id, AVG(discount) d FROM ${TABLE} WHERE category = 'Furniture' GROUP BY order_id)`, row_count: 1, group: 1, note: '' },
          ] },
      }),
    }),
  },
  { title: 'Query failed', note: 'Business language first; the raw error is one click away.',
    turn: turn('failed', 'What were sales by sub-category last week?', { stages: [ev('context', 900), ev('generate_sql', 2000), ev('execute', 400, 'failed', 'query failed')],
      error: '[UNRESOLVED_COLUMN] A column with name `subcategory` cannot be resolved. Did you mean `sub_category`?' }) },
  { title: 'Rate limited', note: 'error_code rate_limited: one automatic retry after a visible countdown; Cancel stops it.',
    turn: turn('busy', 'What is the profit margin by segment?', { stages: [ev('context', 900), ev('generate_sql', 600, 'failed')],
      response: response({ status: 'ERROR', error_code: 'rate_limited', answer: "The Analyst model couldn't answer: databricks-gpt-oss-120b is at its rate limit or out of capacity." }) }) },
  { title: 'Permission denied', note: 'error_code permission: Unity Catalog decides; no silent fallback.',
    turn: turn('denied', 'What is the average discount by customer?', { stages: [ev('context', 900), ev('generate_sql', 2000), ev('execute', 300, 'failed')],
      response: response({ status: 'ERROR', error_code: 'permission', answer: "The query couldn't run: [INSUFFICIENT_PERMISSIONS] User does not have SELECT on Table 'ai_data_agent.gold.orders'." }) }) },
  { title: 'Connection lost', note: 'The steps that finished are kept.',
    turn: turn('dropped', 'Which state had the most orders?', { stages: [ev('context', 900), ev('generate_sql', 2000), ev('execute', 0, 'skipped')], error: 'The connection closed before an answer arrived.' }) },
  { title: 'Stopped by you', note: 'Esc or Stop; nothing further runs on the warehouse.',
    turn: turn('stopped', 'Who are the top 5 customers by sales?', { stages: [ev('context', 900), ev('generate_sql', 0, 'skipped')], cancelled: true }) },
]

/** The streaming example replays these events with realistic delays (ms after start). */
export const REPLAY: [number, StageEvent][] = [
  [0, ev('context', 0, 'running')], [900, ev('context', 900)], [950, ev('generate_sql', 0, 'running')], [3000, ev('generate_sql', 2050)],
  [3050, ev('execute', 0, 'running', 'warehouse starting')], [9000, ev('execute', 5950, 'succeeded', '4 rows')], [9050, ev('draft', 0, 'running')],
  [12000, ev('draft', 2950)], [12050, ev('review', 0, 'running')], [14000, ev('review', 1950)],
]
