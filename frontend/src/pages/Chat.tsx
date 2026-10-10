import { useEffect, useRef, useState } from 'react'
import {
  Bot,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Clock,
  Eraser,
  Loader2,
  MessageSquare,
  Plus,
  Send,
  ShieldAlert,
  Square,
  Trash2,
  User,
  Wrench,
  X,
  XCircle,
} from 'lucide-react'
import { useAppStore } from '../store/useAppStore'
import type { ToolCallRecord } from '../store/useAppStore'
import type { PendingAction } from '../types'
import Badge from '../components/Badge'
import Button from '../components/Button'

export default function Chat() {
  const {
    messages,
    isStreaming,
    sendMessage,
    stopStreaming,
    currentStatus,
    toolHistory,
    liveText,
    currentTurn,
    sessionId,
    chatSessions,
    newChat,
    switchChat,
    deleteChat,
    fetchChatSessions,
    pendingActions,
    pendingActionBusyId,
    confirmPendingAction,
    cancelPendingAction,
  } = useAppStore()
  const [input, setInput] = useState('')
  const [showTrace, setShowTrace] = useState(true)
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    fetchChatSessions()
  }, [fetchChatSessions])

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [messages, isStreaming, liveText])

  const handleSend = () => {
    if (!input.trim() || isStreaming) return
    sendMessage(input)
    setInput('')
  }

  const handleKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      handleSend()
    }
  }

  const currentSession = chatSessions.find((item) => item.id === sessionId)
  const title = currentSession?.title || '新对话'

  return (
    <div className="flex h-full min-h-0">
      <aside className="flex w-60 shrink-0 flex-col border-r border-border-secondary bg-bg-secondary">
        <div className="border-b border-border-secondary p-3">
          <Button className="w-full" onClick={newChat}>
            <Plus size={15} />
            新对话
          </Button>
        </div>

        <div className="flex-1 overflow-y-auto p-2">
          <div className="mb-1 px-2 text-[11px] font-medium uppercase tracking-wide text-text-tertiary">
            最近会话
          </div>
          <div className="space-y-0.5">
            {chatSessions.map((session) => {
              const active = session.id === sessionId
              return (
                <div
                  key={session.id}
                  className={`group flex items-center rounded-lg transition-colors ${
                    active
                      ? 'bg-accent-soft text-accent-primary'
                      : 'text-text-secondary hover:bg-bg-hover hover:text-text-primary'
                  }`}
                >
                  <button
                    onClick={() => switchChat(session.id)}
                    className="min-w-0 flex-1 px-2.5 py-2 text-left"
                  >
                    <div className="truncate text-xs font-medium">
                      {session.title}
                    </div>
                    <div className="mt-0.5 text-[10px] text-text-tertiary">
                      {formatRelative(session.updatedAt)}
                    </div>
                  </button>
                  <button
                    onClick={(event) => {
                      event.stopPropagation()
                      deleteChat(session.id)
                    }}
                    className="mr-1 hidden h-7 w-7 items-center justify-center rounded-md text-text-tertiary hover:bg-bg-active hover:text-status-error group-hover:flex"
                    title="删除会话"
                  >
                    <Trash2 size={13} />
                  </button>
                </div>
              )
            })}
          </div>

          {chatSessions.length === 0 && (
            <div className="px-3 py-8 text-center text-xs text-text-tertiary">
              发送第一条消息后会出现在这里
            </div>
          )}
        </div>
      </aside>

      <section className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 shrink-0 items-center justify-between border-b border-border-secondary px-5">
          <div className="flex min-w-0 items-center gap-3">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent-primary/15 text-accent-primary">
              <Bot size={17} />
            </div>
            <div className="min-w-0">
              <div className="truncate text-sm font-semibold">{title}</div>
              <div className="text-[11px] text-text-tertiary">
                {sessionId ? shortId(sessionId) : '尚未创建 Session'}
              </div>
            </div>
          </div>
          <div className="text-xs text-text-tertiary">
            {isStreaming ? '运行中' : '就绪'}
          </div>
        </header>

        <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto px-5 py-5">
          <div className="mx-auto max-w-3xl space-y-5">
            {messages.length === 0 && <EmptyState />}

            {messages.map((message, index) => {
              const isLastAssistant =
                message.role === 'assistant'
                && index === messages.length - 1
                && toolHistory.length > 0
              return (
                <div key={`${message.role}-${index}`}>
                  {isLastAssistant && (
                    <div className="mb-3">
                      <ExecutionTrace
                        currentStatus={currentStatus}
                        currentTurn={currentTurn}
                        toolHistory={toolHistory}
                        liveText=""
                        showTrace={showTrace}
                        onToggle={() => setShowTrace(!showTrace)}
                        streaming={false}
                      />
                    </div>
                  )}
                  <MessageBubble
                    role={message.role}
                    content={message.content}
                  />
                </div>
              )
            })}

            {isStreaming && (
              <ExecutionTrace
                currentStatus={currentStatus}
                currentTurn={currentTurn}
                toolHistory={toolHistory}
                liveText={liveText}
                showTrace={showTrace}
                onToggle={() => setShowTrace(!showTrace)}
                streaming
              />
            )}

            {isStreaming && (
              <div className="flex justify-center">
                <button
                  onClick={stopStreaming}
                  className="flex items-center gap-2 rounded-lg border border-status-error/30 bg-status-error/10 px-4 py-2 text-xs text-status-error transition-colors hover:bg-status-error/20"
                >
                  <Square size={12} />
                  停止生成
                </button>
              </div>
            )}
          </div>
        </div>

        <div className="shrink-0 border-t border-border-secondary bg-bg-secondary p-4">
          <div className="mx-auto max-w-3xl">
            {pendingActions.length > 0 && (
              <InlineApprovals
                actions={pendingActions}
                busyId={pendingActionBusyId}
                disabled={isStreaming}
                onConfirm={confirmPendingAction}
                onCancel={cancelPendingAction}
              />
            )}
            <div className="rounded-xl border border-border-primary bg-bg-primary p-2 transition-colors focus-within:border-accent-primary">
              <textarea
                value={input}
                onChange={(event) => setInput(event.target.value)}
                onKeyDown={handleKeyDown}
                disabled={isStreaming}
                placeholder={
                  isStreaming
                    ? 'Agent 正在工作...'
                    : '输入消息，回车发送，Shift+Enter 换行'
                }
                className="max-h-40 min-h-[52px] w-full resize-none bg-transparent px-2 py-2 text-sm text-text-primary placeholder:text-text-tertiary focus:outline-none disabled:opacity-60"
                rows={1}
              />
              <div className="flex items-center justify-between px-1 pt-1">
                <div className="flex items-center gap-2 text-[11px] text-text-tertiary">
                  <span>{input.length} / 4000</span>
                </div>
                <div className="flex items-center gap-1">
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => setInput('')}
                    disabled={!input || isStreaming}
                    title="清空输入"
                  >
                    <Eraser size={14} />
                    清空
                  </Button>
                  <Button
                    size="sm"
                    onClick={handleSend}
                    disabled={isStreaming || !input.trim()}
                  >
                    {isStreaming
                      ? <Loader2 size={14} className="animate-spin" />
                      : <Send size={14} />}
                    发送
                  </Button>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>
    </div>
  )
}

function InlineApprovals({
  actions,
  busyId,
  disabled,
  onConfirm,
  onCancel,
}: {
  actions: PendingAction[]
  busyId: string
  disabled: boolean
  onConfirm: (actionId: string) => Promise<void>
  onCancel: (actionId: string, reason?: string) => Promise<void>
}) {
  return (
    <div className="mb-3 space-y-2">
      {actions.map((action) => (
        <div
          key={action.id}
          className="rounded-xl border border-status-warning/35 bg-status-warning/10 p-3"
        >
          <div className="flex items-start gap-3">
            <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-status-warning/15 text-status-warning">
              <ShieldAlert size={16} />
            </div>
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <div className="text-sm font-medium">{action.title}</div>
                <Badge variant="warning">{action.risk_level || 'approval'}</Badge>
              </div>
              <div className="mt-1 text-xs text-text-tertiary">
                {action.target_id || '全局操作'} · {action.id}
              </div>
              <pre className="mt-2 max-h-32 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-bg-primary/80 px-3 py-2 font-mono text-xs text-text-secondary">
                {formatActionCommand(action)}
              </pre>
            </div>
            <div className="flex shrink-0 gap-2">
              <Button
                size="sm"
                variant="secondary"
                disabled={disabled || busyId === action.id}
                onClick={() => onCancel(action.id, 'Rejected from chat')}
              >
                <X size={14} />
                拒绝
              </Button>
              <Button
                size="sm"
                disabled={disabled || busyId === action.id}
                onClick={() => onConfirm(action.id)}
              >
                {busyId === action.id ? (
                  <Loader2 size={14} className="animate-spin" />
                ) : (
                  <Check size={14} />
                )}
                批准并执行
              </Button>
            </div>
          </div>
          {disabled && (
            <div className="mt-2 text-[11px] text-text-tertiary">
              等待 Agent 当前回复结束后即可审批。
            </div>
          )}
        </div>
      ))}
    </div>
  )
}

function formatActionCommand(action: PendingAction) {
  const tool = action.payload?.tool || action.steps?.[0]?.tool || action.action_code
  const input = action.payload?.input || action.steps?.[0]?.input || {}
  if (tool === 'bash') {
    return String(input.command || '(no command)')
  }
  if (tool === 'target_write_file') {
    const content = String(input.content || '')
    return `写入文件: ${input.path}\n大小: ${new Blob([content]).size} bytes\n\n${content.slice(0, 1000)}${content.length > 1000 ? '\n... (truncated)' : ''}`
  }
  if (tool === 'target_edit_file') {
    return `编辑文件: ${input.path}\n\n替换前:\n${String(input.old_text || '').slice(0, 1000)}\n\n替换后:\n${String(input.new_text || '').slice(0, 1000)}`
  }
  if (tool === 'target_restart') return '重启当前运维项目服务'
  if (tool === 'target_deploy') return '执行当前项目配置的部署命令'
  return `${tool}\n${JSON.stringify(input, null, 2)}`
}

function ExecutionTrace({
  currentStatus,
  currentTurn,
  toolHistory,
  liveText,
  showTrace,
  onToggle,
  streaming,
}: {
  currentStatus: string
  currentTurn: number
  toolHistory: ToolCallRecord[]
  liveText: string
  showTrace: boolean
  onToggle: () => void
  streaming: boolean
}) {
  return (
    <div className="overflow-hidden rounded-lg border border-border-primary bg-bg-secondary/60">
      <button
        onClick={onToggle}
        className="flex w-full items-center justify-between px-4 py-3 hover:bg-bg-hover/50"
      >
        <div className="flex items-center gap-2">
          {showTrace
            ? <ChevronDown size={14} className="text-text-secondary" />
            : <ChevronRight size={14} className="text-text-secondary" />}
          {streaming
            ? <Loader2 size={14} className="animate-spin text-accent-primary" />
            : <Clock size={14} className="text-text-secondary" />}
          <span className="text-xs font-medium">
            {streaming ? '正在思考' : '思考过程'}
          </span>
          {currentTurn > 0 && (
            <span className="text-[10px] text-text-tertiary">
              第 {currentTurn} 轮
            </span>
          )}
          {toolHistory.length > 0 && (
            <span className="text-[10px] text-text-tertiary">
              已调用 {toolHistory.length} 个工具
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[11px] text-text-tertiary">
            {streaming ? currentStatus : '已完成'}
          </span>
          {!streaming && <Badge variant="success">已完成</Badge>}
        </div>
      </button>

      {showTrace && (
        <div className="border-t border-border-secondary">
          {toolHistory.length === 0 && !liveText && (
            <div className="flex items-center gap-2 px-4 py-3 text-xs text-text-tertiary">
              <Loader2 size={12} className={streaming ? 'animate-spin' : ''} />
              等待工具调用
            </div>
          )}
          {toolHistory.map((record) => (
            <ToolCallRow key={`${record.turn}-${record.tool}`} record={record} />
          ))}
          {liveText && (
            <div className="border-t border-border-secondary bg-accent-primary/5 px-4 py-3">
              <div className="mb-1 flex items-center gap-2 text-[10px] font-medium text-accent-primary">
                <Bot size={12} />
                生成回复中
              </div>
              <p className="whitespace-pre-wrap break-words text-xs text-text-primary">
                {liveText}
                <span className="ml-0.5 inline-block h-3 w-1.5 animate-pulse bg-accent-primary" />
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function ToolCallRow({ record }: { record: ToolCallRecord }) {
  const [expanded, setExpanded] = useState(false)
  const icon = {
    running: <Loader2 size={12} className="animate-spin text-status-warning" />,
    done: <CheckCircle2 size={12} className="text-status-success" />,
    error: <XCircle size={12} className="text-status-error" />,
    pending: <Wrench size={12} className="text-text-tertiary" />,
  }[record.status]

  return (
    <div className="border-t border-border-secondary first:border-t-0">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex w-full items-center justify-between px-4 py-2.5 hover:bg-bg-hover/40"
      >
        <div className="flex min-w-0 items-center gap-2">
          {expanded
            ? <ChevronDown size={12} className="text-text-tertiary" />
            : <ChevronRight size={12} className="text-text-tertiary" />}
          {icon}
          <span className="text-xs font-medium">{record.tool}</span>
          {record.input && Object.keys(record.input).length > 0 && (
            <span className="max-w-[260px] truncate text-[10px] text-text-tertiary">
              {JSON.stringify(record.input)}
            </span>
          )}
        </div>
        {record.duration_ms !== undefined && (
          <span className="text-[10px] text-text-tertiary">
            {record.duration_ms}ms
          </span>
        )}
      </button>
      {expanded && record.output !== undefined && (
        <pre className="max-h-48 overflow-auto border-t border-border-secondary px-4 py-3 text-[11px] text-text-secondary">
          {record.output}
        </pre>
      )}
    </div>
  )
}

function MessageBubble({ role, content }: { role: string; content: string }) {
  const isUser = role === 'user'
  return (
    <div className={`flex items-start gap-3 ${isUser ? 'justify-end' : ''}`}>
      {!isUser && (
        <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-accent-primary/15 text-accent-primary">
          <Bot size={14} />
        </div>
      )}
      <div
        className={
          isUser
            ? 'max-w-[74%] rounded-2xl rounded-tr-sm bg-accent-primary px-4 py-2.5 text-sm leading-relaxed text-white'
            : 'min-w-0 flex-1 whitespace-pre-wrap break-words px-1 py-1 text-sm leading-7 text-text-primary'
        }
      >
        {content}
      </div>
      {isUser && (
        <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-accent-primary/15 text-accent-primary">
          <User size={14} />
        </div>
      )}
    </div>
  )
}

function EmptyState() {
  const { sendMessage, newChat } = useAppStore()
  const quickPrompts = [
    '分析一下最近一小时的服务异常',
    '检查服务器 CPU、内存和磁盘状态',
    '创建一个每日巡检任务',
    '查看当前有哪些工具可用',
  ]

  return (
    <div className="flex flex-col items-center justify-center py-16 text-center">
      <div className="mb-5 flex h-14 w-14 items-center justify-center rounded-2xl bg-accent-primary text-white shadow-lg shadow-accent-primary/20">
        <MessageSquare size={24} />
      </div>
      <h2 className="mb-1.5 text-xl font-semibold">开始新的运维对话</h2>
      <p className="mb-7 max-w-md text-sm text-text-secondary">
        可以查询系统、分析故障、创建任务，也可以继续之前的历史会话。
      </p>
      <div className="grid w-full max-w-xl grid-cols-2 gap-2.5">
        {quickPrompts.map((prompt) => (
          <button
            key={prompt}
            onClick={() => {
              newChat()
              sendMessage(prompt)
            }}
            className="rounded-lg border border-border-primary bg-bg-secondary px-4 py-3 text-left text-sm text-text-secondary transition-colors hover:border-accent-primary/50 hover:bg-accent-soft hover:text-text-primary"
          >
            {prompt}
          </button>
        ))}
      </div>
    </div>
  )
}

function shortId(value: string) {
  return value.length > 18
    ? `${value.slice(0, 8)}...${value.slice(-5)}`
    : value
}

function formatRelative(value: number) {
  const diff = Date.now() - value
  if (diff < 60_000) return '刚刚'
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)} 分钟前`
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)} 小时前`
  return new Date(value).toLocaleDateString()
}
