import { useEffect, useState } from 'react'
import { RefreshCw, ScrollText, Search } from 'lucide-react'
import { auditApi } from '../api'
import Badge from '../components/Badge'
import Button from '../components/Button'
import { Input } from '../components/Input'
import SessionSelect, {
  sessionTitle,
  useSessions,
} from '../components/SessionSelect'
import {
  SectionLabel,
  SplitView,
  WorkspaceEmpty,
  WorkspacePage,
  WorkspacePanel,
  WorkspaceToolbar,
} from '../components/Workspace'

export default function Audit() {
  const sessions = useSessions()
  const [events, setEvents] = useState<any[]>([])
  const [sessionId, setSessionId] = useState('')
  const [eventType, setEventType] = useState('')
  const [selectedId, setSelectedId] = useState('')
  const [loading, setLoading] = useState(false)

  const load = async () => {
    setLoading(true)
    try {
      const res = await auditApi.events({
        sessionId: sessionId || undefined,
        eventType: eventType || undefined,
        limit: 200,
      })
      const next = res.events || []
      setEvents(next)
      setSelectedId((current) =>
        next.some((event: any) => event.id === current)
          ? current
          : next[0]?.id || ''
      )
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  const selected = events.find((event) => event.id === selectedId) || events[0]

  return (
    <WorkspacePage
      title="审计"
      description="查看 Agent、工具、审批和恢复留下的结构化操作轨迹。"
      wide
    >
      <WorkspaceToolbar>
        <SessionSelect value={sessionId} onChange={setSessionId} sessions={sessions} />
        <div className="w-56">
          <Input
            label="事件类型"
            placeholder="例如 tool.completed"
            value={eventType}
            onChange={(event) => setEventType(event.target.value)}
          />
        </div>
        <Button size="sm" variant="secondary" onClick={load} disabled={loading}>
          <Search size={13} />
          查询
        </Button>
        <Button size="sm" variant="ghost" onClick={load} disabled={loading}>
          <RefreshCw size={13} className={loading ? 'animate-spin' : ''} />
        </Button>
        <span className="ml-auto text-[10.5px] text-text-tertiary">
          {events.length} 条事件
        </span>
      </WorkspaceToolbar>

      {events.length === 0 ? (
        <WorkspaceEmpty
          icon={<ScrollText size={17} />}
          title="暂无审计事件"
          description="会话中的工具调用、审批和恢复操作会记录在这里。"
        />
      ) : (
        <SplitView
          asideWidth="390px"
          aside={
            <EventDetail
              event={selected}
              sessions={sessions}
            />
          }
        >
          <WorkspacePanel>
            <div className="flex items-center justify-between border-b border-border-secondary px-4 py-3">
              <SectionLabel>事件流</SectionLabel>
              <span className="text-[10px] text-text-tertiary">最近 200 条</span>
            </div>
            <div className="max-h-[calc(100vh-250px)] overflow-auto">
              <table className="w-full">
                <thead className="sticky top-0 z-[1] bg-bg-secondary">
                  <tr className="border-b border-border-primary">
                    <Th>事件</Th>
                    <Th>结果</Th>
                    <Th>会话</Th>
                    <Th>时间</Th>
                  </tr>
                </thead>
                <tbody>
                  {events.map((event) => (
                    <tr
                      key={event.id}
                      onClick={() => setSelectedId(event.id)}
                      className={`cursor-pointer border-b border-border-secondary last:border-0 ${
                        selected?.id === event.id ? 'bg-bg-active' : 'hover:bg-bg-hover'
                      }`}
                    >
                      <td className="px-4 py-3">
                        <div className="max-w-[360px] truncate text-[12px] font-medium">
                          {event.title}
                        </div>
                        <div className="mt-0.5 truncate font-mono text-[10px] text-text-tertiary">
                          {event.event_type}
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <Badge variant={resultVariant(event.result)}>{event.result}</Badge>
                      </td>
                      <td className="max-w-40 px-4 py-3">
                        <div className="truncate text-[11px] text-text-secondary">
                          {sessionTitle(sessions, event.session_id)}
                        </div>
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-[10.5px] text-text-tertiary">
                        {new Date(event.occurred_at * 1000).toLocaleString()}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </WorkspacePanel>
        </SplitView>
      )}
    </WorkspacePage>
  )
}

function EventDetail({
  event,
  sessions,
}: {
  event: any
  sessions: ReturnType<typeof useSessions>
}) {
  if (!event) {
    return (
      <WorkspacePanel padded className="min-h-[360px]">
        <WorkspaceEmpty icon={<ScrollText size={17} />} title="选择一条审计事件" />
      </WorkspacePanel>
    )
  }

  return (
    <WorkspacePanel padded>
      <SectionLabel>事件详情</SectionLabel>
      <h2 className="mt-2 text-[15px] font-medium leading-6">{event.title}</h2>
      <div className="mt-3 flex flex-wrap gap-2">
        <Badge variant={resultVariant(event.result)}>{event.result}</Badge>
        <Badge variant={severityVariant(event.severity)}>{event.severity || 'info'}</Badge>
      </div>
      <div className="mt-5 space-y-3 border-y border-border-secondary py-4 text-[11px]">
        <Meta label="事件类型" value={event.event_type} mono />
        <Meta label="会话" value={sessionTitle(sessions, event.session_id)} />
        <Meta label="Run" value={event.run_id || '-'} mono />
        <Meta label="工具 / Action" value={event.tool_name || event.action_code || '-'} mono />
        <Meta label="Actor" value={event.actor || '-'} />
        <Meta label="时间" value={new Date(event.occurred_at * 1000).toLocaleString()} />
      </div>
      {event.summary && (
        <div className="mt-4">
          <SectionLabel>摘要</SectionLabel>
          <p className="mt-2 whitespace-pre-wrap text-[11.5px] leading-6 text-text-secondary">
            {event.summary}
          </p>
        </div>
      )}
      {event.payload && Object.keys(event.payload).length > 0 && (
        <div className="mt-4">
          <SectionLabel>Payload</SectionLabel>
          <pre className="mt-2 max-h-72 overflow-auto whitespace-pre-wrap rounded-lg bg-bg-secondary p-3 font-mono text-[10.5px] leading-5 text-text-secondary">
            {JSON.stringify(event.payload, null, 2)}
          </pre>
        </div>
      )}
    </WorkspacePanel>
  )
}

function Th({ children }: { children: React.ReactNode }) {
  return (
    <th className="px-4 py-2.5 text-left text-[10px] font-medium uppercase tracking-[0.1em] text-text-tertiary">
      {children}
    </th>
  )
}

function Meta({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <div>
      <div className="text-text-tertiary">{label}</div>
      <div className={`mt-1 break-words text-text-secondary ${mono ? 'font-mono text-[10.5px]' : ''}`}>
        {value || '-'}
      </div>
    </div>
  )
}

function resultVariant(result: string): 'success' | 'warning' | 'error' | 'info' | 'default' {
  if (result === 'success') return 'success'
  if (result === 'failed') return 'error'
  if (result === 'blocked') return 'warning'
  if (result === 'pending') return 'info'
  return 'default'
}

function severityVariant(severity: string): 'success' | 'warning' | 'error' | 'info' | 'default' {
  if (severity === 'high' || severity === 'critical') return 'error'
  if (severity === 'warning' || severity === 'medium') return 'warning'
  if (severity === 'info') return 'info'
  return 'default'
}
