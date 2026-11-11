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
  new_failed_rules?: string[]
  recovered_rules?: string[]
}

export interface EvalComparison {
  baseline_batch_id: string
  current_batch_id: string
  regressions: CaseComparison[]
  improvements: CaseComparison[]
  drops_within_noise: CaseComparison[]
  rule_regressions: CaseComparison[]
  missing_cases: string[]
  new_cases: string[]
  high_severity_regressions: CaseComparison[]
}
