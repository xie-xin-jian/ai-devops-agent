import { useEffect, useMemo, useState } from 'react'
import {
  Clock,
  FolderOpen,
  ListTodo,
  Puzzle,
  RefreshCw,
  Search,
  Terminal,
  Wrench,
} from 'lucide-react'
import { useAppStore } from '../store/useAppStore'
import Badge from '../components/Badge'
import Button from '../components/Button'
import {
  SectionLabel,
  WorkspaceEmpty,
  WorkspacePage,
  WorkspacePanel,
  WorkspaceToolbar,
} from '../components/Workspace'

const categoryIcons: Record<string, typeof Wrench> = {
  基础工具: Terminal,
  任务管理: ListTodo,
  技能与子Agent: Puzzle,
  Cron调度: Clock,
  MCP: Puzzle,
  上下文: RefreshCw,
  运维工具: Wrench,
  项目Target: FolderOpen,
}

function categorize(name: string): string {
  const categories: Record<string, string[]> = {
    基础工具: ['bash'],
    任务管理: ['create_task', 'list_tasks', 'get_task', 'claim_task', 'complete_task'],
    技能与子Agent: ['list_skills', 'load_skill', 'spawn_subagent'],
    Cron调度: ['schedule_cron', 'list_crons', 'cancel_cron', 'list_cron_logs'],
    上下文: ['compact'],
  }
  for (const [category, names] of Object.entries(categories)) {
    if (names.includes(name)) return category
  }
  if (name.startsWith('mcp__')) return 'MCP'
  if (name.startsWith('target_')) return '项目Target'
  return '运维工具'
}

export default function Tools() {
  const { tools, fetchTools } = useAppStore()
  const [query, setQuery] = useState('')
  const [category, setCategory] = useState('全部')

  useEffect(() => {
    fetchTools()
  }, [fetchTools])

  const groups = useMemo(() => {
    const result: Record<string, typeof tools> = {}
    for (const tool of tools) {
      const group = categorize(tool.name)
      result[group] = [...(result[group] || []), tool]
    }
    return result
  }, [tools])

  const categories = ['全部', ...Object.keys(groups)]
  const filtered = tools.filter((tool) => {
    const matchesCategory = category === '全部' || categorize(tool.name) === category
    const needle = query.trim().toLowerCase()
    return (
      matchesCategory &&
      (!needle ||
        tool.name.toLowerCase().includes(needle) ||
        tool.description.toLowerCase().includes(needle))
    )
  })

  return (
    <WorkspacePage
      title="工具库"
      description={`${tools.length} 个可用工具，按运行时能力分组。`}
      actions={
        <Button variant="secondary" onClick={fetchTools}>
          <RefreshCw size={12} />
          刷新
        </Button>
      }
      wide
    >
      <WorkspaceToolbar>
        <div className="relative w-64">
          <Search size={13} className="pointer-events-none absolute left-3 top-2.5 text-text-tertiary" />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="搜索工具名称或描述"
            className="h-8 w-full rounded-lg border border-border-primary bg-bg-primary pl-8 pr-3 text-[12px] outline-none focus:border-text-tertiary"
          />
        </div>
        <span className="ml-auto text-[10.5px] text-text-tertiary">{filtered.length} 个结果</span>
      </WorkspaceToolbar>

      <div className="grid gap-4 md:grid-cols-[180px_minmax(0,1fr)]">
        <WorkspacePanel padded>
          <SectionLabel>分类</SectionLabel>
          <div className="mt-2 space-y-0.5">
            {categories.map((item) => {
              const Icon = item === '全部' ? Wrench : categoryIcons[item] || Wrench
              const count = item === '全部' ? tools.length : groups[item]?.length || 0
              return (
                <button
                  key={item}
                  onClick={() => setCategory(item)}
                  className={`flex w-full items-center gap-2 rounded-lg px-2 py-2 text-left text-[12px] transition-colors ${
                    category === item
                      ? 'bg-bg-active text-text-primary'
                      : 'text-text-secondary hover:bg-bg-hover'
                  }`}
                >
                  <Icon size={13} className="text-text-tertiary" />
                  <span className="min-w-0 flex-1 truncate">{item}</span>
                  <span className="text-[10px] text-text-tertiary">{count}</span>
                </button>
              )
            })}
          </div>
        </WorkspacePanel>

        <WorkspacePanel>
          <div className="flex items-center justify-between border-b border-border-secondary px-4 py-3">
            <SectionLabel>{category}</SectionLabel>
          </div>
          {filtered.length === 0 ? (
            <WorkspaceEmpty icon={<Search size={17} />} title="没有匹配的工具" />
          ) : (
            filtered.map((tool) => (
              <div
                key={tool.name}
                className="border-b border-border-secondary px-4 py-3.5 last:border-0"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <code className="font-mono text-[12px] font-medium text-text-primary">{tool.name}</code>
                  <Badge>{categorize(tool.name)}</Badge>
                </div>
                <p className="mt-1.5 text-[11.5px] leading-5 text-text-secondary">
                  {tool.description || '暂无工具说明。'}
                </p>
                {!!tool.input_schema?.required?.length && (
                  <div className="mt-2 flex flex-wrap gap-1">
                    {tool.input_schema.required.map((param: string) => (
                      <span
                        key={param}
                        className="rounded border border-border-secondary bg-bg-secondary px-1.5 py-0.5 font-mono text-[10px] text-text-tertiary"
                      >
                        {param}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            ))
          )}
        </WorkspacePanel>
      </div>
    </WorkspacePage>
  )
}
