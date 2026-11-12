import { useEffect, useState } from 'react'
import {
  Link,
  Plus,
  Plug,
  RefreshCw,
  Server,
  Unlink,
  X,
} from 'lucide-react'
import { useAppStore } from '../store/useAppStore'
import Button from '../components/Button'
import Badge from '../components/Badge'
import {
  SectionLabel,
  SplitView,
  WorkspaceEmpty,
  WorkspacePage,
  WorkspacePanel,
} from '../components/Workspace'

export default function MCP() {
  const {
    mcpServers,
    fetchMcpServers,
    connectMcp,
    disconnectMcp,
    connectStdioMcp,
    disconnectStdioMcp,
    connectSseMcp,
    disconnectSseMcp,
  } = useAppStore()
  const [showForm, setShowForm] = useState(false)
  const [formMode, setFormMode] = useState<'stdio' | 'sse'>('stdio')
  const [selectedName, setSelectedName] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [form, setForm] = useState({ name: '', command: 'python', args: '', cwd: '' })
  const [sseForm, setSseForm] = useState({ name: '', url: '' })

  useEffect(() => {
    fetchMcpServers()
  }, [fetchMcpServers])

  const selected = mcpServers.find((server) => server.name === selectedName) || mcpServers[0]

  const handleDisconnect = (server: { name: string; type?: string }) => {
    if (server.type === 'stdio') return disconnectStdioMcp(server.name)
    if (server.type === 'sse') return disconnectSseMcp(server.name)
    return disconnectMcp(server.name)
  }

  const handleSubmit = async () => {
    setSubmitting(true)
    try {
      if (formMode === 'sse') {
        if (!sseForm.name.trim() || !sseForm.url.trim()) return
        await connectSseMcp({ name: sseForm.name.trim(), url: sseForm.url.trim() })
        setSseForm({ name: '', url: '' })
      } else {
        if (!form.name.trim() || !form.command.trim()) return
        await connectStdioMcp({
          name: form.name.trim(),
          command: form.command.trim(),
          args: form.args.trim() ? form.args.split(/\s+/) : [],
          cwd: form.cwd.trim() || undefined,
        })
        setForm({ name: '', command: 'python', args: '', cwd: '' })
      }
      setShowForm(false)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <WorkspacePage
      title="MCP"
      description="连接外部 Model Context Protocol Server，在运行时扩展 Agent 工具。"
      actions={
        <>
          <Button variant="secondary" onClick={fetchMcpServers}>
            <RefreshCw size={12} />
            刷新
          </Button>
          <Button onClick={() => setShowForm((value) => !value)}>
            <Plus size={12} />
            连接 Server
          </Button>
        </>
      }
      wide
    >
      {showForm && (
        <WorkspacePanel padded className="mb-4">
          <div className="flex items-start justify-between">
            <div>
              <SectionLabel>连接标准 MCP Server</SectionLabel>
              <p className="mt-1 text-[10.5px] text-text-tertiary">
                支持本地 stdio 子进程和远程 SSE。
              </p>
            </div>
            <Button size="sm" variant="ghost" onClick={() => setShowForm(false)}>
              <X size={13} />
            </Button>
          </div>
          <div className="mt-4 flex gap-1">
            {(['stdio', 'sse'] as const).map((mode) => (
              <button
                key={mode}
                onClick={() => setFormMode(mode)}
                className={`rounded-lg px-3 py-1.5 text-[11px] ${
                  formMode === mode
                    ? 'bg-text-primary text-bg-primary'
                    : 'bg-bg-secondary text-text-secondary hover:bg-bg-hover'
                }`}
              >
                {mode === 'stdio' ? '本地 Stdio' : '远程 SSE'}
              </button>
            ))}
          </div>
          {formMode === 'sse' ? (
            <div className="mt-4 grid gap-3 sm:grid-cols-2">
              <Field label="服务器名称">
                <input value={sseForm.name} onChange={(event) => setSseForm({ ...sseForm, name: event.target.value })} placeholder="remote_mcp" className={inputClass} />
              </Field>
              <Field label="SSE 端点">
                <input value={sseForm.url} onChange={(event) => setSseForm({ ...sseForm, url: event.target.value })} placeholder="http://localhost:8080/sse" className={inputClass} />
              </Field>
            </div>
          ) : (
            <div className="mt-4 grid gap-3 sm:grid-cols-2">
              <Field label="服务器名称">
                <input value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} placeholder="alert_server" className={inputClass} />
              </Field>
              <Field label="启动命令">
                <input value={form.command} onChange={(event) => setForm({ ...form, command: event.target.value })} placeholder="python" className={inputClass} />
              </Field>
              <Field label="参数">
                <input value={form.args} onChange={(event) => setForm({ ...form, args: event.target.value })} placeholder="mcp_servers/alert_server.py" className={inputClass} />
              </Field>
              <Field label="工作目录">
                <input value={form.cwd} onChange={(event) => setForm({ ...form, cwd: event.target.value })} placeholder="可选" className={inputClass} />
              </Field>
            </div>
          )}
          <div className="mt-4 flex justify-end gap-2">
            <Button variant="secondary" onClick={() => setShowForm(false)}>取消</Button>
            <Button
              onClick={handleSubmit}
              disabled={
                submitting ||
                (formMode === 'sse'
                  ? !sseForm.name.trim() || !sseForm.url.trim()
                  : !form.name.trim() || !form.command.trim())
              }
            >
              {submitting ? '连接中…' : '连接'}
            </Button>
          </div>
        </WorkspacePanel>
      )}

      {mcpServers.length === 0 ? (
        <WorkspaceEmpty
          icon={<Plug size={17} />}
          title="暂无 MCP Server"
          description="连接 MCP Server 后，它的工具会以 mcp__server__tool 形式进入 Agent 工具目录。"
        />
      ) : (
        <SplitView
          asideWidth="380px"
          aside={<McpDetail server={selected} onDisconnect={handleDisconnect} onConnect={connectMcp} />}
        >
          <WorkspacePanel>
            <div className="flex items-center justify-between border-b border-border-secondary px-4 py-3">
              <SectionLabel>Servers</SectionLabel>
              <span className="text-[10px] text-text-tertiary">{mcpServers.length}</span>
            </div>
            {mcpServers.map((server) => (
              <button
                key={server.name}
                onClick={() => setSelectedName(server.name)}
                className={`flex w-full items-center gap-3 border-b border-border-secondary px-4 py-3 text-left transition-colors last:border-0 ${
                  selected?.name === server.name ? 'bg-bg-active' : 'hover:bg-bg-hover'
                }`}
              >
                <span className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-lg ${
                  server.connected
                    ? 'bg-status-success/10 text-status-success'
                    : 'bg-bg-tertiary text-text-tertiary'
                }`}>
                  <Plug size={14} />
                </span>
                <div className="min-w-0 flex-1">
                  <div className="truncate text-[12.5px] font-medium">{server.name}</div>
                  <div className="mt-0.5 text-[10.5px] text-text-tertiary">
                    {typeLabel(server.type)} · {server.tool_count} 个工具
                  </div>
                </div>
                <Badge variant={server.connected ? 'success' : 'default'}>
                  {server.connected ? '已连接' : '未连接'}
                </Badge>
              </button>
            ))}
          </WorkspacePanel>
        </SplitView>
      )}
    </WorkspacePage>
  )
}

function McpDetail({
  server,
  onDisconnect,
  onConnect,
}: {
  server: any
  onDisconnect: (server: any) => void
  onConnect: (name: string) => Promise<void>
}) {
  if (!server) {
    return (
      <WorkspacePanel padded className="min-h-[380px]">
        <WorkspaceEmpty icon={<Server size={17} />} title="选择一个 MCP Server" />
      </WorkspacePanel>
    )
  }

  return (
    <WorkspacePanel padded>
      <SectionLabel>Server 详情</SectionLabel>
      <div className="mt-2 flex items-start justify-between gap-3">
        <div>
          <h2 className="font-mono text-[15px] font-medium">{server.name}</h2>
          <p className="mt-1 text-[11px] text-text-tertiary">{typeLabel(server.type)}</p>
        </div>
        <Badge variant={server.connected ? 'success' : 'default'}>
          {server.connected ? '已连接' : '未连接'}
        </Badge>
      </div>
      <p className="mt-4 text-[11.5px] leading-6 text-text-secondary">
        {server.description || '该 Server 未提供说明。'}
      </p>
      <div className="mt-5 grid grid-cols-2 gap-3 border-y border-border-secondary py-4 text-[11px]">
        <Meta label="工具数" value={String(server.tool_count || 0)} />
        <Meta label="类型" value={typeLabel(server.type)} />
      </div>
      <div className="mt-4">
        {server.connected ? (
          <Button size="sm" variant="secondary" onClick={() => onDisconnect(server)}>
            <Unlink size={12} />
            断开连接
          </Button>
        ) : (
          <Button
            size="sm"
            onClick={() => (server.type === 'stdio' || server.type === 'sse') ? undefined : onConnect(server.name)}
            disabled={server.type === 'stdio' || server.type === 'sse'}
          >
            <Link size={12} />
            {(server.type === 'stdio' || server.type === 'sse') ? '请通过表单连接' : '连接'}
          </Button>
        )}
      </div>
    </WorkspacePanel>
  )
}

function typeLabel(type?: string) {
  if (type === 'stdio') return '本地 Stdio'
  if (type === 'sse') return '远程 SSE'
  if (type === 'custom') return '自定义'
  if (type === 'builtin') return '内置 Mock'
  return '未知类型'
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label>
      <div className="mb-1.5 text-[10.5px] font-medium text-text-secondary">{label}</div>
      {children}
    </label>
  )
}

function Meta({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-text-tertiary">{label}</div>
      <div className="mt-1 text-text-secondary">{value}</div>
    </div>
  )
}

const inputClass = 'h-8 w-full rounded-lg border border-border-primary bg-bg-secondary px-3 text-[11.5px] outline-none focus:border-text-tertiary focus:bg-bg-primary'
