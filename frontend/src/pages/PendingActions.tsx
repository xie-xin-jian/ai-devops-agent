import { useCallback, useEffect, useState } from 'react'
import {
  Check,
  History,
  RefreshCw,
  ShieldAlert,
  X,
} from 'lucide-react'
import { actionApi } from '../api'
import Badge from '../components/Badge'
import Button from '../components/Button'
import SessionSelect, {
  sessionTitle,
  useSessions,
} from '../components/SessionSelect'
import { useAppStore } from '../store/useAppStore'

type Tab = 'pending' | 'history'

export default function PendingActions() {
  const sessions = useSessions()
  const [tab, setTab] = useState<Tab>('pending')
  const [actions, setActions] = useState<any[]>([])
  const [sessionId, setSessionId] = useState('')
  const [loading, setLoading] = useState(false)
  const [busyId, setBusyId] = useState('')
  const [error, setError] = useState('')

  const load = useCallback(async (which: Tab, sid: string) => {
    setLoading(true)
    setError('')
    try {
      if (which === 'pending') {
        // 待审批只拉 pending 状态，服务端过滤 + 限量，轮询开销可控。
        const res = await actionApi.pending(sid || undefined, 'pending', 50)
        setActions(res.actions || [])
      } else {
        // 历史按需加载：切到该 Tab 或手动刷新时才请求。
        const res = await actionApi.pending(sid || undefined, undefined, 50)
        setActions(
          (res.actions || []).filter((item: any) => item.status !== 'pending')
        )
      }
    } catch (e: any) {
      setError(e.message || '加载审批记录失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load(tab, sessionId)
    // 仅待审批 Tab 需要 10s 轮询；历史 Tab 按需加载。
    const timer = setInterval(() => {
      if (tab === 'pending') {
        load('pending', sessionId)
      }
    }, 10000)
    return () => clearInterval(timer)
  }, [load, tab, sessionId])

  const switchTab = (next: Tab) => {
    setTab(next)
  }

  const decide = async (action: any, decision: 'confirm' | 'cancel') => {
    const id = action.id
    setBusyId(id)
    setError('')
    try {
      if (decision === 'confirm') {
        const result = await actionApi.confirm(id)
        if (
          action.session_id
          && useAppStore.getState().sessionId === action.session_id
        ) {
          await useAppStore.getState().fetchMessages()
        }
        if (result?.result_payload?.continuation_error) {
          setError(`命令已执行，但 Agent 未能继续：${result.result_payload.continuation_error}`)
        }
      } else {
        await actionApi.cancel(id, 'api-user', 'Rejected from UI')
      }
      await load(tab, sessionId)
    } catch (e: any) {
      setError(e.message || '审批操作失败')
    } finally {
      setBusyId('')
    }
  }

  return (
    <div className="h-full overflow-y-auto p-6">
      <div className="mx-auto max-w-6xl">
        <div className="mb-5 flex flex-wrap items-end gap-3">
          <SessionSelect
            value={sessionId}
            onChange={(value) => {
              setSessionId(value)
              load(tab, value)
            }}
            sessions={sessions}
          />
          <div className="flex rounded-lg border border-border-primary p-0.5">
            <TabButton
              active={tab === 'pending'}
              onClick={() => switchTab('pending')}
              icon={<ShieldAlert size={14} />}
              text="待审批"
            />
            <TabButton
              active={tab === 'history'}
              onClick={() => switchTab('history')}
              icon={<History size={14} />}
              text="历史"
            />
          </div>
          <Button variant="ghost" onClick={() => load(tab, sessionId)} disabled={loading}>
            <RefreshCw size={16} className={loading ? 'animate-spin' : ''} />
          </Button>
          <div className="ml-auto text-xs text-text-tertiary">
            {actions.length} 条记录
          </div>
        </div>

        {error && (
          <div className="mb-4 rounded-lg border border-status-error/30 bg-status-error/10 px-4 py-3 text-sm text-status-error">
            {error}
          </div>
        )}

        {actions.length === 0 ? (
          <div className="rounded-xl border border-dashed border-border-primary py-20 text-center">
            <ShieldAlert size={36} className="mx-auto mb-3 text-text-tertiary" />
            <p className="text-text-secondary">
              {tab === 'pending' ? '当前没有待审批动作' : '暂无历史记录'}
            </p>
          </div>
        ) : (
          <div className="space-y-3">
            {actions.map((action) => (
              <div
                key={action.id}
                className="rounded-xl border border-border-primary bg-bg-secondary p-4"
              >
                <div className="flex items-start justify-between gap-4">
                  <div className="min-w-0 flex-1">
                    <div className="mb-2 flex flex-wrap items-center gap-2">
                      <h3 className="font-medium">{action.title}</h3>
                      <Badge variant={riskVariant(action.risk_level)}>
                        {action.risk_level || 'unknown'}
                      </Badge>
                      <Badge variant={statusVariant(action.status)}>
                        {action.status}
                      </Badge>
                      <span className="text-xs text-text-tertiary">
                        {action.action_code}
                      </span>
                    </div>
                    <p className="text-sm text-text-secondary">
                      {action.summary}
                    </p>

                    <div className="mt-3 grid gap-3 text-xs md:grid-cols-3">
                      <Detail label="会话" value={sessionTitle(sessions, action.session_id)} />
                      <Detail label="Run" value={action.run_id || '-'} />
                      <Detail label="Owner" value={action.owner_id || '-'} />
                    </div>

                    {!!action.steps?.length && (
                      <div className="mt-3">
                        <div className="mb-1.5 text-xs font-medium text-text-secondary">
                          执行步骤
                        </div>
                        <div className="space-y-1">
                          {action.steps.map((step: any, index: number) => (
                            <div
                              key={`${step.tool}-${index}`}
                              className="flex gap-2 text-xs text-text-secondary"
                            >
                              <span className="w-4 text-text-tertiary">{index + 1}.</span>
                              <span className="font-mono text-text-primary">{step.tool}</span>
                              <span>{step.description}</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {(action.impact || action.rollback_plan || action.verification) && (
                      <div className="mt-3 grid gap-2 text-xs md:grid-cols-3">
                        {action.impact && <Detail label="影响范围" value={action.impact} />}
                        {action.rollback_plan && <Detail label="回滚方案" value={action.rollback_plan} />}
                        {action.verification && <Detail label="验证方式" value={action.verification} />}
                      </div>
                    )}
                  </div>

                  {action.status === 'pending' && (
                    <div className="flex shrink-0 gap-2">
                      <Button
                        size="sm"
                        variant="secondary"
                        onClick={() => decide(action, 'cancel')}
                        disabled={busyId === action.id}
                      >
                        <X size={14} />
                        拒绝
                      </Button>
                      <Button
                        size="sm"
                        onClick={() => decide(action, 'confirm')}
                        disabled={busyId === action.id}
                      >
                        <Check size={14} />
                        批准并执行
                      </Button>
                    </div>
                  )}
                </div>

                {action.result_payload?.summary && (
                  <div className="mt-3 rounded-lg bg-bg-tertiary px-3 py-2">
                    <div className="mb-1 text-xs font-medium text-text-secondary">
                      执行结果
                    </div>
                    <pre className="max-h-52 overflow-auto whitespace-pre-wrap break-words text-xs text-text-secondary">
                      {action.result_payload.summary}
                    </pre>
                  </div>
                )}
                {action.result_payload?.error && (
                  <div className="mt-3 rounded-lg border border-status-error/30 bg-status-error/10 px-3 py-2 text-xs text-status-error">
                    {action.result_payload.error}
                  </div>
                )}
                {action.result_payload?.assistant_response && (
                  <div className="mt-3 rounded-lg border border-accent-primary/20 bg-accent-soft px-3 py-2">
                    <div className="mb-1 text-xs font-medium text-accent-primary">
                      Agent 继续处理结果
                    </div>
                    <pre className="max-h-52 overflow-auto whitespace-pre-wrap break-words text-xs text-text-secondary">
                      {action.result_payload.assistant_response}
                    </pre>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

function TabButton({
  active,
  onClick,
  icon,
  text,
}: {
  active: boolean
  onClick: () => void
  icon: React.ReactNode
  text: string
}) {
  return (
    <button
      onClick={onClick}
      className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
        active
          ? 'bg-accent-soft text-accent-primary'
          : 'text-text-tertiary hover:text-text-primary'
      }`}
    >
      {icon}
      {text}
    </button>
  )
}

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <div className="text-text-tertiary">{label}</div>
      <div className="truncate text-text-secondary" title={value}>
        {value}
      </div>
    </div>
  )
}

function riskVariant(risk: string): 'success' | 'warning' | 'error' | 'info' | 'default' {
  if (risk === 'critical') return 'error'
  if (risk === 'high') return 'error'
  if (risk === 'medium') return 'warning'
  if (risk === 'low') return 'info'
  return 'success'
}

function statusVariant(status: string): 'success' | 'warning' | 'error' | 'info' | 'default' {
  if (status === 'confirmed') return 'info'
  if (status === 'executed') return 'success'
  if (status === 'failed' || status === 'canceled') return 'error'
  if (status === 'pending') return 'warning'
  return 'default'
}
