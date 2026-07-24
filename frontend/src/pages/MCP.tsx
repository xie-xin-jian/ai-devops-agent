import { useEffect, useState } from 'react'
import { Plug, Zap, RefreshCw, Link, Unlink, Plus, Server, X } from 'lucide-react'
import { useAppStore } from '../store/useAppStore'
import Button from '../components/Button'
import Badge from '../components/Badge'

export default function MCP() {
  const { mcpServers, fetchMcpServers, connectMcp, disconnectMcp, connectStdioMcp, disconnectStdioMcp } = useAppStore()
  const [showForm, setShowForm] = useState(false)
  const [form, setForm] = useState({
    name: '',
    command: 'python',
    args: '',
    cwd: '',
  })
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    fetchMcpServers()
  }, [fetchMcpServers])

  const handleDisconnect = (s: { name: string; type?: string }) => {
    if (s.type === 'stdio') {
      disconnectStdioMcp(s.name)
    } else {
      disconnectMcp(s.name)
    }
  }

  const handleSubmit = async () => {
    if (!form.name.trim() || !form.command.trim()) return
    setSubmitting(true)
    try {
      await connectStdioMcp({
        name: form.name.trim(),
        command: form.command.trim(),
        args: form.args.trim() ? form.args.split(/\s+/) : [],
        cwd: form.cwd.trim() || undefined,
      })
      setShowForm(false)
      setForm({ name: '', command: 'python', args: '', cwd: '' })
    } finally {
      setSubmitting(false)
    }
  }

  const typeLabel = (type?: string) => {
    switch (type) {
      case 'stdio': return '标准 MCP'
      case 'custom': return '自定义'
      case 'builtin': return 'Mock'
      default: return ''
    }
  }

  const typeBadgeVariant = (type?: string): 'default' | 'success' | 'info' => {
    switch (type) {
      case 'stdio': return 'info'
      case 'custom': return 'success'
      default: return 'default'
    }
  }

  return (
    <div className="h-full overflow-y-auto p-6">
      <div className="mx-auto max-w-5xl">
        {/* 头部 */}
        <div className="mb-6 flex items-center justify-between">
          <div>
            <p className="text-sm text-text-secondary">
              Model Context Protocol · 动态扩展工具能力
            </p>
          </div>
          <div className="flex gap-2">
            <Button variant="secondary" onClick={() => setShowForm(!showForm)}>
              <Plus size={14} />
              连接标准 MCP
            </Button>
            <Button variant="secondary" onClick={fetchMcpServers}>
              <RefreshCw size={14} />
              刷新
            </Button>
          </div>
        </div>

        {/* 连接标准 MCP 服务器表单 */}
        {showForm && (
          <div className="mb-6 rounded-xl border border-border-primary bg-bg-secondary p-5">
            <div className="mb-4 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Server size={18} className="text-accent-primary" />
                <h3 className="font-medium">连接标准 MCP 服务器</h3>
              </div>
              <button
                onClick={() => setShowForm(false)}
                className="text-text-tertiary hover:text-text-primary"
              >
                <X size={18} />
              </button>
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <label className="mb-1 block text-sm text-text-secondary">服务器名称 *</label>
                <input
                  type="text"
                  value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                  placeholder="alert_server"
                  className="w-full rounded-lg border border-border-primary bg-bg-primary px-3 py-2 text-sm outline-none focus:border-accent-primary"
                />
              </div>
              <div>
                <label className="mb-1 block text-sm text-text-secondary">命令 *</label>
                <input
                  type="text"
                  value={form.command}
                  onChange={(e) => setForm({ ...form, command: e.target.value })}
                  placeholder="python"
                  className="w-full rounded-lg border border-border-primary bg-bg-primary px-3 py-2 text-sm outline-none focus:border-accent-primary"
                />
              </div>
              <div>
                <label className="mb-1 block text-sm text-text-secondary">参数（空格分隔）</label>
                <input
                  type="text"
                  value={form.args}
                  onChange={(e) => setForm({ ...form, args: e.target.value })}
                  placeholder="mcp_servers/alert_server.py"
                  className="w-full rounded-lg border border-border-primary bg-bg-primary px-3 py-2 text-sm outline-none focus:border-accent-primary"
                />
              </div>
              <div>
                <label className="mb-1 block text-sm text-text-secondary">工作目录（可选）</label>
                <input
                  type="text"
                  value={form.cwd}
                  onChange={(e) => setForm({ ...form, cwd: e.target.value })}
                  placeholder="D:/ai_agent/ai-devops-agent"
                  className="w-full rounded-lg border border-border-primary bg-bg-primary px-3 py-2 text-sm outline-none focus:border-accent-primary"
                />
              </div>
            </div>
            <div className="mt-4 flex justify-end gap-2">
              <Button variant="secondary" onClick={() => setShowForm(false)}>取消</Button>
              <Button
                onClick={handleSubmit}
                disabled={!form.name.trim() || !form.command.trim() || submitting}
              >
                {submitting ? '连接中...' : '连接'}
              </Button>
            </div>
          </div>
        )}

        {/* 服务器列表 */}
        {mcpServers.length === 0 ? (
          <div className="rounded-xl border border-dashed border-border-primary py-20 text-center">
            <Plug size={36} className="mx-auto mb-3 text-text-tertiary" />
            <p className="text-text-secondary mb-1">暂无 MCP 服务器</p>
            <p className="text-sm text-text-tertiary">点击"连接标准 MCP"添加服务器</p>
          </div>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2">
            {mcpServers.map((s) => (
              <div
                key={s.name}
                className="rounded-xl border border-border-primary bg-bg-secondary p-4 hover:border-border-secondary transition-colors"
              >
                <div className="flex items-start justify-between mb-3">
                  <div className="flex items-center gap-3">
                    <div className={`flex h-10 w-10 items-center justify-center rounded-lg ${
                      s.connected
                        ? 'bg-status-success/15 text-status-success'
                        : 'bg-bg-tertiary text-text-tertiary'
                    }`}>
                      <Plug size={20} />
                    </div>
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="font-medium">{s.name}</span>
                        {s.type && (
                          <Badge variant={typeBadgeVariant(s.type)}>
                            {typeLabel(s.type)}
                          </Badge>
                        )}
                      </div>
                      <div className="text-xs text-text-tertiary">
                        {s.tool_count} 个工具
                      </div>
                    </div>
                  </div>
                  <Badge variant={s.connected ? 'success' : 'default'}>
                    {s.connected ? '已连接' : '未连接'}
                  </Badge>
                </div>

                {s.description && (
                  <p className="text-sm text-text-secondary mb-3">
                    {s.description}
                  </p>
                )}

                <div className="flex gap-2">
                  {s.connected ? (
                    <Button
                      variant="secondary"
                      size="sm"
                      onClick={() => handleDisconnect(s)}
                      className="flex-1"
                    >
                      <Unlink size={14} />
                      断开连接
                    </Button>
                  ) : (
                    <Button
                      size="sm"
                      onClick={() => s.type === 'stdio' ? undefined : connectMcp(s.name)}
                      className="flex-1"
                      disabled={s.type === 'stdio'}
                    >
                      <Link size={14} />
                      {s.type === 'stdio' ? '需通过表单连接' : '连接'}
                    </Button>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}

        {/* 说明卡片 */}
        <div className="mt-8 rounded-xl border border-border-primary bg-accent-soft/30 p-5">
          <div className="flex items-start gap-3">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-accent-soft text-accent-primary">
              <Zap size={20} />
            </div>
            <div>
              <h3 className="font-medium mb-1">什么是 MCP？</h3>
              <p className="text-sm text-text-secondary leading-relaxed">
                Model Context Protocol（模型上下文协议）让 Agent 可以在运行时动态连接外部工具服务器，
                扩展工具能力而无需修改代码。支持三种类型：
              </p>
              <ul className="mt-2 space-y-1 text-sm text-text-secondary">
                <li><strong className="text-text-primary">Mock 服务器</strong>：内置的演示服务器，用于学习测试</li>
                <li><strong className="text-text-primary">自定义服务器</strong>：通过 echo/http/shell handler 自定义工具</li>
                <li><strong className="text-text-primary">标准 MCP 服务器</strong>：通过 JSON-RPC 协议连接真实的外部 MCP 进程</li>
              </ul>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
