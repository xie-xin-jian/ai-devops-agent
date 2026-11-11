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
import {
  InlineNotice,
  SectionLabel,
  SplitView,
  WorkspaceEmpty,
  WorkspacePage,
  WorkspacePanel,
  WorkspaceToolbar,
} from '../components/Workspace'
import { useAppStore } from '../store/useAppStore'

type Tab = 'pending' | 'history'

export default function PendingActions() {
  const sessions = useSessions()
  const [tab, setTab] = useState<Tab>('pending')
  const [actions, setActions] = useState<any[]>([])
  const [sessionId, setSessionId] = useState('')
  const [selectedId, setSelectedId] = useState('')
  const [loading, setLoading] = useState(false)
  const [busyId, setBusyId] = useState('')
  const [error, setError] = useState('')

  const load = useCallback(async (which: Tab, sid: string) => {
    setLoading(true)
    setError('')
    try {
      const res = await actionApi.pending(
        sid || undefined,
        which === 'pending' ? 'pending' : undefined,
        50
      )
      const next = which === 'pending'
        ? res.actions || []
        : (res.actions || []).filter((item: any) => item.status !== 'pending')
      setActions(next)
      setSelectedId((current) =>
        next.some((item: any) => item.id === current)
          ? current
          : next[0]?.id || ''
      )
    } catch (e: any) {
      setError(e.message || '加载审批记录失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load(tab, sessionId)
    const timer = setInterval(() => {
      if (tab === 'pending') load('pending', sessionId)
    }, 10_000)
    return () => clearInterval(timer)
  }, [load, tab, sessionId])

  const decide = async (action: any, decision: 'confirm' | 'cancel') => {
    setBusyId(action.id)
    setError('')
    try {
      if (decision === 'confirm') {
        const result = await actionApi.confirm(action.id)
        if (
          action.session_id &&
          useAppStore.getState().sessionId === action.session_id
        ) {
          await useAppStore.getState().fetchMessages()
        }
        if (result?.result_payload?.continuation_error) {
          setError(`命令已执行，但 Agent 未能继续：${result.result_payload.continuation_error}`)
        }
      } else {
        await actionApi.cancel(action.id, 'api-user', 'Rejected from UI')
      }
      await load(tab, sessionId)
    } catch (e: any) {
      setError(e.message || '审批操作失败')
    } finally {
      setBusyId('')
    }
  }

  const selected = actions.find((action) => action.id === selectedId) || actions[0]

  return (
    <WorkspacePage
      title="审批"
      description="所有高风险动作都先进入这里，再决定批准、拒绝或稍后处理。"
      wide
    >
      <WorkspaceToolbar>
        <SessionSelect
          value={sessionId}
          onChange={(value) => {
            setSessionId(value)
            load(tab, value)
          }}
          sessions={sessions}
        />
        <div className="flex h-8 items-center rounded-lg border border-border-primary bg-bg-primary p-0.5">
          <TabButton
            active={tab === 'pending'}
            onClick={() => setTab('pending')}
            icon={<ShieldAlert size={12} />}
            text="待审批"
          />
          <TabButton
            active={tab === 'history'}
            onClick={() => setTab('history')}
            icon={<History size={12} />}
            text="历史"
          />
        </div>
        <Button
          size="sm"
          variant="ghost"
          onClick={() => load(tab, sessionId)}
          disabled={loading}
        >
          <RefreshCw size={13} className={loading ? 'animate-spin' : ''} />
        </Button>
        <span className="ml-auto text-[10.5px] text-text-tertiary">
          {actions.length} 条记录
        </span>
      </WorkspaceToolbar>

      {error && <InlineNotice tone="error">{error}</InlineNotice>}

      <div className="mt-4">
        {actions.length === 0 ? (
          <WorkspaceEmpty
            icon={<ShieldAlert size={17} />}
            title={tab === 'pending' ? '当前没有待审批动作' : '暂无历史记录'}
            description="Agent 请求执行高风险工具时会在这里创建审批项。"
          />
        ) : (
          <SplitView
            asideWidth="440px"
            aside={
              <ApprovalDetail
                action={selected}
                sessions={sessions}
                busy={busyId === selected?.id}
                onConfirm={() => selected && decide(selected, 'confirm')}
                onCancel={() => selected && decide(selected, 'cancel')}
              />
            }
          >
            <WorkspacePanel>
              <div className="flex items-center justify-between border-b border-border-secondary px-4 py-3">
                <SectionLabel>{tab === 'pending' ? '等待决定' : '处理历史'}</SectionLabel>
              </div>
              {actions.map((action) => (
                <button
                  key={action.id}
                  onClick={() => setSelectedId(action.id)}
                  className={`w-full border-b border-border-secondary px-4 py-3 text-left transition-colors last:border-0 ${
                    selected?.id === action.id ? 'bg-bg-active' : 'hover:bg-bg-hover'
                  }`}
                >
                  <div className="flex items-center gap-2">
                    <span className="min-w-0 flex-1 truncate text-[13px] font-medium text-text-primary">
                      {action.title}
                    </span>
                    <Badge variant={riskVariant(action.risk_level)}>
                      {action.risk_level || 'unknown'}
                    </Badge>
                  </div>
                  <div className="mt-1 flex items-center gap-2 text-[10.5px] text-text-tertiary">
                    <span>{action.status}</span>
                    <span>·</span>
                    <span className="truncate">{action.action_code}</span>
                  </div>
                </button>
              ))}
            </WorkspacePanel>
          </SplitView>
        )}
      </div>
    </WorkspacePage>
  )
}

function ApprovalDetail({
  action,
  sessions,
  busy,
  onConfirm,
  onCancel,
}: {
  action: any
  sessions: ReturnType<typeof useSessions>
  busy: boolean
  onConfirm: () => void
  onCancel: () => void
}) {
  if (!action) {
    return (
      <WorkspacePanel padded className="min-h-[420px]">
        <WorkspaceEmpty icon={<ShieldAlert size={17} />} title="选择一条审批记录" />
      </WorkspacePanel>
    )
  }

  return (
    <WorkspacePanel padded>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <SectionLabel>审批详情</SectionLabel>
          <h2 className="mt-2 text-[16px] font-medium leading-6 tracking-[-0.015em]">
            {action.title}
          </h2>
        </div>
        {action.status === 'pending' && (
          <div className="flex shrink-0 gap-1">
            <Button size="sm" variant="secondary" onClick={onCancel} disabled={busy}>
              <X size={12} />
              拒绝
            </Button>
            <Button size="sm" onClick={onConfirm} disabled={busy}>
              <Check size={12} />
              {busy ? '执行中…' : '批准'}
            </Button>
          </div>
        )}
      </div>

      <div className="mt-4 flex flex-wrap gap-2">
        <Badge variant={riskVariant(action.risk_level)}>{action.risk_level || 'unknown'}</Badge>
        <Badge variant={statusVariant(action.status)}>{action.status}</Badge>
        <span className="font-mono text-[10.5px] leading-5 text-text-tertiary">{action.action_code}</span>
      </div>

      <p className="mt-4 whitespace-pre-wrap text-[12px] leading-6 text-text-secondary">
        {action.summary || '未提供摘要。'}
      </p>

      <div className="mt-5 grid grid-cols-2 gap-3 border-y border-border-secondary py-4 text-[11px]">
        <Meta label="会话" value={sessionTitle(sessions, action.session_id)} />
        <Meta label="Owner" value={action.owner_id || '-'} />
        <Meta label="Run" value={action.run_id || '-'} mono />
        <Meta label="创建时间" value={formatTime(action.created_at)} />
      </div>

      {!!action.steps?.length && (
        <div className="mt-5">
          <SectionLabel>执行步骤</SectionLabel>
          <div className="mt-2 space-y-1.5">
            {action.steps.map((step: any, index: number) => (
              <div key={`${step.tool}-${index}`} className="rounded-lg bg-bg-secondary px-3 py-2 text-[11.5px]">
                <div className="flex items-center gap-2">
                  <span className="text-text-tertiary">{index + 1}.</span>
                  <span className="font-mono text-text-primary">{step.tool}</span>
                </div>
                <div className="mt-1 pl-5 text-text-tertiary">{step.description}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {(action.impact || action.rollback_plan || action.verification) && (
        <div className="mt-5 grid gap-3 text-[11px]">
          {action.impact && <Meta label="影响范围" value={action.impact} />}
          {action.rollback_plan && <Meta label="回滚方案" value={action.rollback_plan} />}
          {action.verification && <Meta label="验证方式" value={action.verification} />}
        </div>
      )}

      {action.result_payload?.summary && (
        <div className="mt-5">
          <SectionLabel>执行结果</SectionLabel>
          <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap rounded-lg bg-bg-secondary p-3 text-[11px] leading-5 text-text-secondary">
            {action.result_payload.summary}
          </pre>
        </div>
      )}
      {action.result_payload?.error && (
        <div className="mt-4">
          <InlineNotice tone="error">{action.result_payload.error}</InlineNotice>
        </div>
      )}
      {action.result_payload?.assistant_response && (
        <div className="mt-4">
          <SectionLabel>Agent 继续处理</SectionLabel>
          <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap rounded-lg bg-bg-secondary p-3 text-[11px] leading-5 text-text-secondary">
            {action.result_payload.assistant_response}
          </pre>
        </div>
      )}
    </WorkspacePanel>
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
      className={`flex h-7 items-center gap-1 rounded-md px-2.5 text-[11px] transition-colors ${
        active ? 'bg-bg-active text-text-primary' : 'text-text-tertiary hover:text-text-primary'
      }`}
    >
      {icon}
      {text}
    </button>
  )
}

function Meta({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="min-w-0">
      <div className="text-text-tertiary">{label}</div>
      <div className={`mt-1 break-words text-text-secondary ${mono ? 'font-mono text-[10.5px]' : ''}`}>
        {value || '-'}
      </div>
    </div>
  )
}

function formatTime(value: number) {
  return value ? new Date(value * 1000).toLocaleString() : '-'
}

function riskVariant(risk: string): 'success' | 'warning' | 'error' | 'info' | 'default' {
  if (risk === 'critical' || risk === 'high') return 'error'
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
