import { useEffect, useState } from 'react'
import {
  AlertTriangle,
  CheckCircle2,
  RefreshCw,
  RotateCcw,
} from 'lucide-react'
import { recoveryApi } from '../api'
import Badge from '../components/Badge'
import Button from '../components/Button'

export default function Recovery() {
  const [runs, setRuns] = useState<any[]>([])
  const [selected, setSelected] = useState<any | null>(null)
  const [loading, setLoading] = useState(false)
  const [resumeText, setResumeText] = useState('')
  const [error, setError] = useState('')

  const load = async () => {
    setLoading(true)
    setError('')
    try {
      const result = await recoveryApi.list({ limit: 100 })
      const activeRuns = (result.runs || []).filter((run: any) =>
        ['running', 'interrupted', 'failed', 'canceled'].includes(run.status)
      )
      setRuns(activeRuns)
      if (selected) {
        const updated = activeRuns.find(
          (run: any) => run.run_id === selected.run_id
        )
        setSelected(updated || null)
      }
    } catch (e: any) {
      setError(e.message || '加载恢复记录失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  const selectRun = async (run: any) => {
    setResumeText('')
    setError('')
    try {
      setSelected(await recoveryApi.get(run.run_id))
    } catch (e: any) {
      setError(e.message || '加载 Run 详情失败')
    }
  }

  const resume = async () => {
    if (!selected) return
    setResumeText('')
    setError('')
    try {
      await recoveryApi.resumeStream(selected.run_id, (event) => {
        if (event.type === 'status' || event.type === 'thinking') {
          setResumeText(event.message || `第 ${event.turn} 轮`)
        } else if (event.type === 'text_delta') {
          setResumeText((value) => value + (event.delta || ''))
        } else if (event.type === 'done') {
          setResumeText(event.text || 'Run 已完成')
        } else if (event.type === 'error') {
          setResumeText(`Error: ${event.message}`)
        } else if (event.type === 'cancelled') {
          setResumeText(event.text || '已停止')
        }
      })
      await load()
    } catch (e: any) {
      setError(e.message || '恢复失败')
    }
  }

  return (
    <div className="h-full overflow-y-auto p-6">
      <div className="mx-auto max-w-7xl">
        <div className="mb-5 flex items-center justify-between gap-4">
          <div>
            <h1 className="text-base font-semibold">崩溃恢复中心</h1>
            <p className="mt-1 text-sm text-text-secondary">
              查看进程中断原因，只从没有工具在途的安全点继续。
            </p>
          </div>
          <Button variant="secondary" onClick={load} disabled={loading}>
            <RefreshCw size={16} className={loading ? 'animate-spin' : ''} />
            刷新
          </Button>
        </div>

        {error && (
          <div className="mb-4 rounded-lg border border-status-error/30 bg-status-error/10 px-4 py-3 text-sm text-status-error">
            {error}
          </div>
        )}

        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_420px]">
          <div className="overflow-hidden rounded-lg border border-border-primary">
            <div className="overflow-x-auto">
              <table className="w-full min-w-[720px]">
                <thead>
                  <tr className="border-b border-border-primary bg-bg-tertiary/50">
                    <Th>Run</Th>
                    <Th>状态</Th>
                    <Th>阶段</Th>
                    <Th>安全点</Th>
                    <Th>更新时间</Th>
                  </tr>
                </thead>
                <tbody>
                  {runs.map((run) => (
                    <tr
                      key={run.run_id}
                      onClick={() => selectRun(run)}
                      className={`cursor-pointer border-b border-border-secondary last:border-0 hover:bg-bg-hover/60 ${
                        selected?.run_id === run.run_id ? 'bg-accent-soft' : ''
                      }`}
                    >
                      <td className="px-4 py-3">
                        <div className="font-mono text-xs">
                          {shortId(run.run_id)}
                        </div>
                        <div className="mt-0.5 max-w-sm truncate text-[11px] text-text-tertiary">
                          {run.user_message || '-'}
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <StatusBadge status={run.status} />
                      </td>
                      <td className="px-4 py-3 text-xs text-text-secondary">
                        {run.phase}
                      </td>
                      <td className="px-4 py-3 text-xs">
                        {run.safe_to_resume ? (
                          <span className="text-status-success">可继续</span>
                        ) : (
                          <span className="text-text-tertiary">不可用</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-xs text-text-tertiary">
                        {formatTime(run.updated_at)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {!loading && runs.length === 0 && (
              <div className="flex flex-col items-center py-20 text-center">
                <CheckCircle2 size={34} className="mb-3 text-status-success" />
                <p className="text-sm text-text-secondary">
                  没有中断或失败的 Run
                </p>
              </div>
            )}
          </div>

          <div className="min-h-[420px] rounded-lg border border-border-primary bg-bg-secondary p-4">
            {!selected ? (
              <div className="flex h-full min-h-[380px] flex-col items-center justify-center text-center">
                <RotateCcw size={34} className="mb-3 text-text-tertiary" />
                <p className="text-sm text-text-secondary">
                  选择一条记录查看中断原因
                </p>
              </div>
            ) : (
              <div>
                <div className="mb-4 flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="truncate font-mono text-xs text-text-secondary">
                      {selected.run_id}
                    </div>
                    <div className="mt-2 flex items-center gap-2">
                      <StatusBadge status={selected.status} />
                      <span className="text-xs text-text-tertiary">
                        {selected.message_count} 条消息
                      </span>
                    </div>
                  </div>
                  {selected.safe_to_resume && (
                    <Button size="sm" onClick={resume}>
                      <RotateCcw size={14} />
                      从安全点继续
                    </Button>
                  )}
                </div>

                <dl className="space-y-3 text-xs">
                  <Meta label="Session" value={selected.session_id} />
                  <Meta label="初始请求" value={selected.user_message} />
                  <Meta label="中断原因" value={selected.interruption_reason || '-'} />
                  <Meta label="在途工具" value={selected.active_tool || '-'} />
                  <Meta
                    label="恢复次数"
                    value={String(selected.resume_count || 0)}
                  />
                </dl>

                {!selected.safe_to_resume && (
                  <div className="mt-4 flex gap-2 rounded-lg border border-status-warning/30 bg-status-warning/10 px-3 py-2 text-xs text-status-warning">
                    <AlertTriangle size={15} className="mt-0.5 shrink-0" />
                    <span>
                      中断发生在工具执行期间。为避免重复执行非幂等命令，不提供自动续跑。
                    </span>
                  </div>
                )}

                {resumeText && (
                  <div className="mt-4 max-h-64 overflow-y-auto rounded-lg bg-bg-tertiary p-3 text-xs leading-5 text-text-secondary">
                    {resumeText}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
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

function Meta({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-text-tertiary">{label}</dt>
      <dd className="mt-1 break-words text-text-secondary">{value || '-'}</dd>
    </div>
  )
}

function StatusBadge({ status }: { status: string }) {
  const variant = (
    status === 'completed' ? 'success'
    : status === 'running' ? 'info'
    : status === 'interrupted' ? 'warning'
    : 'error'
  ) as 'success' | 'info' | 'warning' | 'error'
  return <Badge variant={variant}>{status}</Badge>
}

function shortId(value: string) {
  return value.length > 18
    ? `${value.slice(0, 10)}...${value.slice(-5)}`
    : value
}

function formatTime(value: number) {
  return value ? new Date(value * 1000).toLocaleString() : '-'
}
