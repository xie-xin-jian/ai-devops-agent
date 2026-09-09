import { MessageSquare, ListTodo, Clock, Wrench, Plug, BookOpen } from 'lucide-react'
import { useAppStore } from '../store/useAppStore'

const navItems = [
  { id: 'chat' as const, label: '对话', icon: MessageSquare },
  { id: 'tasks' as const, label: '任务', icon: ListTodo },
  { id: 'cron' as const, label: '定时', icon: Clock },
  { id: 'tools' as const, label: '工具', icon: Wrench },
  { id: 'mcp' as const, label: 'MCP', icon: Plug },
  { id: 'skills' as const, label: '技能', icon: BookOpen },
]

export default function Sidebar() {
  const { view, setView } = useAppStore()

  return (
    <aside className="flex h-full w-56 flex-col border-r border-border-secondary bg-bg-secondary">
      {/* Logo */}
      <div className="flex h-14 items-center gap-2.5 px-4 border-b border-border-secondary">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-accent-primary to-purple-500 text-white">
          <Wrench size={16} />
        </div>
        <div>
          <div className="text-sm font-semibold">DevOps Agent</div>
          <div className="text-[11px] text-text-tertiary">AI 运维助手</div>
        </div>
      </div>

      {/* 导航 */}
      <nav className="flex-1 py-2 px-2">
        <div className="mb-1 px-2 text-[11px] font-medium text-text-tertiary uppercase tracking-wider">
          主菜单
        </div>
        {navItems.map((item) => {
          const Icon = item.icon
          const active = view === item.id
          return (
            <button
              key={item.id}
              onClick={() => setView(item.id)}
              className={`mb-0.5 flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm transition-all ${
                active
                  ? 'bg-accent-soft text-accent-primary font-medium'
                  : 'text-text-secondary hover:bg-bg-hover hover:text-text-primary'
              }`}
            >
              <Icon size={18} className={active ? 'text-accent-primary' : ''} />
              <span>{item.label}</span>
            </button>
          )
        })}
      </nav>

      {/* 底部状态 */}
      <div className="border-t border-border-secondary p-3">
        <HealthBadge />
      </div>
    </aside>
  )
}

function HealthBadge() {
  const { health } = useAppStore()
  return (
    <div className="flex items-center gap-2 rounded-lg bg-bg-tertiary px-3 py-2">
      <div
        className={`h-2 w-2 rounded-full ${
          health.ok ? 'bg-status-success' : 'bg-status-error'
        }`}
      />
      <span className="text-xs text-text-secondary">
        {health.ok ? '服务正常' : '未连接'}
      </span>
    </div>
  )
}
