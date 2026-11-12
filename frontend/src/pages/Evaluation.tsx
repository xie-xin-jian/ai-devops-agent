import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  ChevronDown,
  ChevronRight,
  FlaskConical,
  GitCompare,
  Play,
  RefreshCw,
} from 'lucide-react'
import { evalApi, type EvalRunPayload } from '../api'
import Badge from '../components/Badge'
import Button from '../components/Button'
import Modal from '../components/Modal'
import { Input } from '../components/Input'
import { WorkspacePage } from '../components/Workspace'
import type {
  CaseComparison,
  EvalBatchSummary,
  EvalComparison,
  EvalReport,
  EvalRunStatus,
  EvalTrial,
} from '../types/eval'

export default function Evaluation() {
  const [batches, setBatches] = useState<EvalBatchSummary[]>([])
  const [selected, setSelected] = useState('')
  const [report, setReport] = useState<EvalReport | null>(null)
  const [loading, setLoading] = useState(false)
  const [expandedCase, setExpandedCase] = useState('')

  const [baselineId, setBaselineId] = useState('')
  const [currentId, setCurrentId] = useState('')
  const [comparison, setComparison] = useState<EvalComparison | null>(null)
  const [comparing, setComparing] = useState(false)

  const [showRunModal, setShowRunModal] = useState(false)
  const [runs, setRuns] = useState<EvalRunStatus[]>([])
  const [runError, setRunError] = useState('')
  const prevRunningRef = useRef<Set<string>>(new Set())

  const loadBatches = async () => {
    setLoading(true)
    try {
      const res = await evalApi.batches()
      setBatches(res.batches || [])
      setSelected((prev) =>
        prev || (res.batches || [])[0]?.batch_id || ''
      )
    } finally {
      setLoading(false)
    }
  }

  const pollRuns = useCallback(async () => {
    try {
      const res = await evalApi.runs()
      setRuns(res.runs || [])
    } catch {
      /* 轮询失败静默，下次再试 */
    }
  }, [])

  useEffect(() => {
    loadBatches()
    pollRuns()
  }, [pollRuns])

  // 有运行中的任务时每 2.5s 轮询一次
  useEffect(() => {
    if (!runs.some((r) => r.status === 'running')) return
    const timer = setInterval(pollRuns, 2500)
    return () => clearInterval(timer)
  }, [runs, pollRuns])

  // 刚结束的运行 → 刷新报告列表
  useEffect(() => {
    const running = new Set(
      runs.filter((r) => r.status === 'running').map((r) => r.run_id)
    )
    let finished = false
    for (const id of prevRunningRef.current) {
      if (!running.has(id)) finished = true
    }
    prevRunningRef.current = running
    if (finished) loadBatches()
  }, [runs])

  useEffect(() => {
    if (!selected) {
      setReport(null)
      return
    }
    setExpandedCase('')
    evalApi
      .report(selected)
      .then(setReport)
      .catch(() => setReport(null))
  }, [selected])

  const runCompare = async () => {
    if (!baselineId || !currentId || baselineId === currentId) return
    setComparing(true)
    try {
      setComparison(await evalApi.compare(baselineId, currentId))
    } finally {
      setComparing(false)
    }
  }

  const startRun = async (payload: EvalRunPayload) => {
    setRunError('')
    try {
      await evalApi.run(payload)
      setShowRunModal(false)
      await pollRuns()
    } catch (err: any) {
      setRunError(
        err?.response?.detail?.message ||
          err?.detail?.message ||
          err?.message ||
          '启动失败'
      )
    }
  }

  const caseGroups = useMemo(() => {
    if (!report) return []
    const groups = new Map<string, EvalTrial[]>()
    for (const trial of report.results || []) {
      const list = groups.get(trial.case_id) || []
      list.push(trial)
      groups.set(trial.case_id, list)
    }
    return [...groups.entries()].map(([caseId, trials]) => {
      const completed = trials.filter((t) => t.status === 'completed')
      const passed = completed.filter((t) => t.passed)
      return {
        caseId,
        trials,
        completed: completed.length,
        passed: passed.length,
        passRate: completed.length ? passed.length / completed.length : 0,
      }
    })
  }, [report])

  return (
    <WorkspacePage
      title="评估"
      description="查看批次指标、逐用例试跑轨迹，并用统计显著性判断回归。"
      wide
    >
        <div className="mb-5 flex flex-wrap items-center gap-3">
          <Button variant="ghost" onClick={loadBatches} disabled={loading}>
            <RefreshCw size={16} className={loading ? 'animate-spin' : ''} />
          </Button>
          <Button variant="primary" onClick={() => setShowRunModal(true)}>
            <Play size={14} />
            运行评估
          </Button>
          <div className="ml-auto flex flex-wrap items-center gap-2">
            <CompareSelect
              value={baselineId}
              onChange={setBaselineId}
              placeholder="基线 batch"
              batches={batches}
            />
            <GitCompare size={14} className="text-text-tertiary" />
            <CompareSelect
              value={currentId}
              onChange={setCurrentId}
              placeholder="当前 batch"
              batches={batches}
            />
            <Button
              variant="secondary"
              onClick={runCompare}
              disabled={
                comparing || !baselineId || !currentId || baselineId === currentId
              }
            >
              对比
            </Button>
          </div>
        </div>

        {runs.length > 0 && (
          <RunPanel
            runs={runs.slice(0, 3)}
            onViewReport={(runId) => {
              setSelected(runId)
              setExpandedCase('')
            }}
          />
        )}

        <RunModal
          open={showRunModal}
          onClose={() => setShowRunModal(false)}
          onSubmit={startRun}
          error={runError}
        />

        {batches.length === 0 ? (
          <EmptyState />
        ) : (
          <div className="flex gap-5">
            <BatchList
              batches={batches}
              selected={selected}
              onSelect={setSelected}
            />
            <div className="min-w-0 flex-1 space-y-5">
              {report ? (
                <>
                  <SummaryCards report={report} />
                  <CategoryBars report={report} />
                  <CaseTable
                    groups={caseGroups}
                    expandedCase={expandedCase}
                    onToggle={(id) =>
                      setExpandedCase((prev) => (prev === id ? '' : id))
                    }
                  />
                </>
              ) : (
                <div className="rounded-xl border border-dashed border-border-primary py-20 text-center text-sm text-text-secondary">
                  加载报告中…
                </div>
              )}
              {comparison && (
                <ComparisonPanel comparison={comparison} />
              )}
            </div>
          </div>
        )}
    </WorkspacePage>
  )
}

function EmptyState() {
  return (
    <div className="rounded-xl border border-dashed border-border-primary py-20 text-center">
      <FlaskConical size={36} className="mx-auto mb-3 text-text-tertiary" />
      <p className="text-sm text-text-secondary">暂无评估报告</p>
      <p className="mt-2 text-xs text-text-tertiary">
        运行 <code className="font-mono">python scripts/run_eval.py</code> 后，
        报告会出现在 <code className="font-mono">eval/reports/</code>
      </p>
    </div>
  )
}

function CompareSelect({
  value,
  onChange,
  placeholder,
  batches,
}: {
  value: string
  onChange: (v: string) => void
  placeholder: string
  batches: EvalBatchSummary[]
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="rounded-lg border border-border-primary bg-bg-secondary px-2.5 py-1.5 text-xs text-text-primary"
    >
      <option value="">{placeholder}</option>
      {batches.map((b) => (
        <option key={b.batch_id} value={b.batch_id}>
          {b.label ? `${b.label}（${shortId(b.batch_id)}）` : b.batch_id}
        </option>
      ))}
    </select>
  )
}

function shortId(batchId: string) {
  return batchId.length > 20 ? `${batchId.slice(0, 17)}…` : batchId
}

function BatchList({
  batches,
  selected,
  onSelect,
}: {
  batches: EvalBatchSummary[]
  selected: string
  onSelect: (id: string) => void
}) {
  return (
    <div className="w-60 shrink-0 space-y-2">
      {batches.map((b) => {
        const active = b.batch_id === selected
        return (
          <button
            key={b.batch_id}
            onClick={() => onSelect(b.batch_id)}
            className={`w-full rounded-xl border px-3.5 py-3 text-left transition-colors ${
              active
                ? 'border-border-primary bg-accent-soft'
                : 'border-border-primary bg-bg-secondary hover:bg-bg-hover'
            }`}
          >
            <div className="truncate text-sm font-medium">
              {b.label || b.batch_id}
            </div>
            <div className="mt-0.5 truncate font-mono text-[11px] text-text-tertiary">
              {shortId(b.batch_id)}
            </div>
            <div className="mt-2 flex items-center gap-2">
              <Badge variant={rateVariant(b.pass_rate)}>
                {Math.round(b.pass_rate * 100)}%
              </Badge>
              <span className="text-[11px] text-text-tertiary">
                {b.passed}/{b.completed} · ¥{b.total_cost_cny?.toFixed(2)}
              </span>
            </div>
            <div className="mt-1 text-[11px] text-text-tertiary">
              {b.started_at ? new Date(b.started_at * 1000).toLocaleString() : '-'}
            </div>
          </button>
        )
      })}
    </div>
  )
}

function rateVariant(rate: number): 'success' | 'warning' | 'error' {
  if (rate >= 0.8) return 'success'
  if (rate >= 0.5) return 'warning'
  return 'error'
}

function SummaryCards({ report }: { report: EvalReport }) {
  const ci = report.pass_rate_ci95
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
      <Stat label="试跑" value={String(report.trials)} />
      <Stat label="完成" value={String(report.completed)} />
      <Stat label="通过" value={String(report.passed)} />
      <Stat
        label="失败"
        value={String(report.failed)}
        tone={report.failed > 0 ? 'error' : undefined}
      />
      <Stat
        label="通过率"
        value={`${Math.round(report.pass_rate * 100)}%`}
        sub={
          ci
            ? `95% CI [${ci[0].toFixed(2)}, ${ci[1].toFixed(2)}]`
            : undefined
        }
      />
      <Stat
        label="总成本"
        value={`¥${(report.total_cost_cny || 0).toFixed(2)}`}
        sub={`耗时 ${(report.duration_ms / 1000).toFixed(0)}s`}
      />
    </div>
  )
}

function Stat({
  label,
  value,
  sub,
  tone,
}: {
  label: string
  value: string
  sub?: string
  tone?: 'error'
}) {
  return (
    <div className="rounded-xl border border-border-primary bg-bg-secondary px-3.5 py-3">
      <div className="text-[11px] text-text-tertiary">{label}</div>
      <div
        className={`mt-1 text-lg font-semibold ${
          tone === 'error' ? 'text-status-error' : ''
        }`}
      >
        {value}
      </div>
      {sub && <div className="mt-0.5 text-[11px] text-text-tertiary">{sub}</div>}
    </div>
  )
}

function CategoryBars({ report }: { report: EvalReport }) {
  const entries = Object.entries(report.by_category || {})
  if (entries.length === 0) return null
  return (
    <div className="rounded-xl border border-border-primary bg-bg-secondary p-4">
      <div className="mb-3 text-xs font-medium text-text-secondary">
        按类别通过率
      </div>
      <div className="space-y-2.5">
        {entries.map(([category, stat]) => (
          <div key={category} className="flex items-center gap-3">
            <div className="w-20 shrink-0 font-mono text-xs text-text-secondary">
              {category}
            </div>
            <RateBar passed={stat.passed} total={stat.completed} />
            <div className="w-24 shrink-0 text-right text-xs text-text-tertiary">
              {stat.passed}/{stat.completed}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

/** 通过率条形图：填充为通过比例，细线标注 Wilson 95% 区间 */
function RateBar({
  passed,
  total,
  ci,
}: {
  passed: number
  total: number
  ci?: [number, number] | null
}) {
  const rate = total ? passed / total : 0
  const low = ci ? Math.max(0, ci[0]) : 0
  const high = ci ? Math.min(1, ci[1]) : 0
  return (
    <div className="relative h-3 flex-1 overflow-visible rounded-full bg-bg-tertiary">
      <div
        className="absolute inset-y-0 left-0 rounded-full bg-status-success/70"
        style={{ width: `${rate * 100}%` }}
      />
      {ci && (
        <>
          <div
            className="absolute inset-y-[-3px] w-px bg-text-tertiary"
            style={{ left: `${low * 100}%` }}
          />
          <div
            className="absolute inset-y-[-3px] w-px bg-text-tertiary"
            style={{ left: `${high * 100}%` }}
          />
          <div
            className="absolute inset-y-[-3px] h-[3px] border-x border-text-tertiary"
            style={{ left: `${low * 100}%`, width: `${(high - low) * 100}%` }}
          />
        </>
      )}
      <div
        className="absolute top-[-4px] h-[calc(100%+8px)] w-0.5 bg-text-primary"
        style={{ left: `calc(${rate * 100}% - 1px)` }}
      />
    </div>
  )
}

function CaseTable({
  groups,
  expandedCase,
  onToggle,
}: {
  groups: {
    caseId: string
    trials: EvalTrial[]
    completed: number
    passed: number
    passRate: number
  }[]
  expandedCase: string
  onToggle: (id: string) => void
}) {
  return (
    <div className="overflow-hidden rounded-xl border border-border-primary">
      <table className="w-full">
        <thead>
          <tr className="border-b border-border-primary bg-bg-tertiary/50">
            <Th>用例</Th>
            <Th>类别</Th>
            <Th>严重度</Th>
            <Th>通过率</Th>
            <Th>试次</Th>
          </tr>
        </thead>
        <tbody>
          {groups.map((g) => {
            const expanded = expandedCase === g.caseId
            const first = g.trials[0]
            return (
              <Fragment key={g.caseId}>
                <tr
                  onClick={() => onToggle(g.caseId)}
                  className="cursor-pointer border-b border-border-secondary last:border-0 hover:bg-bg-hover/50"
                >
                  <td className="px-4 py-3">
                    <span className="flex items-center gap-1.5 text-sm font-medium">
                      {expanded ? (
                        <ChevronDown size={14} className="text-text-tertiary" />
                      ) : (
                        <ChevronRight size={14} className="text-text-tertiary" />
                      )}
                      {g.caseId}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <Badge variant="default">{first?.category || '-'}</Badge>
                  </td>
                  <td className="px-4 py-3">
                    <Badge variant={severityVariant(first?.severity)}>
                      {first?.severity || '-'}
                    </Badge>
                  </td>
                  <td className="w-56 px-4 py-3">
                    <div className="flex items-center gap-2">
                      <RateBar passed={g.passed} total={g.completed} />
                      <span className="w-9 shrink-0 text-right text-xs text-text-secondary">
                        {Math.round(g.passRate * 100)}%
                      </span>
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex gap-1">
                      {g.trials.map((t) => (
                        <span
                          key={t.trial_no}
                          title={`trial ${t.trial_no}: ${t.status}`}
                          className={`inline-block h-2.5 w-2.5 rounded-full ${
                            t.status !== 'completed'
                              ? 'bg-status-warning'
                              : t.passed
                                ? 'bg-status-success'
                                : 'bg-status-error'
                          }`}
                        />
                      ))}
                    </div>
                  </td>
                </tr>
                {expanded && (
                  <tr className="bg-bg-tertiary/30">
                    <td colSpan={5} className="px-4 py-3">
                      <div className="space-y-2.5">
                        {g.trials.map((t) => (
                          <TrialDetail key={t.trial_no} trial={t} />
                        ))}
                      </div>
                    </td>
                  </tr>
                )}
              </Fragment>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function TrialDetail({ trial }: { trial: EvalTrial }) {
  const [showTools, setShowTools] = useState(false)
  const failedScores = trial.scores.filter(
    (s) => s.status === 'fail' || s.status === 'error'
  )
  return (
    <div className="rounded-lg border border-border-secondary bg-bg-secondary p-3">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className="font-mono font-medium">trial #{trial.trial_no}</span>
        <Badge variant={trial.status === 'completed' ? 'default' : 'warning'}>
          {trial.status}
        </Badge>
        {trial.status === 'completed' && (
          <Badge variant={trial.passed ? 'success' : 'error'}>
            {trial.passed ? '通过' : '失败'}
          </Badge>
        )}
        <span className="text-text-tertiary">
          {(trial.duration_ms / 1000).toFixed(1)}s · ¥
          {(trial.cost_cny + trial.judge_cost_cny).toFixed(3)}
        </span>
        {trial.approvals_requested ? (
          <span className="text-text-tertiary">
            审批 {trial.approvals_granted}/{trial.approvals_requested}
          </span>
        ) : null}
        <button
          onClick={() => setShowTools((v) => !v)}
          className="ml-auto text-text-secondary hover:text-text-primary"
        >
          工具调用（{trial.tool_calls?.length || 0}）
        </button>
      </div>

      <div className="mt-2 flex flex-wrap gap-1.5">
        {trial.scores.map((s, i) => (
          <span
            key={`${s.rule}-${i}`}
            className={`inline-flex items-center gap-1 rounded border px-1.5 py-0.5 font-mono text-[11px] ${
              s.status === 'pass'
                ? 'border-status-success/30 bg-status-success/10 text-status-success'
                : s.status === 'skip'
                  ? 'border-border-primary bg-bg-tertiary text-text-tertiary'
                  : 'border-status-error/30 bg-status-error/10 text-status-error'
            }`}
          >
            {s.rule}
          </span>
        ))}
      </div>

      {failedScores.map((s, i) => (
        <div
          key={i}
          className="mt-2 rounded-md border border-status-error/20 bg-status-error/5 px-2.5 py-1.5 text-[11px] text-text-secondary"
        >
          <span className="font-mono text-status-error">{s.rule}</span>
          {s.evidence && Object.keys(s.evidence).length > 0 && (
            <span className="ml-2 font-mono">
              {Object.entries(s.evidence)
                .slice(0, 3)
                .map(([k, v]) => `${k}=${String(v).slice(0, 80)}`)
                .join(' · ')}
            </span>
          )}
        </div>
      ))}

      {showTools && (
        <div className="mt-2 space-y-1.5">
          {(trial.tool_calls || []).map((c) => (
            <div
              key={c.step}
              className="rounded-md border border-border-secondary px-2.5 py-1.5 text-[11px]"
            >
              <div className="flex items-center gap-2">
                <span
                  className={`h-1.5 w-1.5 rounded-full ${
                    c.ok ? 'bg-status-success' : 'bg-status-error'
                  }`}
                />
                <span className="font-mono font-medium">{c.tool}</span>
                {c.duration_ms != null && (
                  <span className="text-text-tertiary">{c.duration_ms}ms</span>
                )}
              </div>
              {c.input && (
                <div className="mt-1 truncate font-mono text-text-tertiary">
                  {JSON.stringify(c.input)}
                </div>
              )}
              {c.output && (
                <pre className="mt-1 max-h-32 overflow-y-auto whitespace-pre-wrap font-mono text-text-secondary">
                  {c.output.slice(0, 600)}
                </pre>
              )}
            </div>
          ))}
        </div>
      )}

      {trial.final_answer && (
        <div className="mt-2 border-l-2 border-border-primary pl-2.5 text-xs text-text-secondary">
          {trial.final_answer}
        </div>
      )}
      {trial.error && (
        <div className="mt-2 text-[11px] text-status-error">{trial.error}</div>
      )}
    </div>
  )
}

function ComparisonPanel({ comparison }: { comparison: EvalComparison }) {
  return (
    <div className="space-y-3 rounded-xl border border-border-primary bg-bg-secondary p-4">
      <div className="text-xs font-medium text-text-secondary">
        基线对比 · {shortId(comparison.baseline_batch_id)} →{' '}
        {shortId(comparison.current_batch_id)}
      </div>

      <ComparisonSection
        title="回归"
        empty="无回归"
        items={comparison.regressions}
        tone="error"
      />
      <ComparisonSection
        title="改进"
        empty="无改进"
        items={comparison.improvements}
        tone="success"
      />
      <ComparisonSection
        title="噪声内下降（不拦门禁）"
        empty="无"
        items={comparison.drops_within_noise}
        tone="muted"
      />
      {(comparison.missing_cases?.length || comparison.new_cases?.length) ? (
        <div className="text-[11px] text-text-tertiary">
          {comparison.missing_cases?.length ? (
            <div>
              基线有而本次没有的用例：{comparison.missing_cases.join('、')}
            </div>
          ) : null}
          {comparison.new_cases?.length ? (
            <div>新增用例：{comparison.new_cases.join('、')}</div>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}

function ComparisonSection({
  title,
  empty,
  items,
  tone,
}: {
  title: string
  empty: string
  items: CaseComparison[]
  tone: 'error' | 'success' | 'muted'
}) {
  if (!items?.length) {
    return (
      <div className="text-[11px] text-text-tertiary">
        {title}：{empty}
      </div>
    )
  }
  return (
    <div>
      <div className="mb-1.5 text-[11px] font-medium text-text-secondary">
        {title}（{items.length}）
      </div>
      <div className="space-y-1.5">
        {items.map((item) => (
          <div
            key={item.case_id}
            className="flex flex-wrap items-center gap-2 rounded-lg border border-border-secondary px-2.5 py-1.5 text-xs"
          >
            <span className="font-mono font-medium">{item.case_id}</span>
            <span className="text-text-tertiary">
              {(item.baseline_pass_rate * 100).toFixed(0)}% →{' '}
              {(item.current_pass_rate * 100).toFixed(0)}%
            </span>
            <Badge
              variant={
                tone === 'error'
                  ? 'error'
                  : tone === 'success'
                    ? 'success'
                    : 'default'
              }
            >
              {item.significance === 'significant'
                ? `显著 p=${item.regression_p_value}`
                : item.significance === 'within-noise'
                  ? '噪声内'
                  : item.significance === 'insufficient-samples'
                    ? '样本不足'
                    : item.significance}
            </Badge>
            {item.new_failed_rules?.length ? (
              <span className="font-mono text-[11px] text-status-error">
                新失败规则：{item.new_failed_rules.join('、')}
              </span>
            ) : null}
          </div>
        ))}
      </div>
    </div>
  )
}

function RunModal({
  open,
  onClose,
  onSubmit,
  error,
}: {
  open: boolean
  onClose: () => void
  onSubmit: (payload: EvalRunPayload) => Promise<void>
  error: string
}) {
  const [validateOnly, setValidateOnly] = useState(false)
  const [casesText, setCasesText] = useState('')
  const [categoriesText, setCategoriesText] = useState('')
  const [trials, setTrials] = useState(3)
  const [parallel, setParallel] = useState(1)
  const [judge, setJudge] = useState(false)
  const [stopOnFailure, setStopOnFailure] = useState(false)
  const [label, setLabel] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const submit = async () => {
    setSubmitting(true)
    try {
      await onSubmit({
        validate_only: validateOnly,
        cases: splitList(casesText),
        categories: splitList(categoriesText),
        trials,
        parallel,
        judge,
        stop_on_failure: stopOnFailure,
        label: label.trim(),
      })
      setCasesText('')
      setCategoriesText('')
      setLabel('')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="运行评估"
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={submitting}>
            取消
          </Button>
          <Button variant="primary" onClick={submit} disabled={submitting}>
            {submitting ? '启动中…' : validateOnly ? '校验（免费）' : '启动（将调模型 API）'}
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <div>
          <div className="mb-1.5 text-xs text-text-secondary">模式</div>
          <div className="flex gap-2">
            <button
              onClick={() => setValidateOnly(false)}
              className={`rounded-lg border px-3 py-1.5 text-xs ${
                !validateOnly
                  ? 'border-border-primary bg-accent-soft font-medium'
                  : 'border-border-primary text-text-secondary'
              }`}
            >
              正式评估
            </button>
            <button
              onClick={() => setValidateOnly(true)}
              className={`rounded-lg border px-3 py-1.5 text-xs ${
                validateOnly
                  ? 'border-border-primary bg-accent-soft font-medium'
                  : 'border-border-primary text-text-secondary'
              }`}
            >
              仅校验用例（不调模型）
            </button>
          </div>
        </div>

        <Input
          label="用例（逗号分隔，留空 = 全部）"
          placeholder="demo-inspect-service, check-config-syntax"
          value={casesText}
          onChange={(e) => setCasesText(e.target.value)}
        />
        <Input
          label="类别（逗号分隔，留空 = 全部）"
          placeholder="core, boundary, faq, abnormal"
          value={categoriesText}
          onChange={(e) => setCategoriesText(e.target.value)}
        />

        {!validateOnly && (
          <div className="grid grid-cols-2 gap-3">
            <label className="block">
              <span className="mb-1 block text-xs text-text-secondary">
                每用例采样次数
              </span>
              <input
                type="number"
                min={1}
                max={20}
                value={trials}
                onChange={(e) => setTrials(Number(e.target.value) || 1)}
                className="w-full rounded-lg border border-border-primary bg-bg-secondary px-3 py-1.5 text-sm"
              />
            </label>
            <label className="block">
              <span className="mb-1 block text-xs text-text-secondary">
                并发数
              </span>
              <input
                type="number"
                min={1}
                max={8}
                value={parallel}
                onChange={(e) => setParallel(Number(e.target.value) || 1)}
                className="w-full rounded-lg border border-border-primary bg-bg-secondary px-3 py-1.5 text-sm"
              />
            </label>
          </div>
        )}

        {!validateOnly && (
          <div className="flex gap-5">
            <label className="flex items-center gap-2 text-xs text-text-secondary">
              <input
                type="checkbox"
                checked={judge}
                onChange={(e) => setJudge(e.target.checked)}
              />
              启用 LLM Judge（开放问答用）
            </label>
            <label className="flex items-center gap-2 text-xs text-text-secondary">
              <input
                type="checkbox"
                checked={stopOnFailure}
                onChange={(e) => setStopOnFailure(e.target.checked)}
              />
              失败即停（强制串行）
            </label>
          </div>
        )}

        <Input
          label="标签（可选）"
          placeholder="例如 prompt-v2"
          value={label}
          onChange={(e) => setLabel(e.target.value)}
        />

        {error && (
          <div className="rounded-lg border border-status-error/30 bg-status-error/10 px-3 py-2 text-xs text-status-error">
            {error}
          </div>
        )}
      </div>
    </Modal>
  )
}

function splitList(text: string): string[] {
  return text
    .split(/[,，\s]+/)
    .map((s) => s.trim())
    .filter(Boolean)
}

function RunPanel({
  runs,
  onViewReport,
}: {
  runs: EvalRunStatus[]
  onViewReport: (runId: string) => void
}) {
  const [openLog, setOpenLog] = useState('')
  return (
    <div className="mb-5 space-y-2">
      {runs.map((run) => (
        <div
          key={run.run_id}
          className="rounded-xl border border-border-primary bg-bg-secondary p-3"
        >
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <Badge
              variant={
                run.status === 'running'
                  ? 'info'
                  : run.status === 'completed'
                    ? 'success'
                    : 'error'
              }
            >
              {run.status === 'running'
                ? `运行中 ${run.elapsed_s}s`
                : run.status === 'completed'
                  ? '已完成'
                  : `失败（exit ${run.exit_code}）`}
            </Badge>
            <span className="font-mono text-text-tertiary">
              {run.run_id}
            </span>
            {run.label && <span>{run.label}</span>}
            {run.validate_only && <Badge variant="default">仅校验</Badge>}
            {!run.validate_only && (
              <span className="text-text-tertiary">
                {run.cases.length ? `用例 ${run.cases.join('、')}` : '全部用例'}
                {run.trials > 1 ? ` × ${run.trials}` : ''}
                {run.parallel > 1 ? ` · 并发 ${run.parallel}` : ''}
                {run.judge ? ' · Judge' : ''}
              </span>
            )}
            <div className="ml-auto flex items-center gap-2">
              <button
                onClick={() =>
                  setOpenLog((prev) => (prev === run.run_id ? '' : run.run_id))
                }
                className="text-text-secondary hover:text-text-primary"
              >
                日志
              </button>
              {run.status === 'completed' && !run.validate_only && (
                <Button
                  variant="secondary"
                  onClick={() => onViewReport(run.run_id)}
                >
                  查看报告
                </Button>
              )}
            </div>
          </div>
          {openLog === run.run_id && (
            <pre className="mt-2 max-h-48 overflow-y-auto whitespace-pre-wrap rounded-lg bg-bg-tertiary p-2.5 font-mono text-[11px] text-text-secondary">
              {run.log_tail || '（暂无输出）'}
            </pre>
          )}
        </div>
      ))}
    </div>
  )
}

function Th({ children }: { children: React.ReactNode }) {
  return (
    <th className="px-4 py-3 text-left text-xs font-medium text-text-secondary">
      {children}
    </th>
  )
}

function severityVariant(severity?: string): 'error' | 'warning' | 'default' {
  if (severity === 'high') return 'error'
  if (severity === 'medium') return 'warning'
  return 'default'
}
