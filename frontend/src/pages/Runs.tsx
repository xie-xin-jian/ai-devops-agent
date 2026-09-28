import { useEffect, useState } from 'react'
import {
  GitBranch,
  Play,
  RefreshCw,
  RotateCcw,
} from 'lucide-react'
import { auditApi, runApi } from '../api'
import Badge from '../components/Badge'
import Button from '../components/Button'

export default function Runs() {
  const [runs, setRuns] = useState<any[]>([])
  const [selected, setSelected] = useState<any | null>(null)
  const [events, setEvents] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  const [resumeText, setResumeText] = useState('')

  const load = async () => {
    setLoading(true)
    try {
      const res = await runApi.list()
      setRuns(res.runs || [])
      if (selected) {
        const updated = (res.runs || []).find((run: any) => run.run_id === selected.run_id)
        if (updated) setSelected(updated)
      }
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  const selectRun = async (run: any) => {
    setSelected(run)
    setResumeText('')
    try {
      const trace = await auditApi.run(run.run_id)
      setEvents(trace.events || [])
    } catch {
      setEvents([])
    }
  }

  const resume = async () => {
    if (!selected) return
    setResumeText('')
    try {
      await runApi.resumeStream(selected.run_id, (event) => {
        if (event.type === 'text_delta') {
          setResumeText((value) => value + (event.delta || ''))
        } else if (event.type === 'done') {
          setResumeText(event.text || 'Run 已完成')
        } else if (event.type === 'error') {
          setResumeText(`Error: ${event.message}`)
        }
      })
      await load()
      await selectRun(selected)
    } catch (e: any) {
      setResumeText(e.message || '恢复失败')
    }
  }

  const resumable = selected && ['running', 'interrupted', 'failed'].includes(selected.status)

  return (
    <div className="h-full overflow-y-auto p-6">
      <div className="mx-auto max-w-7xl">
        <div className="mb-5 flex items-center justify-between">
          <p className="text-sm text-text-secondary">
            Run、Checkpoint 与恢复状态
          </p>
          <Button variant="secondary" onClick={load} disabled={loading}>
            <RefreshCw size={16} className={loading ? 'animate-spin' : ''} />
            刷新
          </Button>
        </div>

        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_420px]">
          <div className="overflow-hidden rounded-xl border border-border-primary">
            <table className="w-full">
              <thead>
                <tr className="border-b border-border-primary bg-bg-tertiary/50">
                  <Th>Run</Th>
                  <Th>来源</Th>
                  <Th>状态</Th>
                  <Th>轮次</Th>
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
                      <div className="font-mono text-xs">{shortId(run.run_id)}</div>
                      <div className="mt-0.5 truncate text-[11px] text-text-tertiary">
                        {run.resource_id || run.session_id || '-'}
                      </div>
                    </td>
                    <td className="px-4 py-3 text-xs text-text-secondary">
                      {run.source}
                    </td>
                    <td className="px-4 py-3">
                      <RunStatus status={run.status} />
                    </td>
                    <td className="px-4 py-3 text-xs text-text-secondary">
                      {run.turn}
                    </td>
                    <td className="px-4 py-3 text-xs text-text-tertiary">
                      {formatTime(run.updated_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {runs.length === 0 && (
              <EmptyState />
            )}
          </div>

          <div className="min-h-[420px] rounded-xl border border-border-primary bg-bg-secondary p-4">
            {!selected ? (
              <div className="flex h-full min-h-[380px] flex-col items-center justify-center text-center">
                <GitBranch size={34} className="mb-3 text-text-tertiary" />
                <p className="text-sm text-text-secondary">选择 Run 查看轨迹</p>
              </div>
            ) : (
              <div>
                <div className="mb-4 flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="truncate font-mono text-xs text-text-secondary">
                      {selected.run_id}
                    </div>
                    <div className="mt-1 flex items-center gap-2">
                      <RunStatus status={selected.status} />
                      <span className="text-xs text-text-tertiary">
                        {selected.phase}
                      </span>
                    </div>
                  </div>
                  {resumable && (
                    <Button size="sm" onClick={resume}>
                      <RotateCcw size={14} />
                      恢复
                    </Button>
                  )}
                </div>

                <div className="mb-4 grid grid-cols-2 gap-3 text-xs">
                  <Meta label="来源" value={selected.source} />
                  <Meta label="父 Run" value={selected.parent_run_id || '-'} />
                  <Meta label="资源" value={selected.resource_id || '-'} />
                  <Meta label="Action" value={selected.action_code || '-'} />
                </div>

                {resumeText && (
                  <div className="mb-4 max-h-36 overflow-y-auto rounded-lg bg-bg-tertiary p-3 text-xs text-text-secondary">
                    {resumeText}
                  </div>
                )}

                <div className="mb-2 text-xs font-medium text-text-secondary">
                  审计事件
                </div>
                <div className="max-h-72 space-y-2 overflow-y-auto">
                  {events.length === 0 ? (
                    <p className="py-8 text-center text-xs text-text-tertiary">
                      暂无事件
                    </p>
                  ) : (
                    events.map((event) => (
                      <div key={event.id} className="rounded-lg bg-bg-tertiary px-3 py-2">
                        <div className="flex items-center justify-between gap-2">
                          <span className="truncate text-xs font-medium">
                            {event.title}
                          </span>
                          <Badge variant={event.result === 'failed' || event.result === 'blocked' ? 'error' : 'default'}>
                            {event.result}
                          </Badge>
                        </div>
                        <div className="mt-1 text-[11px] text-text-tertiary">
                          {formatTime(event.occurred_at)}
                        </div>
                      </div>
                    ))
                  )}
                </div>
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
    <div className="min-w-0">
      <div className="text-text-tertiary">{label}</div>
      <div className="truncate text-text-secondary" title={value}>{value}</div>
    </div>
  )
}

function EmptyState() {
  return (
    <div className="py-20 text-center">
      <Play size={34} className="mx-auto mb-3 text-text-tertiary" />
      <p className="text-sm text-text-secondary">暂无 Run 记录</p>
    </div>
  )
}

function RunStatus({ status }: { status: string }) {
  const variant = (
    status === 'completed' ? 'success'
    : status === 'failed' || status === 'canceled' ? 'error'
    : status === 'waiting_approval' ? 'warning'
    : 'info'
  ) as 'success' | 'error' | 'warning' | 'info'
  return <Badge variant={variant}>{status}</Badge>
}

function shortId(value: string) {
  return value.length > 18 ? `${value.slice(0, 10)}...${value.slice(-5)}` : value
}

function formatTime(value: number) {
  if (!value) return '-'
  return new Date(value * 1000).toLocaleString()
}
