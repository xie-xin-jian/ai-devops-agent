import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import {
  AlertTriangle,
  ArrowRight,
  BarChart3,
  BookOpen,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  ChevronUp,
  Clock,
  Database,
  Filter,
  FlaskConical,
  GitCompare,
  Info,
  Layers,
  ListChecks,
  Minus,
  Play,
  RefreshCw,
  Search,
  ShieldAlert,
  SlidersHorizontal,
  Star,
  TrendingDown,
  TrendingUp,
  X,
  XCircle,
  Zap,
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
  EvalCase,
  EvalCaseCatalog,
  EvalComparison,
  EvalMetricPoint,
  EvalReport,
  EvalRunStatus,
  EvalToolCall,
  EvalTrial,
} from '../types/eval'

type Tab = 'cases' | 'experiments' | 'compare'

const CATEGORY_LABELS: Record<string, string> = {
  core: 'core · 正常诊断',
  boundary: 'boundary · 边界拒答',
  abnormal: 'abnormal · 危险拦截',
  faq: 'faq · 开放问答',
}

const CATEGORY_HINTS: Record<string, string> = {
  core: '测正常只读诊断与显式批准的写操作；等价工具用 any_of 断言。',
  boundary: '测敏感文件拒读、路径穿越、日志缺失容错；断言的是拒绝行为。',
  abnormal: '测危险删除/重启必须被拦；这类用例必须保持绿色，红了说明治理退化。',
  faq: '开放式运维问答，没有标准答案，由 LLM Judge 按 rubric 评分。',
}

const CATEGORY_SHORT: Record<string, string> = {
  core: '正常诊断',
  boundary: '边界拒答',
  abnormal: '危险拦截',
  faq: '开放问答',
}

function formatBatchStamp(startedAt: number): string {
  if (!startedAt) return ''
  const d = new Date(startedAt * 1000)
  if (Number.isNaN(d.getTime())) return ''
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

/** 旧报告没有 label 时，用类别 + 时间拼一个可读名字，避免直接展示裸 batch_id。 */
function batchDisplayName(batch: {
  label?: string
  by_category?: Record<string, unknown>
  started_at?: number
}): string {
  if (batch.label) return batch.label
  const cats = Object.keys(batch.by_category || {})
  const scope = cats.length
    ? cats.map((c) => CATEGORY_SHORT[c] || c).join(' + ')
    : '评估'
  const stamp = formatBatchStamp(batch.started_at || 0)
  return stamp ? `${scope} · ${stamp}` : scope
}

/** Wilson score interval，和后端 baseline.py 同公式，用于报告页的 CI 须线。 */
function wilsonCI(passed: number, trials: number): [number, number] | null {
  if (trials <= 0) return null
  const z = 1.96
  const z2 = z * z
  const p = passed / trials
  const denom = 1 + z2 / trials
  const center = (p + z2 / (2 * trials)) / denom
  const half =
    (z * Math.sqrt(p * (1 - p) / trials + z2 / (4 * trials * trials))) / denom
  return [Math.max(0, center - half), Math.min(1, center + half)]
}

function HelpTip({ text }: { text: string }) {
  return (
    <span
      title={text}
      className="inline-flex h-3.5 w-3.5 shrink-0 cursor-help items-center justify-center rounded-full border border-border-primary text-[9px] text-text-tertiary hover:text-text-primary"
    >
      ?
    </span>
  )
}

export default function Evaluation() {
  const [tab, setTab] = useState<Tab>('experiments')

  const [batches, setBatches] = useState<EvalBatchSummary[]>([])
  const [selected, setSelected] = useState('')
  const [report, setReport] = useState<EvalReport | null>(null)
  const [loading, setLoading] = useState(false)
  const [expandedCase, setExpandedCase] = useState('')

  const [catalog, setCatalog] = useState<EvalCaseCatalog | null>(null)
  const [catalogError, setCatalogError] = useState('')

  // 跨批次通过率趋势（可选增强：接口失败不影响主流程）
  const [metrics, setMetrics] = useState<EvalMetricPoint[]>([])

  const [baselineStar, setBaselineStar] = useState('')
  const [baselineId, setBaselineId] = useState('')
  const [currentId, setCurrentId] = useState('')
  const [comparison, setComparison] = useState<EvalComparison | null>(null)
  const [comparing, setComparing] = useState(false)

  const [showRunModal, setShowRunModal] = useState(false)
  const [runPrefill, setRunPrefill] = useState<{
    cases: string[]
    trials?: number
    validateOnly?: boolean
  } | null>(null)
  const [runs, setRuns] = useState<EvalRunStatus[]>([])
  const [runError, setRunError] = useState('')
  const prevRunningRef = useRef<Set<string>>(new Set())

  const loadBatches = useCallback(async () => {
    setLoading(true)
    try {
      const res = await evalApi.batches()
      const list = res.batches || []
      setBatches(list)
      setSelected((prev) => prev || list[0]?.batch_id || '')
      setCurrentId((prev) => prev || list[0]?.batch_id || '')
      setBaselineId((prev) => prev || list[1]?.batch_id || list[0]?.batch_id || '')
      setBaselineStar((prev) => prev || list[1]?.batch_id || list[0]?.batch_id || '')
    } finally {
      setLoading(false)
    }
  }, [])

  const loadCatalog = useCallback(async () => {
    try {
      setCatalog(await evalApi.cases())
      setCatalogError('')
    } catch (e: any) {
      setCatalogError(e?.message || '用例目录加载失败')
    }
  }, [])

  const loadMetrics = useCallback(async () => {
    try {
      const res = await evalApi.metrics()
      setMetrics(res.points || [])
    } catch {
      /* 趋势图是可选增强，失败时静默降级为不显示 */
    }
  }, [])

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
    loadCatalog()
    loadMetrics()
    pollRuns()
  }, [loadBatches, loadCatalog, loadMetrics, pollRuns])

  useEffect(() => {
    if (!runs.some((r) => r.status === 'running')) return
    const timer = setInterval(pollRuns, 2500)
    return () => clearInterval(timer)
  }, [runs, pollRuns])

  useEffect(() => {
    const running = new Set(
      runs.filter((r) => r.status === 'running').map((r) => r.run_id)
    )
    let finished = false
    for (const id of prevRunningRef.current) {
      if (!running.has(id)) finished = true
    }
    prevRunningRef.current = running
    if (finished) {
      loadBatches()
      loadCatalog()
      loadMetrics()
    }
  }, [runs, loadBatches, loadCatalog, loadMetrics])

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

  const runCompare = useCallback(async () => {
    if (!baselineId || !currentId || baselineId === currentId) return
    setComparing(true)
    try {
      setComparison(await evalApi.compare(baselineId, currentId))
    } finally {
      setComparing(false)
    }
  }, [baselineId, currentId])

  // 切到对比页且两个 batch 就绪时自动出一次结论，避免用户面对空面板
  const autoCompareKey = `${baselineId}|${currentId}`
  const lastAutoKey = useRef('')
  useEffect(() => {
    if (tab !== 'compare') return
    if (!baselineId || !currentId || baselineId === currentId) return
    if (lastAutoKey.current === autoCompareKey && comparison) return
    lastAutoKey.current = autoCompareKey
    runCompare()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab, autoCompareKey])

  const startRun = async (payload: EvalRunPayload) => {
    setRunError('')
    try {
      await evalApi.run(payload)
      setShowRunModal(false)
      setRunPrefill(null)
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

  const openRunModal = (prefill?: typeof runPrefill) => {
    setRunPrefill(prefill ?? null)
    setRunError('')
    setShowRunModal(true)
  }

  const caseGroups = useMemo(() => {
    if (!report) return []
    const groups = new Map<string, EvalTrial[]>()
    for (const trial of report.results || []) {
      const list = groups.get(trial.case_id) || []
      list.push(trial)
      groups.set(trial.case_id, list)
    }
    const built = [...groups.entries()].map(([caseId, trials]) => {
      const completed = trials.filter((t) => t.status === 'completed')
      const passed = completed.filter((t) => t.passed)
      return {
        caseId,
        category: trials[0]?.category || '',
        severity: trials[0]?.severity || 'medium',
        trials,
        completed: completed.length,
        passed: passed.length,
        passRate: completed.length ? passed.length / completed.length : 0,
        ci: wilsonCI(passed.length, completed.length),
      }
    })
    // 失败置顶：安全类失败最优先，其次其它失败，再通过率升序
    const rank = (g: (typeof built)[number]) => {
      const failing = g.passRate < 1
      if (failing && g.category === 'abnormal') return 0
      if (failing) return 1
      return 2
    }
    built.sort((a, b) => rank(a) - rank(b) || a.passRate - b.passRate)
    return built
  }, [report])

  const runningCount = runs.filter((r) => r.status === 'running').length

  return (
    <WorkspacePage
      title="评估工作台"
      description="用例库 → 跑基线 → 改 Prompt 后对比，用统计显著性判断能否合入。"
      wide
      actions={
        <div className="flex items-center gap-2">
          <Button variant="ghost" onClick={() => { loadBatches(); loadCatalog(); loadMetrics() }} disabled={loading}>
            <RefreshCw size={16} className={loading ? 'animate-spin' : ''} />
          </Button>
          <Button variant="primary" onClick={() => openRunModal()}>
            <Play size={14} />
            运行评估
          </Button>
        </div>
      }
    >
      <TabBar
        tab={tab}
        onChange={setTab}
        caseCount={catalog?.total ?? 0}
        batchCount={batches.length}
        runningCount={runningCount}
      />

      {runningCount > 0 && (
        <RunPanel
          runs={runs.slice(0, 3)}
          onViewReport={(runId) => {
            setSelected(runId)
            setExpandedCase('')
            setTab('experiments')
          }}
        />
      )}

      {tab === 'cases' && (
        <CasesTab
          catalog={catalog}
          error={catalogError}
          onReload={loadCatalog}
          onRunSelected={(ids) => openRunModal({ cases: ids })}
          onValidate={() => openRunModal({ cases: [], validateOnly: true })}
        />
      )}

      {tab === 'experiments' && (
        <ExperimentsTab
          batches={batches}
          metrics={metrics}
          selected={selected}
          onSelect={setSelected}
          report={report}
          caseGroups={caseGroups}
          expandedCase={expandedCase}
          onToggle={(id) => setExpandedCase((prev) => (prev === id ? '' : id))}
          baselineStar={baselineStar}
          onStar={setBaselineStar}
          onRun={() => openRunModal()}
          onGoCompare={() => setTab('compare')}
        />
      )}

      {tab === 'compare' && (
        <CompareTab
          batches={batches}
          baselineId={baselineId}
          currentId={currentId}
          onBaseline={(id) => { setBaselineId(id); setComparison(null) }}
          onCurrent={(id) => { setCurrentId(id); setComparison(null) }}
          comparison={comparison}
          comparing={comparing}
          onCompare={runCompare}
          onRerun={(ids) => openRunModal({ cases: ids, trials: 10 })}
        />
      )}

      <RunModal
        open={showRunModal}
        onClose={() => { setShowRunModal(false); setRunPrefill(null) }}
        onSubmit={startRun}
        error={runError}
        catalog={catalog}
        prefill={runPrefill}
        batches={batches}
      />
    </WorkspacePage>
  )
}

function TabBar({
  tab,
  onChange,
  caseCount,
  batchCount,
  runningCount,
}: {
  tab: Tab
  onChange: (t: Tab) => void
  caseCount: number
  batchCount: number
  runningCount: number
}) {
  const items: { key: Tab; label: string; icon: ReactNode; hint: string }[] = [
    { key: 'cases', label: '用例库', icon: <Database size={14} />, hint: `${caseCount}` },
    { key: 'experiments', label: '实验', icon: <FlaskConical size={14} />, hint: `${batchCount}` },
    { key: 'compare', label: '对比', icon: <GitCompare size={14} />, hint: runningCount ? '运行中' : '门禁' },
  ]
  return (
    <div className="mb-5 flex items-center gap-1 border-b border-border-primary">
      {items.map((item) => {
        const active = tab === item.key
        return (
          <button
            key={item.key}
            onClick={() => onChange(item.key)}
            className={`flex items-center gap-1.5 border-b-2 px-3.5 py-2.5 text-[13px] transition-colors ${
              active
                ? 'border-accent-primary font-medium text-text-primary'
                : 'border-transparent text-text-secondary hover:text-text-primary'
            }`}
          >
            {item.icon}
            {item.label}
            <span className="rounded-full bg-bg-tertiary px-1.5 py-0.5 text-[10px] text-text-tertiary">
              {item.hint}
            </span>
          </button>
        )
      })}
      <div className="ml-auto pb-2 text-[11px] text-text-tertiary">
        改 Prompt / 模型 / 工具策略后，先过评估再合入
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/* 用例库 Dataset                                                       */
/* ------------------------------------------------------------------ */

function CasesTab({
  catalog,
  error,
  onReload,
  onRunSelected,
  onValidate,
}: {
  catalog: EvalCaseCatalog | null
  error: string
  onReload: () => void
  onRunSelected: (ids: string[]) => void
  onValidate: () => void
}) {
  const [query, setQuery] = useState('')
  const [category, setCategory] = useState('')
  const [checked, setChecked] = useState<Set<string>>(new Set())
  const [expanded, setExpanded] = useState('')

  const cases = catalog?.cases || []
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    return cases.filter((c) => {
      if (category && c.category !== category) return false
      if (!q) return true
      return (
        c.id.toLowerCase().includes(q) ||
        c.topic.toLowerCase().includes(q) ||
        c.prompt.toLowerCase().includes(q) ||
        c.tags.some((t) => t.toLowerCase().includes(q)) ||
        c.fixture.toLowerCase().includes(q)
      )
    })
  }, [cases, query, category])

  const allFilteredIds = filtered.map((c) => c.id)
  const allChecked = allFilteredIds.length > 0 && allFilteredIds.every((id) => checked.has(id))

  const toggle = (id: string) => {
    setChecked((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const toggleAll = () => {
    setChecked((prev) => {
      const next = new Set(prev)
      if (allChecked) allFilteredIds.forEach((id) => next.delete(id))
      else allFilteredIds.forEach((id) => next.add(id))
      return next
    })
  }

  const grouped = useMemo(() => {
    const map = new Map<string, EvalCase[]>()
    for (const c of filtered) {
      const list = map.get(c.category) || []
      list.push(c)
      map.set(c.category, list)
    }
    return [...map.entries()].sort((a, b) => a[0].localeCompare(b[0]))
  }, [filtered])

  if (error && !catalog) {
    return (
      <div className="rounded-xl border border-status-error/30 bg-status-error/5 p-6 text-center text-sm text-status-error">
        {error}
        <div className="mt-3"><Button variant="secondary" onClick={onReload}>重试</Button></div>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-border-primary bg-bg-secondary p-4">
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative min-w-[220px] flex-1">
            <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-text-tertiary" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="搜索用例 ID / 主题 / 断言 / fixture"
              className="h-9 w-full rounded-lg border border-border-primary bg-bg-primary pl-8 pr-3 text-[13px] text-text-primary placeholder:text-text-tertiary"
            />
          </div>
          <div className="flex flex-wrap items-center gap-1.5">
            <button
              onClick={() => setCategory('')}
              className={`rounded-lg border px-2.5 py-1.5 text-xs ${!category ? 'border-border-primary bg-accent-soft font-medium' : 'border-border-primary text-text-secondary'}`}
            >
              全部 {cases.length}
            </button>
            {(catalog?.categories || []).map((cat) => (
              <button
                key={cat}
                onClick={() => setCategory(cat)}
                title={CATEGORY_HINTS[cat]}
                className={`rounded-lg border px-2.5 py-1.5 text-xs ${category === cat ? 'border-border-primary bg-accent-soft font-medium' : 'border-border-primary text-text-secondary'}`}
              >
                {cat} {cases.filter((c) => c.category === cat).length}
              </button>
            ))}
          </div>
        </div>
        {category && (
          <div className="mt-2.5 flex items-start gap-1.5 text-[11px] text-text-tertiary">
            <Info size={12} className="mt-0.5 shrink-0" />
            {CATEGORY_HINTS[category]}
          </div>
        )}
        <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-border-secondary pt-3">
          <Button variant="secondary" size="sm" onClick={toggleAll} disabled={!filtered.length}>
            {allChecked ? <Check size={12} /> : <Layers size={12} />}
            {allChecked ? '取消全选' : '全选当前'}
          </Button>
          <span className="text-xs text-text-tertiary">
            已选 <span className="font-medium text-text-primary">{checked.size}</span> / {cases.length}
          </span>
          <div className="ml-auto flex items-center gap-2">
            <Button variant="ghost" size="sm" onClick={onValidate}>
              <CheckCircle2 size={12} />
              仅校验用例（免费）
            </Button>
            <Button
              variant="primary"
              size="sm"
              disabled={checked.size === 0}
              onClick={() => onRunSelected([...checked])}
            >
              <Play size={12} />
              运行所选 {checked.size > 0 ? `(${checked.size})` : ''}
            </Button>
          </div>
        </div>
      </div>

      {catalog?.errors?.length ? (
        <div className="rounded-lg border border-status-warning/30 bg-status-warning/5 px-3 py-2 text-xs text-status-warning">
          用例校验告警：{catalog.errors.join('；')}
        </div>
      ) : null}

      {grouped.length === 0 ? (
        <div className="rounded-xl border border-dashed border-border-primary py-16 text-center text-sm text-text-secondary">
          没有匹配的用例
        </div>
      ) : (
        grouped.map(([cat, list]) => (
          <div key={cat} className="overflow-hidden rounded-xl border border-border-primary">
            <div className="flex items-center gap-2 border-b border-border-primary bg-bg-tertiary/50 px-4 py-2.5">
              <span className="font-mono text-xs font-medium text-text-secondary">{CATEGORY_LABELS[cat] || cat}</span>
              <HelpTip text={CATEGORY_HINTS[cat] || '评估用例类别'} />
              <span className="text-[11px] text-text-tertiary">{list.length} 个用例</span>
            </div>
            <table className="w-full">
              <thead>
                <tr className="border-b border-border-secondary bg-bg-tertiary/30">
                  <Th className="w-8"></Th>
                  <Th>用例</Th>
                  <Th>严重度</Th>
                  <Th>断言</Th>
                  <Th>上次通过率</Th>
                  <Th>Fixture</Th>
                </tr>
              </thead>
              <tbody>
                {list.map((c) => {
                  const isOpen = expanded === c.id
                  return (
                    <Fragment key={c.id}>
                      <tr className="cursor-pointer border-b border-border-secondary last:border-0 hover:bg-bg-hover/50" onClick={() => toggle(c.id)}>
                        <td className="px-4 py-2.5" onClick={(e) => e.stopPropagation()}>
                          <input
                            type="checkbox"
                            checked={checked.has(c.id)}
                            onChange={() => toggle(c.id)}
                            className="h-3.5 w-3.5 cursor-pointer accent-accent-primary"
                          />
                        </td>
                        <td className="px-2 py-2.5">
                          <div className="flex items-center gap-1.5">
                            {isOpen ? <ChevronDown size={13} className="text-text-tertiary" /> : <ChevronRight size={13} className="text-text-tertiary" />}
                            <span className="font-mono text-xs font-medium">{c.id}</span>
                            {c.has_judge && <Badge variant="info">Judge</Badge>}
                          </div>
                          <div className="mt-0.5 pl-5 text-[11px] text-text-tertiary">{c.topic || '—'}</div>
                        </td>
                        <td className="px-3 py-2.5"><Badge variant={severityVariant(c.severity)}>{c.severity}</Badge></td>
                        <td className="px-3 py-2.5">
                          <span className="flex items-center gap-1 text-xs text-text-secondary"><ListChecks size={12} />{c.expect_count}</span>
                        </td>
                        <td className="w-44 px-3 py-2.5">
                          {c.last_pass_rate == null ? (
                            <span className="text-[11px] text-text-tertiary">未跑过</span>
                          ) : (
                            <div className="flex items-center gap-2">
                              <RateBar passed={Math.round(c.last_pass_rate * c.last_trials)} total={c.last_trials} ci={wilsonCI(Math.round(c.last_pass_rate * c.last_trials), c.last_trials)} />
                              <span className="w-9 shrink-0 text-right text-xs text-text-secondary">{Math.round(c.last_pass_rate * 100)}%</span>
                            </div>
                          )}
                        </td>
                        <td className="px-3 py-2.5 font-mono text-[11px] text-text-tertiary">{c.fixture || '—'}</td>
                      </tr>
                      {isOpen && (
                        <tr className="bg-bg-tertiary/30">
                          <td colSpan={6} className="px-4 py-3">
                            <CaseDefinitionCard item={c} onToggleDetail={() => setExpanded('')} />
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  )
                })}
              </tbody>
            </table>
          </div>
        ))
      )}
      <div className="flex items-center gap-1.5 text-[11px] text-text-tertiary">
        <BookOpen size={12} />
        用例定义来自 <code className="font-mono">eval/cases/*.yaml</code>，此页只读。YAML 是唯一真源，改用例请直接改文件后点「仅校验用例」。
      </div>
    </div>
  )
}

function CaseDefinitionCard({ item, onToggleDetail }: { item: EvalCase; onToggleDetail: () => void }) {
  return (
    <div className="space-y-2.5 text-xs">
      <div className="flex items-start justify-between gap-3">
        <div className="text-text-secondary">
          <span className="font-medium text-text-primary">Prompt：</span>{item.prompt}
        </div>
        <button onClick={onToggleDetail} className="shrink-0 text-text-tertiary hover:text-text-primary"><X size={13} /></button>
      </div>
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="text-text-tertiary">断言规则：</span>
        {item.expect_rules.map((r, i) => (
          <span key={`${r}-${i}`} className="rounded border border-border-primary bg-bg-secondary px-1.5 py-0.5 font-mono text-[11px] text-text-secondary">{r}</span>
        ))}
      </div>
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-text-tertiary">
        <span>审批策略：<code className="font-mono">{item.approvals}</code></span>
        <span>超时 {item.timeout_seconds}s</span>
        <span>最大 {item.max_turns} 轮</span>
        <span>来源 <code className="font-mono">{item.source}</code></span>
        {item.tags.length > 0 && <span>tags: {item.tags.join('、')}</span>}
      </div>
      {item.notes && <div className="rounded-md border border-border-secondary bg-bg-secondary px-2.5 py-1.5 text-[11px] text-text-secondary">设计意图：{item.notes}</div>}
    </div>
  )
}

/* ------------------------------------------------------------------ */
/* 通过率趋势 sparkline（手写 SVG，无新依赖）                          */
/* ------------------------------------------------------------------ */

/** 颜色全部走 CSS 变量，明暗主题自动适配；不引图表库。 */
function Sparkline({
  points,
  highlightId,
  baselineId,
}: {
  points: EvalMetricPoint[]
  highlightId?: string
  baselineId?: string
}) {
  const width = 200
  const height = 36
  const padX = 5
  const padY = 6
  const n = points.length
  if (n < 2) return null

  const x = (i: number) => padX + (i * (width - padX * 2)) / (n - 1)
  const y = (v: number) =>
    padY + (1 - Math.min(Math.max(v, 0), 1)) * (height - padY * 2)
  const line = points
    .map((p, i) => `${x(i).toFixed(1)},${y(p.pass_rate).toFixed(1)}`)
    .join(' ')

  return (
    <svg
      width="100%"
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label="各批次通过率趋势"
      className="block"
    >
      {/* 100% 参考线 */}
      <line
        x1={padX}
        y1={y(1)}
        x2={width - padX}
        y2={y(1)}
        stroke="var(--border-primary)"
        strokeWidth="1"
        strokeDasharray="2 3"
      />
      <polyline
        points={line}
        fill="none"
        stroke="var(--text-secondary)"
        strokeWidth="1.5"
        strokeLinejoin="round"
        strokeLinecap="round"
      />
      {points.map((p, i) => {
        const isBaseline = p.batch_id === baselineId
        const isCurrent = p.batch_id === highlightId
        const color = isBaseline
          ? 'var(--status-warning)'
          : isCurrent
            ? 'var(--status-info)'
            : 'var(--text-tertiary)'
        const r = isBaseline || isCurrent ? 3.2 : 1.8
        return (
          <g key={p.batch_id}>
            <title>
              {`${p.label || `${formatBatchStamp(p.started_at)} · ${p.cases} 用例`} · ${Math.round(p.pass_rate * 100)}% · ${p.cases} 用例 / ${p.trials} 试跑${isBaseline ? ' · 基准 ★' : ''}${isCurrent ? ' · 当前选中' : ''}`}
            </title>
            {(isBaseline || isCurrent) && (
              <circle
                cx={x(i)}
                cy={y(p.pass_rate)}
                r={5.5}
                fill="none"
                stroke={color}
                strokeWidth="1"
                opacity="0.65"
              />
            )}
            <circle
              cx={x(i)}
              cy={y(p.pass_rate)}
              r={r}
              fill={color}
              stroke="var(--bg-secondary)"
              strokeWidth="1"
            />
          </g>
        )
      })}
    </svg>
  )
}

/* ------------------------------------------------------------------ */
/* 实验 Experiments                                                    */
/* ------------------------------------------------------------------ */

function ExperimentsTab({
  batches,
  metrics,
  selected,
  onSelect,
  report,
  caseGroups,
  expandedCase,
  onToggle,
  baselineStar,
  onStar,
  onRun,
  onGoCompare,
}: {
  batches: EvalBatchSummary[]
  metrics: EvalMetricPoint[]
  selected: string
  onSelect: (id: string) => void
  report: EvalReport | null
  caseGroups: {
    caseId: string
    category: string
    severity: string
    trials: EvalTrial[]
    completed: number
    passed: number
    passRate: number
    ci: [number, number] | null
  }[]
  expandedCase: string
  onToggle: (id: string) => void
  baselineStar: string
  onStar: (id: string) => void
  onRun: () => void
  onGoCompare: () => void
}) {
  const [onlyFailed, setOnlyFailed] = useState(false)
  const visibleGroups = onlyFailed ? caseGroups.filter((g) => g.passRate < 1) : caseGroups
  const failedCount = caseGroups.filter((g) => g.passRate < 1).length

  if (batches.length === 0) {
    return <OnboardingGuide onRun={onRun} onValidate={() => onRun()} />
  }

  return (
    <div className="flex gap-5">
      <div className="w-60 shrink-0 space-y-2">
        <div className="flex items-center justify-between px-1 text-[11px] text-text-tertiary">
          <span>{batches.length} 个批次</span>
          <span className="flex items-center gap-1"><Star size={11} /> 基准</span>
        </div>
        <div className="flex items-center gap-1 px-1 text-[10px] text-text-tertiary">
          <TrendingUp size={10} />
          {metrics.length >= 2
            ? `通过率趋势 · ${metrics.length} 批（★ 基准 / ◎ 当前选中）`
            : '批次不足 2 个，暂无趋势'}
          <HelpTip text="每张卡片下方是全量批次按时间排序的通过率折线，用来看「改完 Prompt 之后整体是变好还是变坏」——AI 测试不会 100% 通过，趋势比单批总分更重要。橙点是基准批次，蓝圈是当前选中批次，鼠标悬停可看该点的通过率与试跑数。" />
        </div>
        {batches.map((b) => {
          const active = b.batch_id === selected
          const starred = b.batch_id === baselineStar
          return (
            <div key={b.batch_id} className="relative">
              <button
                onClick={() => onSelect(b.batch_id)}
                className={`w-full rounded-xl border px-3.5 py-3 pr-9 text-left transition-colors ${
                  active ? 'border-border-primary bg-accent-soft' : 'border-border-primary bg-bg-secondary hover:bg-bg-hover'
                }`}
              >
                <div className="truncate text-sm font-medium">{batchDisplayName(b)}</div>
                <div className="mt-0.5 truncate font-mono text-[11px] text-text-tertiary">{shortId(b.batch_id)}</div>
                <div className="mt-2 flex items-center gap-2">
                  <Badge variant={rateVariant(b.pass_rate)}>{Math.round(b.pass_rate * 100)}%</Badge>
                  <span className="text-[11px] text-text-tertiary">{b.passed}/{b.completed} · ¥{b.total_cost_cny?.toFixed(2)}</span>
                </div>
                <div className="mt-1 text-[11px] text-text-tertiary">
                  {b.started_at ? new Date(b.started_at * 1000).toLocaleString() : '-'}
                </div>
                {metrics.length >= 2 && (
                  <div className="mt-2 border-t border-border-secondary pt-1.5">
                    <Sparkline points={metrics} highlightId={b.batch_id} baselineId={baselineStar} />
                  </div>
                )}
              </button>
              <button
                title={starred ? '当前基准' : '设为对比基准'}
                onClick={() => onStar(b.batch_id)}
                className={`absolute right-3 top-3 ${starred ? 'text-status-warning' : 'text-text-tertiary hover:text-text-primary'}`}
              >
                <Star size={13} fill={starred ? 'currentColor' : 'none'} />
              </button>
            </div>
          )
        })}
        <button
          onClick={onGoCompare}
          className="flex w-full items-center justify-center gap-1.5 rounded-lg border border-border-primary py-2 text-xs text-text-secondary hover:bg-bg-hover"
        >
          <GitCompare size={12} /> 去对比页
        </button>
      </div>

      <div className="min-w-0 flex-1 space-y-5">
        {report ? (
          <>
            <SummaryCards report={report} />
            <CategoryBars report={report} />
            <div className="flex items-center gap-2">
              <div className="flex items-center gap-1.5 text-xs text-text-secondary">
                <Filter size={12} /> 用例结果
                <HelpTip text="默认把失败用例排在最前，其中 abnormal（危险拦截）类失败优先级最高——这类用例红了代表安全治理退化，必须最先看。" />
              </div>
              <button
                onClick={() => setOnlyFailed((v) => !v)}
                className={`ml-auto rounded-lg border px-2.5 py-1 text-xs ${onlyFailed ? 'border-status-error/30 bg-status-error/10 text-status-error' : 'border-border-primary text-text-secondary'}`}
              >
                只看失败{failedCount > 0 ? ` (${failedCount})` : ''}
              </button>
              <button onClick={onGoCompare} className="rounded-lg border border-border-primary px-2.5 py-1 text-xs text-text-secondary hover:bg-bg-hover">
                与基准对比 <ArrowRight size={11} className="inline" />
              </button>
            </div>
            <CaseTable
              groups={visibleGroups}
              expandedCase={expandedCase}
              onToggle={onToggle}
              emptyHint="没有失败用例"
            />
          </>
        ) : (
          <div className="rounded-xl border border-dashed border-border-primary py-20 text-center text-sm text-text-secondary">
            加载报告中…
          </div>
        )}
      </div>
    </div>
  )
}

function OnboardingGuide({ onRun, onValidate }: { onRun: () => void; onValidate: () => void }) {
  const steps = [
    { n: '1', title: '先校验用例', desc: '不调模型、不花钱，确认 YAML 写得对', action: onValidate, label: '免费校验' },
    { n: '2', title: '跑一次基线', desc: '选定用例跑一批，作为之后的对比基准', action: onRun, label: '运行评估' },
    { n: '3', title: '改完再对比', desc: '改 Prompt / 模型 / 工具策略后重跑，进对比页看门禁结论', action: () => {}, label: '' },
  ]
  return (
    <div className="rounded-xl border border-dashed border-border-primary p-8">
      <div className="mb-1 flex items-center gap-2 text-sm font-medium"><FlaskConical size={16} className="text-text-tertiary" />还没有评估报告</div>
      <p className="mb-6 text-xs text-text-tertiary">评估驱动的闭环是：写用例 → 跑基线 → 对比实验 → 回归门禁。按这三步开始：</p>
      <div className="grid gap-3 sm:grid-cols-3">
        {steps.map((s) => (
          <div key={s.n} className="rounded-lg border border-border-primary bg-bg-secondary p-4">
            <div className="mb-2 flex h-6 w-6 items-center justify-center rounded-full bg-accent-soft text-xs font-medium">{s.n}</div>
            <div className="text-[13px] font-medium">{s.title}</div>
            <div className="mt-1 text-[11px] leading-relaxed text-text-tertiary">{s.desc}</div>
            {s.label && (
              <Button variant="secondary" size="sm" className="mt-3" onClick={s.action}>{s.label}</Button>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

function SummaryCards({ report }: { report: EvalReport }) {
  const ci = report.pass_rate_ci95 || wilsonCI(report.passed, report.completed)
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
      <Stat label="试跑" value={String(report.trials)} />
      <Stat label="完成" value={String(report.completed)} />
      <Stat label="通过" value={String(report.passed)} />
      <Stat label="失败" value={String(report.failed)} tone={report.failed > 0 ? 'error' : undefined} />
      <Stat
        label={<span className="flex items-center gap-1">通过率 <HelpTip text="通过率 = 通过试次 / 完成试次。注意试跑次数少时这个数字波动很大，看旁边的 95% 置信区间更稳妥。" /></span>}
        value={`${Math.round(report.pass_rate * 100)}%`}
        sub={ci ? `95% CI [${ci[0].toFixed(2)}, ${ci[1].toFixed(2)}]` : undefined}
      />
      <Stat label="总成本" value={`¥${(report.total_cost_cny || 0).toFixed(2)}`} sub={`耗时 ${(report.duration_ms / 1000).toFixed(0)}s`} />
    </div>
  )
}

function Stat({ label, value, sub, tone }: { label: ReactNode; value: string; sub?: string; tone?: 'error' }) {
  return (
    <div className="rounded-xl border border-border-primary bg-bg-secondary px-3.5 py-3">
      <div className="text-[11px] text-text-tertiary">{label}</div>
      <div className={`mt-1 text-lg font-semibold ${tone === 'error' ? 'text-status-error' : ''}`}>{value}</div>
      {sub && <div className="mt-0.5 text-[11px] text-text-tertiary">{sub}</div>}
    </div>
  )
}

function CategoryBars({ report }: { report: EvalReport }) {
  const entries = Object.entries(report.by_category || {})
  if (entries.length === 0) return null
  return (
    <div className="rounded-xl border border-border-primary bg-bg-secondary p-4">
      <div className="mb-3 flex items-center gap-1.5 text-xs font-medium text-text-secondary">
        按类别通过率
        <HelpTip text="四类用例考的东西不同：core 正常诊断、boundary 边界拒答、abnormal 危险拦截、faq 开放问答。abnormal 必须保持全绿。" />
      </div>
      <div className="space-y-2.5">
        {entries.map(([category, stat]) => (
          <div key={category} className="flex items-center gap-3">
            <div className="w-20 shrink-0 font-mono text-xs text-text-secondary">{category}</div>
            <RateBar passed={stat.passed} total={stat.completed} ci={wilsonCI(stat.passed, stat.completed)} />
            <div className="w-24 shrink-0 text-right text-xs text-text-tertiary">{stat.passed}/{stat.completed}</div>
          </div>
        ))}
      </div>
    </div>
  )
}

/** 通过率条形图：填充为通过比例，细线标注 Wilson 95% 区间 */
function RateBar({ passed, total, ci }: { passed: number; total: number; ci?: [number, number] | null }) {
  const rate = total ? passed / total : 0
  const low = ci ? Math.max(0, ci[0]) : 0
  const high = ci ? Math.min(1, ci[1]) : 0
  return (
    <div className="relative h-3 flex-1 overflow-visible rounded-full bg-bg-tertiary">
      <div className="absolute inset-y-0 left-0 rounded-full bg-status-success/70" style={{ width: `${rate * 100}%` }} />
      {ci && (
        <>
          <div className="absolute inset-y-[-3px] w-px bg-text-tertiary" style={{ left: `${low * 100}%` }} />
          <div className="absolute inset-y-[-3px] w-px bg-text-tertiary" style={{ left: `${high * 100}%` }} />
          <div className="absolute inset-y-[-3px] h-[3px] border-x border-text-tertiary" style={{ left: `${low * 100}%`, width: `${(high - low) * 100}%` }} />
        </>
      )}
      <div className="absolute top-[-4px] h-[calc(100%+8px)] w-0.5 bg-text-primary" style={{ left: `calc(${rate * 100}% - 1px)` }} />
    </div>
  )
}

function CaseTable({
  groups,
  expandedCase,
  onToggle,
  emptyHint,
}: {
  groups: {
    caseId: string
    category: string
    severity: string
    trials: EvalTrial[]
    completed: number
    passed: number
    passRate: number
    ci: [number, number] | null
  }[]
  expandedCase: string
  onToggle: (id: string) => void
  emptyHint?: string
}) {
  if (groups.length === 0) {
    return <div className="rounded-xl border border-dashed border-border-primary py-12 text-center text-xs text-text-tertiary">{emptyHint || '暂无用例'}</div>
  }
  return (
    <div className="overflow-hidden rounded-xl border border-border-primary">
      <table className="w-full">
        <thead>
          <tr className="border-b border-border-primary bg-bg-tertiary/50">
            <Th>用例</Th>
            <Th>类别</Th>
            <Th>严重度</Th>
            <Th><span className="flex items-center gap-1">通过率 <HelpTip text="绿色填充是实测通过率，两根须线是 Wilson 95% 置信区间：真实通过率大概率落在这个范围内。试次越少，区间越宽。" /></span></Th>
            <Th>试次</Th>
          </tr>
        </thead>
        <tbody>
          {groups.map((g) => {
            const expanded = expandedCase === g.caseId
            const failing = g.passRate < 1
            return (
              <Fragment key={g.caseId}>
                <tr onClick={() => onToggle(g.caseId)} className="cursor-pointer border-b border-border-secondary last:border-0 hover:bg-bg-hover/50">
                  <td className="px-4 py-3">
                    <span className="flex items-center gap-1.5 text-sm font-medium">
                      {expanded ? <ChevronDown size={14} className="text-text-tertiary" /> : <ChevronRight size={14} className="text-text-tertiary" />}
                      {g.caseId}
                      {failing && g.category === 'abnormal' && <Badge variant="error"><span className="flex items-center gap-0.5"><ShieldAlert size={10} />安全退化</span></Badge>}
                    </span>
                  </td>
                  <td className="px-4 py-3"><Badge variant="default">{g.category || '-'}</Badge></td>
                  <td className="px-4 py-3"><Badge variant={severityVariant(g.severity)}>{g.severity || '-'}</Badge></td>
                  <td className="w-56 px-4 py-3">
                    <div className="flex items-center gap-2">
                      <RateBar passed={g.passed} total={g.completed} ci={g.ci} />
                      <span className="w-9 shrink-0 text-right text-xs text-text-secondary">{Math.round(g.passRate * 100)}%</span>
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex gap-1">
                      {g.trials.map((t) => (
                        <span key={t.trial_no} title={`trial ${t.trial_no}: ${t.status}`} className={`inline-block h-2.5 w-2.5 rounded-full ${t.status !== 'completed' ? 'bg-status-warning' : t.passed ? 'bg-status-success' : 'bg-status-error'}`} />
                      ))}
                    </div>
                  </td>
                </tr>
                {expanded && (
                  <tr className="bg-bg-tertiary/30">
                    <td colSpan={5} className="px-4 py-3">
                      <div className="space-y-2.5">
                        {g.trials.map((t) => <TrialDetail key={t.trial_no} trial={t} />)}
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
  const failedScores = trial.scores.filter((s) => s.status === 'fail' || s.status === 'error')
  return (
    <div className="rounded-lg border border-border-secondary bg-bg-secondary p-3">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className="font-mono font-medium">trial #{trial.trial_no}</span>
        <Badge variant={trial.status === 'completed' ? 'default' : 'warning'}>{trial.status}</Badge>
        {trial.status === 'completed' && <Badge variant={trial.passed ? 'success' : 'error'}>{trial.passed ? '通过' : '失败'}</Badge>}
        <span className="text-text-tertiary">{(trial.duration_ms / 1000).toFixed(1)}s · ¥{(trial.cost_cny + trial.judge_cost_cny).toFixed(3)}</span>
        {trial.approvals_requested ? <span className="text-text-tertiary">审批 {trial.approvals_granted}/{trial.approvals_requested}</span> : null}
        <button onClick={() => setShowTools((v) => !v)} className="ml-auto text-text-secondary hover:text-text-primary">工具调用（{trial.tool_calls?.length || 0}）</button>
      </div>
      <div className="mt-2 flex flex-wrap gap-1.5">
        {trial.scores.map((s, i) => (
          <span key={`${s.rule}-${i}`} className={`inline-flex items-center gap-1 rounded border px-1.5 py-0.5 font-mono text-[11px] ${s.status === 'pass' ? 'border-status-success/30 bg-status-success/10 text-status-success' : s.status === 'skip' ? 'border-border-primary bg-bg-tertiary text-text-tertiary' : 'border-status-error/30 bg-status-error/10 text-status-error'}`}>
            {s.rule}
          </span>
        ))}
      </div>
      {failedScores.map((s, i) => (
        <div key={i} className="mt-2 rounded-md border border-status-error/20 bg-status-error/5 px-2.5 py-1.5 text-[11px] text-text-secondary">
          <span className="font-mono text-status-error">{s.rule}</span>
          {s.evidence && Object.keys(s.evidence).length > 0 && (
            <span className="ml-2 font-mono">{Object.entries(s.evidence).slice(0, 3).map(([k, v]) => `${k}=${String(v).slice(0, 80)}`).join(' · ')}</span>
          )}
        </div>
      ))}
      {showTools && (
        <div className="mt-2 space-y-1.5">
          {(trial.tool_calls || []).map((c) => (
            <div key={c.step} className="rounded-md border border-border-secondary px-2.5 py-1.5 text-[11px]">
              <div className="flex items-center gap-2">
                <span className={`h-1.5 w-1.5 rounded-full ${c.ok ? 'bg-status-success' : 'bg-status-error'}`} />
                <span className="font-mono font-medium">{c.tool}</span>
                {c.duration_ms != null && <span className="text-text-tertiary">{c.duration_ms}ms</span>}
              </div>
              {c.input && <div className="mt-1 truncate font-mono text-text-tertiary">{JSON.stringify(c.input)}</div>}
              {c.output && <pre className="mt-1 max-h-32 overflow-y-auto whitespace-pre-wrap font-mono text-text-secondary">{c.output.slice(0, 600)}</pre>}
            </div>
          ))}
        </div>
      )}
      {trial.final_answer && <div className="mt-2 border-l-2 border-border-primary pl-2.5 text-xs text-text-secondary">{trial.final_answer}</div>}
      {trial.error && <div className="mt-2 text-[11px] text-status-error">{trial.error}</div>}
    </div>
  )
}

/* ------------------------------------------------------------------ */
/* 对比 Compare                                                        */
/* ------------------------------------------------------------------ */

type DiffKind = 'regression' | 'improvement' | 'noise' | 'rule'
interface DiffRow { kind: DiffKind; item: CaseComparison }

function CompareTab({
  batches,
  baselineId,
  currentId,
  onBaseline,
  onCurrent,
  comparison,
  comparing,
  onCompare,
  onRerun,
}: {
  batches: EvalBatchSummary[]
  baselineId: string
  currentId: string
  onBaseline: (id: string) => void
  onCurrent: (id: string) => void
  comparison: EvalComparison | null
  comparing: boolean
  onCompare: () => void
  onRerun: (ids: string[]) => void
}) {
  const [filter, setFilter] = useState<'all' | DiffKind>('all')
  const [expanded, setExpanded] = useState('')

  // 逐试次 trace 并排：展开用例行时才拉两批完整报告，按 batch_id 缓存，
  // 所有行共享同一份缓存，切换展开行不会再发请求。
  const reportCache = useRef<Map<string, EvalReport>>(new Map())
  const [tracePair, setTracePair] = useState<{ base: EvalReport | null; cur: EvalReport | null }>({ base: null, cur: null })
  const [traceLoading, setTraceLoading] = useState(false)
  const [traceError, setTraceError] = useState('')

  useEffect(() => {
    if (!expanded || !baselineId || !currentId) return
    const cachedBase = reportCache.current.get(baselineId)
    const cachedCur = reportCache.current.get(currentId)
    if (cachedBase && cachedCur) {
      setTracePair({ base: cachedBase, cur: cachedCur })
      setTraceError('')
      return
    }
    let cancelled = false
    const ensure = async (id: string): Promise<EvalReport> => {
      const hit = reportCache.current.get(id)
      if (hit) return hit
      const rep = await evalApi.report(id)
      reportCache.current.set(id, rep)
      return rep
    }
    setTracePair({ base: null, cur: null })
    setTraceLoading(true)
    setTraceError('')
    Promise.all([ensure(baselineId), ensure(currentId)])
      .then(([base, cur]) => {
        if (!cancelled) setTracePair({ base, cur })
      })
      .catch((e: any) => {
        if (!cancelled) setTraceError(e?.message || '报告明细加载失败')
      })
      .finally(() => {
        if (!cancelled) setTraceLoading(false)
      })
    return () => { cancelled = true }
  }, [expanded, baselineId, currentId])

  const rows = useMemo<DiffRow[]>(() => {
    if (!comparison) return []
    const map = new Map<string, DiffRow>()
    const put = (kind: DiffKind, items: CaseComparison[]) => {
      for (const item of items) {
        if (!map.has(item.case_id)) map.set(item.case_id, { kind, item })
      }
    }
    put('regression', comparison.regressions || [])
    put('rule', comparison.rule_regressions || [])
    put('noise', comparison.drops_within_noise || [])
    put('improvement', comparison.improvements || [])
    return [...map.values()]
  }, [comparison])

  const filtered = filter === 'all' ? rows : rows.filter((r) => r.kind === filter)
  const counts = {
    all: rows.length,
    regression: rows.filter((r) => r.kind === 'regression').length,
    rule: rows.filter((r) => r.kind === 'rule').length,
    improvement: rows.filter((r) => r.kind === 'improvement').length,
    noise: rows.filter((r) => r.kind === 'noise').length,
  }
  const insufficientIds = rows
    .filter((r) => r.item.significance === 'insufficient-samples')
    .map((r) => r.item.case_id)

  if (batches.length < 2) {
    return (
      <div className="rounded-xl border border-dashed border-border-primary py-16 text-center">
        <GitCompare size={30} className="mx-auto mb-3 text-text-tertiary" />
        <p className="text-sm text-text-secondary">至少需要两批报告才能对比</p>
        <p className="mt-2 text-xs text-text-tertiary">跑一次基线，改完 Prompt 再跑一次，然后回到这里看门禁结论</p>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2 rounded-xl border border-border-primary bg-bg-secondary p-3.5">
        <CompareSelect value={baselineId} onChange={onBaseline} placeholder="基线 batch" batches={batches} label="基准 ★" />
        <ArrowRight size={14} className="text-text-tertiary" />
        <CompareSelect value={currentId} onChange={onCurrent} placeholder="当前 batch" batches={batches} label="当前" />
        <Button variant="primary" size="sm" onClick={onCompare} disabled={comparing || !baselineId || !currentId || baselineId === currentId}>
          <Zap size={12} />{comparing ? '对比中…' : '开始对比'}
        </Button>
        <div className="ml-auto flex items-center gap-1 text-[11px] text-text-tertiary">
          <HelpTip text="判定顺序：通过率下降 → 两批样本都 ≥ min_samples(5) 才做单侧双比例 z 检验 → p < alpha(0.05) 才判「显著回归」拦门禁；p ≥ 0.05 归为「噪声内下降」只记录不拦；样本不足则标「样本不足」退回数值比较。" />
          alpha {comparison?.alpha ?? 0.05} · min_samples {comparison?.min_samples ?? 5}
        </div>
      </div>

      {!comparison ? (
        <div className="rounded-xl border border-dashed border-border-primary py-16 text-center text-sm text-text-secondary">
          {comparing ? '计算中…' : '选好两批报告后点「开始对比」'}
        </div>
      ) : (
        <>
          <VerdictBanner comparison={comparison} onRerun={() => onRerun(insufficientIds)} insufficientCount={insufficientIds.length} />
          <MetricCards comparison={comparison} />

          <div className="flex flex-wrap items-center gap-1.5">
            <Filter size={12} className="text-text-tertiary" />
            {([
              ['all', `全部 ${counts.all}`],
              ['regression', `只看回归 ${counts.regression}`],
              ['rule', `规则回归 ${counts.rule}`],
              ['improvement', `只看改进 ${counts.improvement}`],
              ['noise', `噪声内 ${counts.noise}`],
            ] as const).map(([key, label]) => (
              <button
                key={key}
                onClick={() => setFilter(key)}
                className={`rounded-lg border px-2.5 py-1 text-xs ${filter === key ? 'border-border-primary bg-accent-soft font-medium' : 'border-border-primary text-text-secondary'}`}
              >
                {label}
              </button>
            ))}
            {(comparison.missing_cases?.length || comparison.new_cases?.length) ? (
              <span className="ml-auto text-[11px] text-text-tertiary">
                {comparison.missing_cases?.length ? `基线独有 ${comparison.missing_cases.length} 个` : ''}
                {comparison.missing_cases?.length && comparison.new_cases?.length ? ' · ' : ''}
                {comparison.new_cases?.length ? `本次新增 ${comparison.new_cases.length} 个` : ''}
              </span>
            ) : null}
          </div>

          <DiffTable
            rows={filtered}
            expanded={expanded}
            onToggle={(id) => setExpanded((p) => (p === id ? '' : id))}
            tracePair={tracePair}
            traceLoading={traceLoading}
            traceError={traceError}
          />
        </>
      )}
    </div>
  )
}

function VerdictBanner({ comparison, onRerun, insufficientCount }: { comparison: EvalComparison; onRerun: () => void; insufficientCount: number }) {
  const verdict = comparison.verdict
  const status = verdict?.status ?? (comparison.regressions?.length ? 'blocked' : 'pass')
  const reason = verdict?.reason ?? (status === 'blocked' ? '检测到回归，建议阻断合入' : '未检测到回归，可合入')
  const config = status === 'pass'
    ? { icon: <CheckCircle2 size={20} />, title: '可合入', cls: 'border-status-success/30 bg-status-success/8 text-status-success', badge: 'success' as const }
    : status === 'blocked'
      ? { icon: <XCircle size={20} />, title: '阻断', cls: 'border-status-error/30 bg-status-error/8 text-status-error', badge: 'error' as const }
      : { icon: <AlertTriangle size={20} />, title: '样本不足', cls: 'border-status-warning/30 bg-status-warning/8 text-status-warning', badge: 'warning' as const }

  return (
    <div className={`rounded-xl border p-4 ${config.cls}`}>
      <div className="flex items-start gap-3">
        <div className="mt-0.5">{config.icon}</div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium">门禁结论：{config.title}</span>
            <Badge variant={config.badge}>{status}</Badge>
            {verdict?.high_severity_regressions ? <Badge variant="error">{verdict.high_severity_regressions} 个高危</Badge> : null}
          </div>
          <p className="mt-1 text-xs opacity-90">{reason}</p>
          {status === 'insufficient' && insufficientCount > 0 && (
            <div className="mt-2.5 flex flex-wrap items-center gap-2">
              <Button variant="secondary" size="sm" onClick={onRerun}>
                <Play size={12} /> 用 10 次试跑重跑这 {insufficientCount} 个用例
              </Button>
              <span className="text-[11px] opacity-80">样本 ≥ {verdict?.min_samples ?? 5} 次后 z 检验才会生效</span>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function MetricCards({ comparison }: { comparison: EvalComparison }) {
  const o = comparison.overall
  if (!o) return null
  const rateDelta = o.pass_rate_delta
  const costDelta = o.total_cost_delta_cny
  const p95Delta = o.p95_duration_delta_ms
  const cards = [
    {
      label: '整体通过率',
      value: `${Math.round(o.current.pass_rate * 100)}%`,
      sub: `基线 ${Math.round(o.baseline.pass_rate * 100)}% → 当前 ${Math.round(o.current.pass_rate * 100)}%`,
      delta: rateDelta,
      deltaText: `${rateDelta >= 0 ? '+' : ''}${(rateDelta * 100).toFixed(1)}pp`,
      help: '两批全部试次的整体通过率之差。pp 是百分点，不是百分比。',
    },
    {
      label: '总成本',
      value: `¥${o.current.total_cost_cny.toFixed(2)}`,
      sub: `基线 ¥${o.baseline.total_cost_cny.toFixed(2)}`,
      delta: -costDelta,
      deltaText: `${costDelta >= 0 ? '+' : ''}¥${costDelta.toFixed(2)}`,
      help: 'Agent 调用成本 + LLM Judge 成本之和，来自 API usage 记账。',
    },
    {
      label: 'p95 耗时',
      value: `${(o.current.p95_duration_ms / 1000).toFixed(1)}s`,
      sub: `基线 ${(o.baseline.p95_duration_ms / 1000).toFixed(1)}s`,
      delta: -p95Delta,
      deltaText: `${p95Delta >= 0 ? '+' : ''}${(p95Delta / 1000).toFixed(1)}s`,
      help: '95 分位单试次耗时；比平均值更能反映长尾卡顿。',
    },
  ]
  return (
    <div className="grid gap-3 sm:grid-cols-3">
      {cards.map((c) => {
        const good = c.delta >= 0
        return (
          <div key={c.label} className="rounded-xl border border-border-primary bg-bg-secondary p-4">
            <div className="flex items-center gap-1 text-[11px] text-text-tertiary">{c.label}<HelpTip text={c.help} /></div>
            <div className="mt-1 flex items-baseline gap-2">
              <span className="text-xl font-semibold">{c.value}</span>
              <span className={`flex items-center gap-0.5 text-xs ${good ? 'text-status-success' : 'text-status-error'}`}>
                {good ? <TrendingUp size={12} /> : c.delta === 0 ? <Minus size={12} /> : <TrendingDown size={12} />}
                {c.deltaText}
              </span>
            </div>
            <div className="mt-1 text-[11px] text-text-tertiary">{c.sub}</div>
          </div>
        )
      })}
    </div>
  )
}

const KIND_META: Record<DiffKind, { label: string; variant: 'error' | 'success' | 'warning' | 'info' }> = {
  regression: { label: '回归', variant: 'error' },
  rule: { label: '规则回归', variant: 'error' },
  improvement: { label: '改进', variant: 'success' },
  noise: { label: '噪声内', variant: 'warning' },
}

function DiffTable({
  rows,
  expanded,
  onToggle,
  tracePair,
  traceLoading,
  traceError,
}: {
  rows: DiffRow[]
  expanded: string
  onToggle: (id: string) => void
  tracePair: { base: EvalReport | null; cur: EvalReport | null }
  traceLoading: boolean
  traceError: string
}) {
  if (rows.length === 0) {
    return <div className="rounded-xl border border-dashed border-border-primary py-12 text-center text-xs text-text-tertiary">该筛选下没有用例</div>
  }
  return (
    <div className="overflow-hidden rounded-xl border border-border-primary">
      <table className="w-full">
        <thead>
          <tr className="border-b border-border-primary bg-bg-tertiary/50">
            <Th>用例</Th>
            <Th>判定</Th>
            <Th>基线 → 当前</Th>
            <Th><span className="flex items-center gap-1">p 值 <HelpTip text="单侧双比例 z 检验：假设「没变差」，算出纯属运气出现这么大降幅的概率。p < 0.05 才判显著回归。样本 < 5 时不做检验，显示 —。" /></span></Th>
            <Th>规则 diff</Th>
          </tr>
        </thead>
        <tbody>
          {rows.map(({ kind, item }) => {
            const isOpen = expanded === item.case_id
            const meta = KIND_META[kind]
            const sig = item.significance
            return (
              <Fragment key={item.case_id}>
                <tr onClick={() => onToggle(item.case_id)} className="cursor-pointer border-b border-border-secondary last:border-0 hover:bg-bg-hover/50">
                  <td className="px-4 py-3">
                    <span className="flex items-center gap-1.5 text-xs font-medium">
                      {isOpen ? <ChevronDown size={13} className="text-text-tertiary" /> : <ChevronRight size={13} className="text-text-tertiary" />}
                      <span className="font-mono">{item.case_id}</span>
                      {item.severity === 'high' && <ShieldAlert size={12} className="text-status-error" />}
                    </span>
                    <div className="mt-0.5 pl-5 text-[11px] text-text-tertiary">{item.category}</div>
                  </td>
                  <td className="px-3 py-3">
                    <div className="flex flex-wrap items-center gap-1">
                      <Badge variant={meta.variant}>{meta.label}</Badge>
                      {sig === 'insufficient-samples' && <Badge variant="default">样本不足</Badge>}
                    </div>
                  </td>
                  <td className="w-56 px-3 py-3">
                    <div className="flex items-center gap-2">
                      <span className="w-9 shrink-0 text-right font-mono text-[11px] text-text-tertiary">{Math.round(item.baseline_pass_rate * 100)}%</span>
                      <DualRateBar baseline={item.baseline_pass_rate} current={item.current_pass_rate} ci={item.current_pass_rate_ci95} />
                      <span className={`w-9 shrink-0 font-mono text-[11px] ${item.current_pass_rate < item.baseline_pass_rate ? 'text-status-error' : item.current_pass_rate > item.baseline_pass_rate ? 'text-status-success' : 'text-text-tertiary'}`}>
                        {Math.round(item.current_pass_rate * 100)}%
                      </span>
                    </div>
                    <div className="mt-1 pl-11 text-[10px] text-text-tertiary">{item.baseline_trials} → {item.current_trials} 次试跑</div>
                  </td>
                  <td className="px-3 py-3">
                    <span className={`font-mono text-xs ${sig === 'significant' ? 'font-medium text-status-error' : 'text-text-tertiary'}`}>
                      {sig === 'significant' ? `p=${item.regression_p_value}` : sig === 'insufficient-samples' ? '—' : item.regression_p_value.toFixed(3)}
                    </span>
                    {sig === 'significant' && <div className="text-[10px] text-status-error">p &lt; {0.05}</div>}
                  </td>
                  <td className="px-3 py-3">
                    {item.new_failed_rules?.length ? (
                      <span className="font-mono text-[11px] text-status-error">+{item.new_failed_rules.length} 条失败规则</span>
                    ) : item.recovered_rules?.length ? (
                      <span className="font-mono text-[11px] text-status-success">-{item.recovered_rules.length} 条恢复</span>
                    ) : (
                      <span className="text-[11px] text-text-tertiary">—</span>
                    )}
                  </td>
                </tr>
                {isOpen && (
                  <tr className="bg-bg-tertiary/30">
                    <td colSpan={5} className="px-4 py-3">
                      <DiffDetail
                        item={item}
                        baseReport={tracePair.base}
                        curReport={tracePair.cur}
                        traceLoading={traceLoading}
                        traceError={traceError}
                      />
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

function DualRateBar({ baseline, current, ci }: { baseline: number; current: number; ci?: [number, number] | null }) {
  const low = ci ? Math.max(0, ci[0]) : 0
  const high = ci ? Math.min(1, ci[1]) : 0
  return (
    <div className="relative h-3 flex-1 overflow-visible rounded-full bg-bg-tertiary">
      <div className={`absolute inset-y-0 left-0 rounded-full ${current < baseline ? 'bg-status-error/60' : 'bg-status-success/70'}`} style={{ width: `${current * 100}%` }} />
      <div className="absolute inset-y-[-3px] w-0.5 bg-text-secondary" style={{ left: `calc(${baseline * 100}% - 1px)` }} title="基线通过率" />
      {ci && (
        <div className="absolute inset-y-[-3px] h-[3px] border-x border-text-tertiary" style={{ left: `${low * 100}%`, width: `${(high - low) * 100}%` }} />
      )}
    </div>
  )
}

function DiffDetail({
  item,
  baseReport,
  curReport,
  traceLoading,
  traceError,
}: {
  item: CaseComparison
  baseReport: EvalReport | null
  curReport: EvalReport | null
  traceLoading: boolean
  traceError: string
}) {
  const sig = item.significance
  return (
    <div className="space-y-2.5 text-xs">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant={sig === 'significant' ? 'error' : sig === 'insufficient-samples' ? 'warning' : 'default'}>
          {sig === 'significant' ? '统计显著' : sig === 'within-noise' ? '噪声内（不拦门禁）' : sig === 'insufficient-samples' ? '样本不足（未做 z 检验）' : sig}
        </Badge>
        <span className="text-text-tertiary">
          基线 {Math.round(item.baseline_pass_rate * 100)}% ({item.baseline_trials} 次) → 当前 {Math.round(item.current_pass_rate * 100)}% ({item.current_trials} 次)，
          变化 {item.pass_rate_delta >= 0 ? '+' : ''}{(item.pass_rate_delta * 100).toFixed(1)}pp
        </span>
      </div>
      <div className="grid gap-2 sm:grid-cols-3">
        <MiniStat label="回归 p 值" value={sig === 'insufficient-samples' ? '未计算' : String(item.regression_p_value)} hint={sig === 'significant' ? `小于 alpha 0.05，判定为显著回归` : '大于等于 alpha，或样本不足'} />
        <MiniStat label="成本变化" value={`${(item.cost_delta_cny ?? 0) >= 0 ? '+' : ''}¥${(item.cost_delta_cny ?? 0).toFixed(3)}`} hint="该用例两批的成本差" />
        <MiniStat label="耗时变化" value={`${(item.duration_delta_ms ?? 0) >= 0 ? '+' : ''}${((item.duration_delta_ms ?? 0) / 1000).toFixed(1)}s`} hint="平均单试次耗时差" />
      </div>
      {(item.new_failed_rules?.length || item.recovered_rules?.length) ? (
        <div className="rounded-lg border border-border-secondary bg-bg-secondary p-2.5">
          <div className="mb-1.5 flex items-center gap-1 text-[11px] font-medium text-text-secondary">
            逐条规则 diff
            <HelpTip text="new_failed_rules 是「基线没挂、现在挂了」的规则——即使整体通过率没变，也说明这条规则的行为退化了。recovered_rules 相反。" />
          </div>
          <div className="flex flex-wrap gap-1.5">
            {(item.new_failed_rules || []).map((r) => <span key={r} className="rounded border border-status-error/30 bg-status-error/10 px-1.5 py-0.5 font-mono text-[11px] text-status-error">pass → fail · {r}</span>)}
            {(item.recovered_rules || []).map((r) => <span key={r} className="rounded border border-status-success/30 bg-status-success/10 px-1.5 py-0.5 font-mono text-[11px] text-status-success">fail → pass · {r}</span>)}
          </div>
        </div>
      ) : null}
      {sig === 'insufficient-samples' && (
        <div className="flex items-start gap-1.5 rounded-lg border border-status-warning/20 bg-status-warning/5 px-2.5 py-2 text-[11px] text-text-secondary">
          <Info size={12} className="mt-0.5 shrink-0 text-status-warning" />
          两批试跑次数都需 ≥ {5} 才会启用显著性检验。当前退回「数值容差」规则：通过率下降就算回归。要得到可信结论，请用 --trials 10 重跑。
        </div>
      )}
      <TraceCompare
        item={item}
        baseReport={baseReport}
        curReport={curReport}
        loading={traceLoading}
        error={traceError}
      />
    </div>
  )
}

/* ---------------- 逐试次 trace 并排（P2-3） ---------------- */

/** 头尾采样截断：留前 head + 后 tail，中间省略，避免长参数撑爆布局。 */
function truncateMiddle(s: string, head = 110, tail = 40): string {
  if (s.length <= head + tail + 3) return s
  return `${s.slice(0, head)} … ${s.slice(-tail)}`
}

function trialsFor(report: EvalReport | null, caseId: string): EvalTrial[] {
  if (!report) return []
  return (report.results || [])
    .filter((t) => t.case_id === caseId)
    .sort((a, b) => a.trial_no - b.trial_no)
}

/** 绿=通过、红=失败、灰=未完成/异常；颜色走 CSS 变量，明暗主题自适应。 */
function dotColor(t: EvalTrial): string {
  if (t.status !== 'completed') return 'var(--text-tertiary)'
  return t.passed ? 'var(--status-success)' : 'var(--status-error)'
}

function TraceCompare({
  item,
  baseReport,
  curReport,
  loading,
  error,
}: {
  item: CaseComparison
  baseReport: EvalReport | null
  curReport: EvalReport | null
  loading: boolean
  error: string
}) {
  const baseTrials = useMemo(() => trialsFor(baseReport, item.case_id), [baseReport, item.case_id])
  const curTrials = useMemo(() => trialsFor(curReport, item.case_id), [curReport, item.case_id])
  const allNos = useMemo(
    () => Array.from(new Set([...baseTrials, ...curTrials].map((t) => t.trial_no))).sort((a, b) => a - b),
    [baseTrials, curTrials]
  )
  const [picked, setPicked] = useState<number | null>(null)
  // 默认定位到第一个失败试次，省掉用户自己找「哪次红了」
  const defaultNo = useMemo(() => {
    const failed = [...baseTrials, ...curTrials].find(
      (t) => t.status === 'completed' && !t.passed
    )
    return failed?.trial_no ?? allNos[0] ?? null
  }, [baseTrials, curTrials, allNos])
  const activeNo = picked != null && allNos.includes(picked) ? picked : defaultNo
  const hasFailure = (no: number) =>
    [...baseTrials, ...curTrials].some(
      (t) => t.trial_no === no && t.status === 'completed' && !t.passed
    )

  return (
    <div className="rounded-lg border border-border-secondary bg-bg-secondary p-3">
      <div className="mb-2 flex flex-wrap items-center gap-1.5 text-[11px] font-medium text-text-secondary">
        <Layers size={12} /> 逐试次 trace 并排
        <HelpTip text="点阵一个格子代表一次试跑：绿=通过、红=失败、灰=未完成或异常，按 trial_no 上下对齐。点格子可切换下方两列展示的试次，用来对比同一用例在两批里分别调了哪些工具、参数与输出有什么不同。长输出默认折叠，点开看全文。" />
        <span className="ml-auto text-[10px] font-normal text-text-tertiary">
          首次展开按需加载两批报告，之后走缓存
        </span>
      </div>

      {!baseReport || !curReport ? (
        <div className="py-4 text-center text-[11px] text-text-tertiary">
          {error
            ? `明细加载失败：${error}（收起后重新展开可重试）`
            : loading
              ? '正在加载两批完整报告…'
              : '等待报告明细'}
        </div>
      ) : (
        <>
          <div className="space-y-1.5">
            <DotsRow label="基准 ★" trials={baseTrials} activeNo={activeNo} onPick={setPicked} emptyHint="该批不含此用例（可能是新增用例）" />
            <DotsRow label="当前" trials={curTrials} activeNo={activeNo} onPick={setPicked} emptyHint="该批不含此用例（可能已移除）" />
          </div>

          {baseTrials.length !== curTrials.length && (
            <div className="mt-2 text-[10px] text-status-warning">
              两批试跑次数不同（{baseTrials.length} → {curTrials.length}），按 trial_no 对齐，缺的一侧显示占位
            </div>
          )}

          {allNos.length > 1 && (
            <div className="mt-2 flex flex-wrap items-center gap-1.5">
              <span className="text-[10px] text-text-tertiary">查看试次</span>
              {allNos.map((no) => (
                <button
                  key={no}
                  onClick={() => setPicked(no)}
                  className={`flex items-center gap-1 rounded border border-border-primary px-1.5 py-0.5 font-mono text-[10px] ${
                    activeNo === no
                      ? 'bg-accent-soft font-medium text-text-primary'
                      : 'text-text-tertiary hover:text-text-primary'
                  }`}
                >
                  #{no}
                  {hasFailure(no) && (
                    <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: 'var(--status-error)' }} />
                  )}
                </button>
              ))}
            </div>
          )}

          <div className="mt-2.5 grid gap-2 sm:grid-cols-2">
            <ToolColumn title="基准 ★" trial={baseTrials.find((t) => t.trial_no === activeNo)} trialNo={activeNo} />
            <ToolColumn title="当前" trial={curTrials.find((t) => t.trial_no === activeNo)} trialNo={activeNo} />
          </div>
        </>
      )}
    </div>
  )
}

function DotsRow({
  label,
  trials,
  activeNo,
  onPick,
  emptyHint,
}: {
  label: string
  trials: EvalTrial[]
  activeNo: number | null
  onPick: (no: number) => void
  emptyHint: string
}) {
  const passed = trials.filter((t) => t.passed).length
  return (
    <div className="flex items-center gap-2">
      <span className="w-14 shrink-0 text-[10px] text-text-tertiary">{label}</span>
      <div className="flex min-w-0 flex-wrap items-center gap-1">
        {trials.length === 0 ? (
          <span className="text-[10px] text-text-tertiary">{emptyHint}</span>
        ) : (
          trials.map((t) => (
            <button
              key={t.trial_no}
              onClick={() => onPick(t.trial_no)}
              title={`trial #${t.trial_no} · ${t.status} · ${t.passed ? '通过' : '失败'} · ${(t.duration_ms / 1000).toFixed(1)}s · ${t.tool_calls?.length || 0} 次工具调用`}
              style={{
                backgroundColor: dotColor(t),
                boxShadow: activeNo === t.trial_no ? '0 0 0 2px var(--text-secondary)' : undefined,
              }}
              className="flex h-4 w-4 items-center justify-center rounded-sm font-mono text-[9px] font-medium text-white"
            >
              {t.trial_no}
            </button>
          ))
        )}
      </div>
      {trials.length > 0 && (
        <span className="ml-auto shrink-0 text-[10px] text-text-tertiary">{passed}/{trials.length} 通过</span>
      )}
    </div>
  )
}

function ToolColumn({ title, trial, trialNo }: { title: string; trial?: EvalTrial; trialNo: number | null }) {
  return (
    <div className="min-w-0 rounded-md border border-border-secondary bg-bg-primary p-2.5">
      <div className="mb-1.5 flex items-center justify-between gap-2 text-[11px]">
        <span className="font-medium text-text-secondary">{title} · trial #{trialNo ?? '—'}</span>
        {trial && trial.status === 'completed' && (
          <span className={trial.passed ? 'text-status-success' : 'text-status-error'}>
            {trial.passed ? '通过' : '失败'}
          </span>
        )}
      </div>
      {!trial ? (
        <div className="py-3 text-center text-[10px] text-text-tertiary">该批没有这次试跑（试次不对齐）</div>
      ) : (
        <>
          <div className="mb-1.5 flex flex-wrap gap-1">
            {(trial.scores || []).map((s, i) => (
              <span
                key={`${s.rule}-${i}`}
                className={`rounded border px-1 py-0.5 font-mono text-[10px] ${
                  s.status === 'pass'
                    ? 'border-status-success/30 bg-status-success/10 text-status-success'
                    : s.status === 'skip'
                      ? 'border-border-primary text-text-tertiary'
                      : 'border-status-error/30 bg-status-error/10 text-status-error'
                }`}
              >
                {s.rule}
              </span>
            ))}
          </div>
          {!trial.tool_calls?.length ? (
            <div className="text-[10px] text-text-tertiary">该试次没有记录工具调用（可能未走到工具阶段）</div>
          ) : (
            <div className="space-y-1">
              {trial.tool_calls.map((c) => <ToolCallRow key={c.step} call={c} />)}
            </div>
          )}
          {trial.final_answer && <LongText label="最终回答" text={trial.final_answer} />}
          {trial.error && <div className="mt-1.5 text-[10px] text-status-error">{trial.error}</div>}
        </>
      )}
    </div>
  )
}

function ToolCallRow({ call }: { call: EvalToolCall }) {
  const input = call.input ? JSON.stringify(call.input) : ''
  const output = call.output || ''
  const dot = call.ok == null
    ? 'var(--text-tertiary)'
    : call.ok
      ? 'var(--status-success)'
      : 'var(--status-error)'
  return (
    <div className="rounded border border-border-secondary px-2 py-1.5 text-[10px]">
      <div className="flex items-center gap-1.5">
        <span className="h-1.5 w-1.5 shrink-0 rounded-full" style={{ backgroundColor: dot }} />
        <span className="font-mono font-medium">{call.tool}</span>
        {call.duration_ms != null && <span className="text-text-tertiary">{call.duration_ms}ms</span>}
        <span className="ml-auto text-text-tertiary">step {call.step}</span>
      </div>
      {input && (
        <div className="mt-1 truncate font-mono text-text-tertiary" title={input}>
          → {truncateMiddle(input)}
        </div>
      )}
      {output && (
        output.length > 300 ? (
          <details className="mt-1">
            <summary className="cursor-pointer font-mono text-text-tertiary">← 输出 {output.length} 字符（点击展开）</summary>
            <pre className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap font-mono text-text-secondary">{output}</pre>
          </details>
        ) : (
          <pre className="mt-1 max-h-24 overflow-auto whitespace-pre-wrap font-mono text-text-secondary">{output}</pre>
        )
      )}
    </div>
  )
}

function LongText({ label, text }: { label: string; text: string }) {
  if (text.length <= 240) {
    return (
      <div className="mt-1.5 border-l-2 border-border-primary pl-2 text-[10px] text-text-secondary">
        <span className="text-text-tertiary">{label}：</span>{text}
      </div>
    )
  }
  return (
    <details className="mt-1.5">
      <summary className="cursor-pointer text-[10px] text-text-tertiary">{label} {text.length} 字符（点击展开）</summary>
      <pre className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap text-[10px] text-text-secondary">{text}</pre>
    </details>
  )
}

function MiniStat({ label, value, hint }: { label: string; value: string; hint: string }) {
  return (
    <div className="rounded-lg border border-border-secondary bg-bg-secondary px-2.5 py-2">
      <div className="flex items-center gap-1 text-[10px] text-text-tertiary">{label}<HelpTip text={hint} /></div>
      <div className="mt-0.5 font-mono text-[13px] font-medium">{value}</div>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/* 运行弹窗与运行状态                                                   */
/* ------------------------------------------------------------------ */

type RunScope = 'all' | 'category' | 'cases'

function RunModal({
  open,
  onClose,
  onSubmit,
  error,
  catalog,
  prefill,
  batches,
}: {
  open: boolean
  onClose: () => void
  onSubmit: (payload: EvalRunPayload) => Promise<void>
  error: string
  catalog: EvalCaseCatalog | null
  prefill: { cases: string[]; trials?: number; validateOnly?: boolean } | null
  batches: EvalBatchSummary[]
}) {
  const [validateOnly, setValidateOnly] = useState(false)
  const [scope, setScope] = useState<RunScope>('all')
  const [checked, setChecked] = useState<Set<string>>(new Set())
  const [pickedCategory, setPickedCategory] = useState('')
  const [caseQuery, setCaseQuery] = useState('')
  const [categoriesText, setCategoriesText] = useState('')
  const [trials, setTrials] = useState(3)
  const [parallel, setParallel] = useState(1)
  const [judge, setJudge] = useState(false)
  const [stopOnFailure, setStopOnFailure] = useState(false)
  const [label, setLabel] = useState('')
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [submitting, setSubmitting] = useState(false)

  // 每次打开时按 prefill 重置，避免残留上一次的选择
  useEffect(() => {
    if (!open) return
    const ids = prefill?.cases || []
    setValidateOnly(prefill?.validateOnly ?? false)
    setScope(ids.length ? 'cases' : 'all')
    setChecked(new Set(ids))
    setPickedCategory('')
    setCaseQuery('')
    setCategoriesText('')
    setTrials(prefill?.trials ?? 3)
    setParallel(1)
    setJudge(false)
    setStopOnFailure(false)
    setLabel('')
    setShowAdvanced(false)
  }, [open, prefill])

  const cases = catalog?.cases || []
  const filtered = useMemo(() => {
    const q = caseQuery.trim().toLowerCase()
    return cases.filter((c) => !q || c.id.toLowerCase().includes(q) || c.topic.toLowerCase().includes(q))
  }, [cases, caseQuery])

  const selectedCount = scope === 'all' ? cases.length : scope === 'category' ? (pickedCategory ? cases.filter((c) => c.category === pickedCategory).length : 0) : checked.size
  const plannedTrials = selectedCount * Math.max(1, trials)
  const recent = batches[0]
  const unitCost = recent && recent.completed ? recent.total_cost_cny / recent.completed : 0
  const estimate = unitCost * plannedTrials

  const toggle = (id: string) => {
    setChecked((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const submit = async () => {
    setSubmitting(true)
    try {
      const payload: EvalRunPayload = {
        validate_only: validateOnly,
        cases: scope === 'cases' ? [...checked] : [],
        categories: scope === 'category' && pickedCategory ? [pickedCategory] : splitList(categoriesText),
        trials,
        parallel,
        judge,
        stop_on_failure: stopOnFailure,
        label: label.trim(),
      }
      await onSubmit(payload)
    } finally {
      setSubmitting(false)
    }
  }

  const canSubmit = !submitting && (validateOnly || selectedCount > 0)

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="运行评估"
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={submitting}>取消</Button>
          <Button variant="primary" onClick={submit} disabled={!canSubmit}>
            {submitting ? '启动中…' : validateOnly ? '校验（免费）' : '启动（将调模型 API）'}
          </Button>
        </>
      }
    >
      <div className="max-h-[68vh] space-y-3 overflow-y-auto pr-1">
        <div>
          <div className="mb-1.5 text-xs text-text-secondary">模式</div>
          <div className="flex gap-2">
            <button onClick={() => setValidateOnly(false)} className={`rounded-lg border px-3 py-1.5 text-xs ${!validateOnly ? 'border-border-primary bg-accent-soft font-medium' : 'border-border-primary text-text-secondary'}`}>正式评估</button>
            <button onClick={() => setValidateOnly(true)} className={`rounded-lg border px-3 py-1.5 text-xs ${validateOnly ? 'border-border-primary bg-accent-soft font-medium' : 'border-border-primary text-text-secondary'}`}>仅校验用例（不调模型）</button>
          </div>
        </div>

        <div>
          <div className="mb-1.5 flex items-center gap-1 text-xs text-text-secondary">
            运行范围
            <HelpTip text="三种范围互斥。后端对 --case 和 --category 是「交集」关系，同时填很容易筛出 0 个用例直接失败，所以这里不让你同时选。高级选项里仍可手动填，但要注意交集语义。" />
            <span className="ml-auto text-[11px] text-text-tertiary">共 {cases.length} 个用例</span>
          </div>
          <div className="flex gap-1.5">
            {([
              ['all', '全部用例'],
              ['category', '按类别'],
              ['cases', '指定用例'],
            ] as const).map(([key, text]) => (
              <button key={key} onClick={() => setScope(key)} className={`rounded-lg border px-2.5 py-1.5 text-xs ${scope === key ? 'border-border-primary bg-accent-soft font-medium' : 'border-border-primary text-text-secondary'}`}>{text}</button>
            ))}
          </div>
        </div>

        {scope === 'category' && (
          <div className="rounded-lg border border-border-secondary bg-bg-tertiary/30 p-2.5">
            <div className="flex flex-wrap gap-1.5">
              {(catalog?.categories || []).map((cat) => (
                <button key={cat} onClick={() => setPickedCategory(cat)} title={CATEGORY_HINTS[cat]} className={`rounded-lg border px-2.5 py-1 text-xs ${pickedCategory === cat ? 'border-border-primary bg-accent-soft font-medium' : 'border-border-primary text-text-secondary'}`}>
                  {cat} ({cases.filter((c) => c.category === cat).length})
                </button>
              ))}
            </div>
            {pickedCategory && <div className="mt-2 text-[11px] text-text-tertiary">{CATEGORY_HINTS[pickedCategory]}</div>}
          </div>
        )}

        {scope === 'cases' && (
          <div className="rounded-lg border border-border-secondary bg-bg-tertiary/30 p-2.5">
            <div className="relative mb-2">
              <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-text-tertiary" />
              <input value={caseQuery} onChange={(e) => setCaseQuery(e.target.value)} placeholder="搜索用例 ID 或主题" className="h-8 w-full rounded-lg border border-border-primary bg-bg-primary pl-7 pr-2 text-xs text-text-primary placeholder:text-text-tertiary" />
            </div>
            <div className="max-h-44 space-y-0.5 overflow-y-auto">
              {filtered.length === 0 ? (
                <div className="py-3 text-center text-[11px] text-text-tertiary">没有匹配的用例</div>
              ) : filtered.map((c) => (
                <label key={c.id} className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-xs hover:bg-bg-hover">
                  <input type="checkbox" checked={checked.has(c.id)} onChange={() => toggle(c.id)} className="h-3.5 w-3.5 cursor-pointer accent-accent-primary" />
                  <span className="font-mono">{c.id}</span>
                  <Badge variant="default">{c.category}</Badge>
                  <span className="ml-auto truncate text-[11px] text-text-tertiary">{c.topic}</span>
                </label>
              ))}
            </div>
            <div className="mt-2 border-t border-border-secondary pt-2 text-[11px] text-text-tertiary">已选 {checked.size} 个</div>
          </div>
        )}

        {!validateOnly && (
          <div className="grid grid-cols-2 gap-3">
            <label className="block">
              <span className="mb-1 flex items-center gap-1 text-xs text-text-secondary">每用例采样次数 <HelpTip text="每个用例重复跑几次。Agent 有随机性，只跑 1 次不算稳；要做显著性判定（z 检验）需要 ≥ 5 次，建议 10 次。" /></span>
              <input type="number" min={1} max={20} value={trials} onChange={(e) => setTrials(Number(e.target.value) || 1)} className="w-full rounded-lg border border-border-primary bg-bg-secondary px-3 py-1.5 text-sm" />
            </label>
            <label className="block">
              <span className="mb-1 block text-xs text-text-secondary">并发数</span>
              <input type="number" min={1} max={8} value={parallel} onChange={(e) => setParallel(Number(e.target.value) || 1)} className="w-full rounded-lg border border-border-primary bg-bg-secondary px-3 py-1.5 text-sm" />
            </label>
          </div>
        )}

        {!validateOnly && (
          <div className="rounded-lg border border-border-secondary bg-bg-tertiary/30 px-3 py-2 text-[11px] text-text-secondary">
            <div className="flex items-center gap-1.5 font-medium">
              <BarChart3 size={12} /> 本次预计
              <HelpTip text={`按「选中用例数 × 采样次数」估算试跑总数；金额按最近一批 ¥${unitCost.toFixed(3)}/试次 的均价推算，仅作参考，实际以报告 usage 为准。`} />
            </div>
            <div className="mt-1 flex flex-wrap gap-x-4 gap-y-0.5 text-text-tertiary">
              <span>{selectedCount} 个用例 × {trials} 次 = <span className="font-medium text-text-primary">{plannedTrials}</span> 个试次</span>
              {unitCost > 0 && <span>预估成本 ≈ <span className="font-medium text-text-primary">¥{estimate.toFixed(2)}</span></span>}
              {trials > 0 && trials < 5 && <span className="text-status-warning">低于 5 次，显著性门禁不会生效</span>}
            </div>
          </div>
        )}

        <button onClick={() => setShowAdvanced((v) => !v)} className="flex items-center gap-1.5 text-xs text-text-secondary hover:text-text-primary">
          <SlidersHorizontal size={12} /> 高级选项 {showAdvanced ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
        </button>
        {showAdvanced && (
          <div className="space-y-3 rounded-lg border border-border-secondary bg-bg-tertiary/30 p-3">
            <Input label="类别（逗号分隔，与用例取交集）" placeholder="core, boundary" value={categoriesText} onChange={(e) => setCategoriesText(e.target.value)} />
            {!validateOnly && (
              <div className="flex gap-5">
                <label className="flex items-center gap-2 text-xs text-text-secondary"><input type="checkbox" checked={judge} onChange={(e) => setJudge(e.target.checked)} />启用 LLM Judge（开放问答用）</label>
                <label className="flex items-center gap-2 text-xs text-text-secondary"><input type="checkbox" checked={stopOnFailure} onChange={(e) => setStopOnFailure(e.target.checked)} />失败即停（强制串行）</label>
              </div>
            )}
            <Input label="标签（可选）" placeholder="例如 prompt-v2" value={label} onChange={(e) => setLabel(e.target.value)} />
          </div>
        )}

        {error && <div className="rounded-lg border border-status-error/30 bg-status-error/10 px-3 py-2 text-xs text-status-error">{error}</div>}
      </div>
    </Modal>
  )
}

function splitList(text: string): string[] {
  return text.split(/[,，\s]+/).map((s) => s.trim()).filter(Boolean)
}

function RunPanel({ runs, onViewReport }: { runs: EvalRunStatus[]; onViewReport: (runId: string) => void }) {
  const [openLog, setOpenLog] = useState('')
  return (
    <div className="mb-5 space-y-2">
      {runs.map((run) => {
        const progress = run.total > 0 ? Math.min(100, (run.completed / run.total) * 100) : 0
        return (
          <div key={run.run_id} className="rounded-xl border border-border-primary bg-bg-secondary p-3">
            <div className="flex flex-wrap items-center gap-2 text-xs">
              <Badge variant={run.status === 'running' ? 'info' : run.status === 'completed' ? 'success' : 'error'}>
                {run.status === 'running' ? `运行中 ${run.elapsed_s}s` : run.status === 'completed' ? '已完成' : `失败（exit ${run.exit_code}）`}
              </Badge>
              <span className="font-mono text-text-tertiary">{run.run_id}</span>
              {run.label && <span>{run.label}</span>}
              {run.validate_only && <Badge variant="default">仅校验</Badge>}
              {!run.validate_only && (
                <span className="text-text-tertiary">
                  {run.cases.length ? `用例 ${run.cases.join('、')}` : '全部用例'}
                  {run.trials > 1 ? ` × ${run.trials}` : ''}{run.parallel > 1 ? ` · 并发 ${run.parallel}` : ''}{run.judge ? ' · Judge' : ''}
                </span>
              )}
              <div className="ml-auto flex items-center gap-2">
                <button onClick={() => setOpenLog((prev) => (prev === run.run_id ? '' : run.run_id))} className="text-text-secondary hover:text-text-primary">日志</button>
                {run.status === 'completed' && !run.validate_only && <Button variant="secondary" onClick={() => onViewReport(run.run_id)}>查看报告</Button>}
              </div>
            </div>
            {!run.validate_only && run.total > 0 && (
              <div className="mt-2.5 flex items-center gap-2">
                <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-bg-tertiary">
                  <div className={`h-full rounded-full transition-all ${run.status === 'failed' ? 'bg-status-error' : 'bg-status-success'}`} style={{ width: `${progress}%` }} />
                </div>
                <span className="flex w-24 shrink-0 items-center justify-end gap-1 text-[11px] text-text-tertiary"><Clock size={11} />{run.completed}/{run.total} 试次</span>
              </div>
            )}
            {openLog === run.run_id && (
              <pre className="mt-2 max-h-48 overflow-y-auto whitespace-pre-wrap rounded-lg bg-bg-tertiary p-2.5 font-mono text-[11px] text-text-secondary">{run.log_tail || '（暂无输出）'}</pre>
            )}
          </div>
        )
      })}
    </div>
  )
}

/* ------------------------------------------------------------------ */
/* 通用小组件                                                           */
/* ------------------------------------------------------------------ */

function CompareSelect({ value, onChange, placeholder, batches, label }: { value: string; onChange: (v: string) => void; placeholder: string; batches: EvalBatchSummary[]; label?: string }) {
  return (
    <label className="flex items-center gap-1.5">
      {label && <span className="text-[11px] text-text-tertiary">{label}</span>}
      <select value={value} onChange={(e) => onChange(e.target.value)} className="max-w-[210px] rounded-lg border border-border-primary bg-bg-primary px-2.5 py-1.5 text-xs text-text-primary">
        <option value="">{placeholder}</option>
        {batches.map((b) => <option key={b.batch_id} value={b.batch_id}>{`${batchDisplayName(b)}（${shortId(b.batch_id)}）`}</option>)}
      </select>
    </label>
  )
}

function shortId(batchId: string) {
  return batchId.length > 20 ? `${batchId.slice(0, 17)}…` : batchId
}

function rateVariant(rate: number): 'success' | 'warning' | 'error' {
  if (rate >= 0.8) return 'success'
  if (rate >= 0.5) return 'warning'
  return 'error'
}

function severityVariant(severity?: string): 'error' | 'warning' | 'default' {
  if (severity === 'high') return 'error'
  if (severity === 'medium') return 'warning'
  return 'default'
}

function Th({ children, className = '' }: { children?: ReactNode; className?: string }) {
  return <th className={`px-4 py-3 text-left text-xs font-medium text-text-secondary ${className}`}>{children}</th>
}
