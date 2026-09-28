import { useEffect, useState } from 'react'
import { RefreshCw, ScrollText, Search } from 'lucide-react'
import { auditApi } from '../api'
import Badge from '../components/Badge'
import Button from '../components/Button'
import { Input } from '../components/Input'

export default function Audit() {
  const [events, setEvents] = useState<any[]>([])
  const [sessionId, setSessionId] = useState('')
  const [eventType, setEventType] = useState('')
  const [loading, setLoading] = useState(false)

  const load = async () => {
    setLoading(true)
    try {
      const res = await auditApi.events({
        sessionId: sessionId || undefined,
        eventType: eventType || undefined,
        limit: 500,
      })
      setEvents(res.events || [])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  return (
    <div className="h-full overflow-y-auto p-6">
      <div className="mx-auto max-w-6xl">
        <div className="mb-5 flex flex-wrap items-end gap-3">
          <div className="w-64">
            <Input
              label="Session ID"
              placeholder="按会话过滤"
              value={sessionId}
              onChange={(event) => setSessionId(event.target.value)}
            />
          </div>
          <div className="w-56">
            <Input
              label="事件类型"
              placeholder="例如 tool.completed"
              value={eventType}
              onChange={(event) => setEventType(event.target.value)}
            />
          </div>
          <Button variant="secondary" onClick={load} disabled={loading}>
            <Search size={16} />
            查询
          </Button>
          <Button variant="ghost" onClick={load} disabled={loading}>
            <RefreshCw size={16} className={loading ? 'animate-spin' : ''} />
          </Button>
          <div className="ml-auto text-xs text-text-tertiary">
            {events.length} 条事件
          </div>
        </div>

        {events.length === 0 ? (
          <div className="rounded-xl border border-dashed border-border-primary py-20 text-center">
            <ScrollText size={36} className="mx-auto mb-3 text-text-tertiary" />
            <p className="text-sm text-text-secondary">暂无审计事件</p>
          </div>
        ) : (
          <div className="overflow-hidden rounded-xl border border-border-primary">
            <table className="w-full">
              <thead>
                <tr className="border-b border-border-primary bg-bg-tertiary/50">
                  <Th>事件</Th>
                  <Th>结果</Th>
                  <Th>Run / Session</Th>
                  <Th>工具 / Action</Th>
                  <Th>时间</Th>
                </tr>
              </thead>
              <tbody>
                {events.map((event) => (
                  <tr key={event.id} className="border-b border-border-secondary last:border-0 hover:bg-bg-hover/50">
                    <td className="px-4 py-3">
                      <div className="text-sm font-medium">{event.title}</div>
                      <div className="mt-0.5 font-mono text-[11px] text-text-tertiary">
                        {event.event_type}
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <Badge variant={resultVariant(event.result)}>
                        {event.result}
                      </Badge>
                    </td>
                    <td className="px-4 py-3">
                      <div className="max-w-52 truncate font-mono text-[11px] text-text-secondary">
                        {event.run_id || '-'}
                      </div>
                      <div className="max-w-52 truncate font-mono text-[10px] text-text-tertiary">
                        {event.session_id || '-'}
                      </div>
                    </td>
                    <td className="px-4 py-3 text-xs text-text-secondary">
                      {event.tool_name || event.action_code || '-'}
                    </td>
                    <td className="px-4 py-3 text-xs text-text-tertiary">
                      {new Date(event.occurred_at * 1000).toLocaleString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
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

function resultVariant(result: string): 'success' | 'warning' | 'error' | 'info' | 'default' {
  if (result === 'success') return 'success'
  if (result === 'failed') return 'error'
  if (result === 'blocked') return 'warning'
  if (result === 'pending') return 'info'
  return 'default'
}
