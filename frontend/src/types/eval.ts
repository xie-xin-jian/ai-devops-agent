// 评估报告类型（对应 api/routes/eval_route.py 与 eval/reports/*.json）

export interface EvalCategoryStat {
  trials: number
  completed: number
  passed: number
  failed: number
  cost_cny: number
  judge_cost_cny: number
}

export interface EvalBatchSummary {
  batch_id: string
  label: string
  model_id: string
  started_at: number
  finished_at: number
  duration_ms: number
  trials: number
  completed: number
  passed: number
  failed: number
  pass_rate: number
  pass_rate_ci95: [number, number] | null
  agent_cost_cny: number
  judge_cost_cny: number
  total_cost_cny: number
  by_category: Record<string, EvalCategoryStat>
}

// 跨批次时间序列（GET /api/eval/metrics）——实验列表的通过率趋势图
// 只读聚合，不落库；按 started_at 升序返回，供手写 SVG sparkline 使用。
export interface EvalMetricPoint {
  batch_id: string
  label: string
  started_at: number
  pass_rate: number
  total_cost_cny: number
  cases: number
  trials: number
}

export interface EvalMetrics {
  points: EvalMetricPoint[]
  total: number
  reports_dir: string
}

export interface EvalScore {
  rule: string
  status: 'pass' | 'fail' | 'skip' | 'error' | string
  evidence?: Record<string, any>
}

export interface EvalToolCall {
  step: number
  tool: string
  input?: Record<string, any>
  output?: string
  duration_ms?: number
  ok?: boolean
}

export interface EvalTrial {
  case_id: string
  category: string
  topic?: string
  severity: string
  trial_no: number
  status: string
  passed: boolean
  run_id?: string
  final_answer?: string
  error?: string
  tool_calls: EvalToolCall[]
  input_tokens?: number
  output_tokens?: number
  cost_cny: number
  judge_cost_cny: number
  duration_ms: number
  approvals_requested?: number
  approvals_granted?: number
  scores: EvalScore[]
}

export interface EvalReport extends EvalBatchSummary {
  results: EvalTrial[]
}

// 用例库（GET /api/eval/cases）——只读解析 eval/cases/*.yaml
export interface EvalCase {
  id: string
  category: string
  topic: string
  severity: string
  prompt: string
  fixture: string
  service: string
  approvals: string
  timeout_seconds: number
  max_turns: number
  expect_count: number
  expect_rules: string[]
  tags: string[]
  notes: string
  has_judge: boolean
  source: string
  last_pass_rate: number | null
  last_trials: number
  last_batch_id: string
}

export interface EvalCaseCatalog {
  cases: EvalCase[]
  categories: string[]
  total: number
  errors: string[]
}

export interface CaseComparison {
  case_id: string
  category: string
  severity: string
  baseline_pass_rate: number
  baseline_pass_rate_ci95?: [number, number] | null
  current_pass_rate: number
  current_pass_rate_ci95?: [number, number] | null
  pass_rate_delta: number
  baseline_trials: number
  current_trials: number
  significance: 'significant' | 'within-noise' | 'insufficient-samples' | string
  regression_p_value: number
  cost_delta_cny?: number
  duration_delta_ms?: number
  tool_call_delta?: number
  new_failed_rules?: string[]
  recovered_rules?: string[]
}

export interface EvalOverall {
  cases: number
  trials: number
  passed: number
  pass_rate: number
  pass_rate_ci95: [number, number] | null
  agent_cost_cny: number
  judge_cost_cny: number
  total_cost_cny: number
  avg_duration_ms: number
  p95_duration_ms: number
}

// 一句话门禁结论（route 层 _build_verdict 附加，不改统计内核）
export interface EvalVerdict {
  status: 'pass' | 'blocked' | 'insufficient'
  reason: string
  alpha: number
  min_samples: number
  tolerance: number
  significant_regressions: number
  high_severity_regressions: number
  insufficient_cases: number
}

export interface EvalComparison {
  baseline_batch_id: string
  current_batch_id: string
  tolerance: number
  alpha: number
  min_samples: number
  overall: {
    baseline: EvalOverall
    current: EvalOverall
    pass_rate_delta: number
    agent_cost_delta_cny: number
    judge_cost_delta_cny: number
    total_cost_delta_cny: number
    avg_duration_delta_ms: number
    p95_duration_delta_ms: number
  }
  verdict?: EvalVerdict
  regressions: CaseComparison[]
  improvements: CaseComparison[]
  drops_within_noise: CaseComparison[]
  rule_regressions: CaseComparison[]
  missing_cases: string[]
  new_cases: string[]
  high_severity_regressions: CaseComparison[]
}

// UI 触发的评估运行状态（POST /api/eval/run 产生的子进程）
export interface EvalRunStatus {
  run_id: string
  status: 'running' | 'completed' | 'failed'
  exit_code: number | null
  started_at: number
  elapsed_s: number
  validate_only: boolean
  label: string
  cases: string[]
  categories: string[]
  trials: number
  parallel: number
  judge: boolean
  completed: number
  total: number
  log_tail: string
}
