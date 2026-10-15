import { useEffect, useState } from 'react'
import { ChevronDown, MessagesSquare } from 'lucide-react'
import { chatApi } from '../api'

export interface SessionOption {
  id: string
  title: string
  updatedAt: number
}

/** 拉取会话列表（轻量接口），供三个页面的会话下拉与标题映射共用。 */
export function useSessions(): SessionOption[] {
  const [sessions, setSessions] = useState<SessionOption[]>([])
  useEffect(() => {
    let alive = true
    chatApi
      .sessions()
      .then((res) => {
        if (!alive) return
        setSessions(
          (res.sessions || []).map((item) => ({
            id: item.id,
            title: item.title || '新对话',
            updatedAt: item.updated_at * 1000,
          }))
        )
      })
      .catch(() => {
        // 会话列表不可用时不阻塞页面，标题回退为短 ID。
      })
    return () => {
      alive = false
    }
  }, [])
  return sessions
}

/** 会话 ID → 展示标题；未知会话回退为短 ID。 */
export function sessionTitle(
  sessions: SessionOption[],
  id: string | undefined | null
): string {
  if (!id) return '-'
  const hit = sessions.find((item) => item.id === id)
  if (hit) return hit.title
  return id.length > 14 ? `${id.slice(0, 8)}…` : id
}

interface SessionSelectProps {
  value: string
  onChange: (value: string) => void
  sessions: SessionOption[]
  label?: string
  allowAll?: boolean
  allLabel?: string
  className?: string
}

export default function SessionSelect({
  value,
  onChange,
  sessions,
  label = '会话',
  allowAll = true,
  allLabel = '全部会话',
  className = 'w-64',
}: SessionSelectProps) {
  return (
    <div className={`flex flex-col gap-1.5 ${className}`}>
      <label className="text-xs font-medium text-text-secondary">
        {label}
      </label>
      <div className="relative">
        <MessagesSquare
          size={14}
          className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-text-tertiary"
        />
        <select
          value={value}
          onChange={(event) => onChange(event.target.value)}
          className="w-full cursor-pointer appearance-none rounded-lg border border-border-primary bg-bg-primary py-2 pl-9 pr-8 text-sm text-text-primary transition-colors focus:border-accent-primary"
        >
          {allowAll && <option value="">{allLabel}</option>}
          {sessions.map((session) => (
            <option key={session.id} value={session.id}>
              {session.title}
            </option>
          ))}
        </select>
        <ChevronDown
          size={14}
          className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-text-tertiary"
        />
      </div>
    </div>
  )
}
