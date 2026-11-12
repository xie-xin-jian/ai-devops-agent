import { useEffect, useState } from 'react'
import {
  BookOpen,
  Box,
  ChevronDown,
  Clock,
  FlaskConical,
  Folder,
  ListTodo,
  Moon,
  Pencil,
  Plug,
  RotateCcw,
  ScrollText,
  ShieldCheck,
  SquarePen,
  Sun,
  Trash2,
  Wrench,
} from 'lucide-react'
import { useAppStore, type ChatSession } from '../store/useAppStore'

const navItems = [
  { id: 'tasks' as const, label: '任务', icon: ListTodo },
  { id: 'cron' as const, label: '定时任务', icon: Clock },
  { id: 'tools' as const, label: '工具库', icon: Wrench },
  { id: 'skills' as const, label: '技能', icon: BookOpen },
  { id: 'actions' as const, label: '审批', icon: ShieldCheck },
  { id: 'audit' as const, label: '审计', icon: ScrollText },
  { id: 'recovery' as const, label: '恢复', icon: RotateCcw },
  { id: 'sandboxes' as const, label: '工作区', icon: Box },
  { id: 'eval' as const, label: '评估', icon: FlaskConical },
]

export default function Sidebar() {
  const {
    view,
    setView,
    newChat,
    chatSessions,
    sessionId,
    switchChat,
    deleteChat,
    renameChat,
    fetchChatSessions,
    targets,
    activeTargetId,
    activateTarget,
    theme,
    toggleTheme,
    health,
  } = useAppStore()
  const [renaming, setRenaming] = useState<{ id: string; value: string } | null>(null)

  useEffect(() => {
    let active = true
    const refresh = () => {
      if (!active || document.visibilityState !== 'visible') return
      void fetchChatSessions()
    }

    refresh()
    const timer = window.setInterval(refresh, 15_000)
    window.addEventListener('focus', refresh)
    document.addEventListener('visibilitychange', refresh)
    return () => {
      active = false
      window.clearInterval(timer)
      window.removeEventListener('focus', refresh)
      document.removeEventListener('visibilitychange', refresh)
    }
  }, [fetchChatSessions])

  const sessionsByTarget = new Map<string, ChatSession[]>()
  const unassigned: ChatSession[] = []
  const targetIds = new Set(targets.map((target) => target.id))
  for (const session of chatSessions) {
    // 已删除或暂时加载失败的 Target 不能把会话藏起来。
    if (session.targetId && targetIds.has(session.targetId)) {
      const list = sessionsByTarget.get(session.targetId) || []
      list.push(session)
      sessionsByTarget.set(session.targetId, list)
    } else {
      unassigned.push(session)
    }
  }

  const renderSession = (session: ChatSession) => {
    const active = session.id === sessionId && view === 'chat'
    const editing = renaming?.id === session.id
    return (
      <div key={session.id} className="group relative flex items-center">
        <button
          onClick={() => {
            switchChat(session.id)
            setView('chat')
          }}
          className={`flex w-full min-w-0 items-center rounded-md py-[6px] pl-7 pr-2 text-left text-[12.5px] transition-colors ${
            active
              ? 'bg-bg-active text-text-primary'
              : 'text-text-secondary hover:bg-bg-hover hover:text-text-primary'
          }`}
        >
          {editing && renaming ? (
            <input
              autoFocus
              value={renaming.value}
              onClick={(event) => event.stopPropagation()}
              onChange={(event) =>
                setRenaming({ id: session.id, value: event.target.value })
              }
              onBlur={() => setRenaming(null)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') {
                  renameChat(session.id, renaming.value).finally(() =>
                    setRenaming(null)
                  )
                } else if (event.key === 'Escape') {
                  setRenaming(null)
                }
              }}
              className="min-w-0 flex-1 rounded border border-border-primary bg-bg-primary px-1.5 py-0.5 text-[12.5px] text-text-primary outline-none focus:border-text-tertiary"
            />
          ) : (
            <span className="min-w-0 flex-1 truncate">{session.title}</span>
          )}
        </button>
        <div className="absolute right-1 hidden items-center gap-0.5 bg-bg-secondary pl-2 group-hover:flex">
          <button
            onClick={(event) => {
              event.stopPropagation()
              setRenaming({ id: session.id, value: session.title })
            }}
            className="flex h-5 w-5 items-center justify-center rounded text-text-tertiary hover:text-text-primary"
            title="重命名会话"
          >
            <Pencil size={11} />
          </button>
          <button
            onClick={(event) => {
              event.stopPropagation()
              deleteChat(session.id)
            }}
            className="flex h-5 w-5 items-center justify-center rounded text-text-tertiary hover:text-status-error"
            title="删除会话"
          >
            <Trash2 size={11} />
          </button>
        </div>
      </div>
    )
  }

  return (
    <aside className="flex h-full w-[260px] shrink-0 flex-col border-r border-border-secondary bg-bg-secondary">
      {/* 工作区 */}
      <div className="flex h-12 shrink-0 items-center gap-1.5 px-4">
        <span className="text-[15px] font-medium text-text-primary">devops-agent</span>
        <ChevronDown size={14} className="text-text-tertiary" />
      </div>

      <div className="shrink-0 px-2">
        <NavRow
          icon={SquarePen}
          label="新建对话"
          onClick={() => {
            newChat()
            setView('chat')
          }}
          active={false}
        />
        {navItems.map((item) => (
          <NavRow
            key={item.id}
            icon={item.icon}
            label={item.label}
            onClick={() => setView(item.id)}
            active={view === item.id}
          />
        ))}
      </div>

      {/* 运维项目（会话挂在对应项目下） */}
      <div className="mt-4 flex min-h-0 flex-1 flex-col">
        <div className="shrink-0 px-4 pb-1 text-[11px] text-text-tertiary">运维项目</div>
        <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-2">
          {targets.map((target) => {
            const active = target.id === activeTargetId
            const targetSessions = sessionsByTarget.get(target.id) || []
            return (
              <div key={target.id}>
                <button
                  onClick={() => activateTarget(target.id)}
                  className={`flex w-full items-center gap-2 rounded-md px-2 py-[7px] text-[13px] transition-colors ${
                    active
                      ? 'bg-bg-active text-text-primary'
                      : 'text-text-secondary hover:bg-bg-hover hover:text-text-primary'
                  }`}
                  title={target.root}
                >
                  <Folder size={15} className="shrink-0 text-text-tertiary" />
                  <span className="truncate">{target.name}</span>
                </button>
                {targetSessions.map(renderSession)}
              </div>
            )
          })}

          <button
            onClick={() => setView('targets')}
            className={`flex w-full items-center gap-2 rounded-md px-2 py-[7px] text-[13px] transition-colors ${
              view === 'targets'
                ? 'bg-bg-active text-text-primary'
                : 'text-text-tertiary hover:bg-bg-hover hover:text-text-primary'
            }`}
          >
            <Plug size={15} className="shrink-0" />
            <span>管理项目</span>
          </button>

          {unassigned.length > 0 && (
            <>
              <div className="px-2 pb-1 pt-3 text-[11px] text-text-tertiary">
                其他对话
              </div>
              {unassigned.map(renderSession)}
            </>
          )}
        </div>
      </div>

      {/* 底部状态 */}
      <div className="flex shrink-0 items-center gap-2 border-t border-border-secondary px-3 py-2.5">
        <div className="relative flex h-6 w-6 items-center justify-center rounded-full bg-bg-tertiary text-[11px] text-text-secondary">
          D
          <span
            className={`absolute -bottom-0.5 -right-0.5 h-2 w-2 rounded-full border-2 border-bg-secondary ${
              health.ok ? 'bg-status-success' : 'bg-status-error'
            }`}
          />
        </div>
        <div className="min-w-0 flex-1">
          <div className="truncate text-[12px] text-text-primary">devops</div>
          <div className="truncate text-[10px] text-text-tertiary">
            {health.ok ? '服务正常' : '未连接'}
          </div>
        </div>
        <button
          onClick={toggleTheme}
          className="flex h-7 w-7 items-center justify-center rounded-md text-text-tertiary transition-colors hover:bg-bg-tertiary hover:text-text-primary"
          title={theme === 'dark' ? '切换亮色' : '切换暗色'}
        >
          {theme === 'dark' ? <Sun size={14} /> : <Moon size={14} />}
        </button>
      </div>
    </aside>
  )
}

function NavRow({
  icon: Icon,
  label,
  onClick,
  active,
}: {
  icon: typeof SquarePen
  label: string
  onClick: () => void
  active: boolean
}) {
  return (
    <button
      onClick={onClick}
      className={`flex w-full items-center gap-2 rounded-md px-2 py-[7px] text-[13px] transition-colors ${
        active
          ? 'bg-bg-active text-text-primary'
          : 'text-text-secondary hover:bg-bg-hover hover:text-text-primary'
      }`}
    >
      <Icon size={15} className="shrink-0" />
      <span>{label}</span>
    </button>
  )
}
