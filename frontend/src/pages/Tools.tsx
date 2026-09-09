import { useEffect, useState } from 'react'
import { Wrench, Terminal, FileText, ListTodo, Clock, Puzzle, RefreshCw, ChevronDown, ChevronUp } from 'lucide-react'
import { useAppStore } from '../store/useAppStore'
import Badge from '../components/Badge'

const categoryIcons: Record<string, any> = {
  '基础工具': Terminal,
  '任务管理': ListTodo,
  '技能/子Agent': Puzzle,
  'Cron 调度': Clock,
  'MCP': Puzzle,
  '上下文': RefreshCw,
  '运维工具': Wrench,
}

function categorize(name: string): string {
  const cats: Record<string, string[]> = {
    '基础工具': ['bash', 'read_file', 'write_file', 'edit_file', 'glob'],
    '任务管理': ['todo_write', 'create_task', 'list_tasks', 'get_task', 'claim_task', 'complete_task'],
    '技能/子Agent': ['list_skills', 'load_skill', 'spawn_subagent'],
    'Cron 调度': ['schedule_cron', 'list_crons', 'cancel_cron'],
    'MCP': ['connect_mcp'],
    '上下文': ['compact'],
  }
  for (const [cat, tools] of Object.entries(cats)) {
    if (tools.includes(name)) return cat
  }
  if (name.startsWith('mcp__')) return 'MCP'
  if (['service_status', 'disk_usage', 'docker_ps'].includes(name)) return '运维工具'
  return '其他'
}

export default function Tools() {
  const { tools, fetchTools } = useAppStore()
  const [expanded, setExpanded] = useState<Record<string, boolean>>({})

  useEffect(() => {
    fetchTools()
  }, [fetchTools])

  // 按类别分组
  const groups: Record<string, typeof tools> = {}
  for (const t of tools) {
    const cat = categorize(t.name)
    if (!groups[cat]) groups[cat] = []
    groups[cat].push(t)
  }

  const toggle = (cat: string) => {
    setExpanded((prev) => ({ ...prev, [cat]: !prev[cat] }))
  }

  return (
    <div className="h-full overflow-y-auto p-6">
      <div className="mx-auto max-w-5xl">
        {/* 头部 */}
        <div className="mb-6 flex items-center justify-between">
          <div>
            <p className="text-sm text-text-secondary">
              共 {tools.length} 个可用工具 · {Object.keys(groups).length} 个分类
            </p>
          </div>
          <button
            onClick={fetchTools}
            className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs text-text-secondary hover:bg-bg-hover hover:text-text-primary transition-colors"
          >
            <RefreshCw size={14} />
            刷新
          </button>
        </div>

        {/* 工具分类 */}
        <div className="space-y-3">
          {Object.entries(groups).map(([cat, toolList]) => {
            const isOpen = expanded[cat] !== false
            const Icon = categoryIcons[cat] || Wrench
            return (
              <div
                key={cat}
                className="overflow-hidden rounded-xl border border-border-primary bg-bg-secondary"
              >
                <button
                  onClick={() => toggle(cat)}
                  className="flex w-full items-center justify-between px-4 py-3 hover:bg-bg-hover/50 transition-colors"
                >
                  <div className="flex items-center gap-2.5">
                    <Icon size={18} className="text-accent-primary" />
                    <span className="font-medium text-sm">{cat}</span>
                    <Badge variant="default">{toolList.length}</Badge>
                  </div>
                  {isOpen ? (
                    <ChevronUp size={16} className="text-text-tertiary" />
                  ) : (
                    <ChevronDown size={16} className="text-text-tertiary" />
                  )}
                </button>
                {isOpen && (
                  <div className="border-t border-border-secondary p-3 grid gap-2 sm:grid-cols-2">
                    {toolList.map((t) => (
                      <div
                        key={t.name}
                        className="rounded-lg border border-border-primary bg-bg-primary p-3 hover:border-accent-primary/30 transition-colors"
                      >
                        <div className="flex items-center gap-2 mb-1.5">
                          <div className="flex h-7 w-7 items-center justify-center rounded-md bg-accent-soft text-accent-primary">
                            <Wrench size={14} />
                          </div>
                          <code className="text-sm font-mono font-medium">{t.name}</code>
                        </div>
                        <p className="text-xs text-text-secondary line-clamp-2 mb-2 pl-9">
                          {t.description}
                        </p>
                        {t.input_schema?.required && t.input_schema.required.length > 0 && (
                          <div className="flex flex-wrap gap-1 pl-9">
                            {t.input_schema.required.map((p: string) => (
                              <span
                                key={p}
                                className="rounded bg-bg-tertiary px-1.5 py-0.5 text-[10px] font-mono text-text-tertiary"
                              >
                                {p}
                              </span>
                            ))}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
