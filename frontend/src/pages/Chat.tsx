import { useEffect, useRef, useState, type KeyboardEvent } from 'react'
import {
  ArrowUp,
  ChevronDown,
  Folder,
  Plus,
  Plug,
  Square,
  Trash2,
} from 'lucide-react'
import { useAppStore } from '../store/useAppStore'
import type { ToolCallRecord } from '../store/useAppStore'
import type { PendingAction } from '../types'
import MarkdownText from '../components/MarkdownText'

const PREVIEW_LINES = 5

export default function Chat() {
  const { messages, isStreaming, toolHistory, liveText, currentStatus } = useAppStore()
  const scrollRef = useRef<HTMLDivElement>(null)
  const empty = messages.length === 0 && !isStreaming

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [messages, isStreaming, liveText, toolHistory])

  return (
    <div className="flex h-full flex-col bg-bg-primary">
      <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto">
        {empty ? (
          <div className="mx-auto flex h-full w-full max-w-[780px] flex-col justify-center px-6 pb-24">
            <div className="mb-2 text-center text-[11px] font-medium uppercase tracking-[0.18em] text-text-tertiary">
              DevOps workspace
            </div>
            <h1 className="mb-9 text-center text-[30px] font-normal tracking-[-0.025em] text-text-primary">
              有什么可以帮你？
            </h1>
            <Composer />
          </div>
        ) : (
          <div className="mx-auto w-full max-w-[780px] px-7 pb-10 pt-12">
            {messages.map((message, index) => {
              const isUser = message.role === 'user'
              const previous = messages[index - 1]
              const startsNewAssistantTurn =
                !isUser && previous?.role === 'assistant'
              const withTools =
                !isStreaming
                && message.role === 'assistant'
                && index === messages.length - 1
                && toolHistory.length > 0
              return (
                <div key={`${message.role}-${index}`}>
                  {startsNewAssistantTurn && <AgentResponseDivider />}
                  {withTools
                    && toolHistory.map((record, recordIndex) => (
                      <ToolCard key={`${record.turn}-${recordIndex}`} record={record} />
                    ))}
                  {isUser ? (
                    <UserBubble text={message.content} />
                  ) : (
                    <AssistantText text={message.content} />
                  )}
                </div>
              )
            })}

            {isStreaming && (
              <div>
                {toolHistory.map((record, recordIndex) => (
                  <ToolCard key={`${record.turn}-${recordIndex}`} record={record} />
                ))}
                {liveText ? (
                  <AssistantText text={liveText} streaming />
                ) : (
                  <div className="mb-4 flex items-center gap-2 text-[13px] text-text-tertiary">
                    <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-text-tertiary" />
                    {currentStatus || 'thinking'}
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </div>

      {!empty && (
        <div className="shrink-0 bg-gradient-to-t from-bg-primary via-bg-primary to-transparent pb-5 pt-7">
          <div className="mx-auto w-full max-w-[780px] px-6">
            <Composer />
            {isStreaming && currentStatus && (
              <div className="mt-1.5 text-center text-[11px] text-text-tertiary">
                {currentStatus}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

function Composer() {
  const {
    sendMessage,
    stopStreaming,
    isStreaming,
    targets,
    activeTargetId,
    activateTarget,
    setView,
    resetMessages,
    pendingActions,
    pendingActionBusyId,
    confirmPendingAction,
    cancelPendingAction,
  } = useAppStore()
  const [input, setInput] = useState('')
  const [pickerOpen, setPickerOpen] = useState(false)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const activeTarget = targets.find((target) => target.id === activeTargetId)

  useEffect(() => {
    const element = textareaRef.current
    if (!element) return
    element.style.height = 'auto'
    element.style.height = `${Math.min(element.scrollHeight, 200)}px`
  }, [input])

  const submit = () => {
    if (!input.trim() || isStreaming) return
    sendMessage(input)
    setInput('')
  }

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      submit()
    }
  }

  return (
    <div className="relative">
      {pendingActions.length > 0 && (
        <ApprovalPanel
          actions={pendingActions}
          busyId={pendingActionBusyId}
          onConfirm={confirmPendingAction}
          onCancel={cancelPendingAction}
        />
      )}

      <div className="codex-composer rounded-[28px] border border-border-primary bg-bg-primary transition-colors">
        <textarea
          ref={textareaRef}
          rows={1}
          value={input}
          onChange={(event) => setInput(event.target.value)}
          onKeyDown={handleKeyDown}
          disabled={isStreaming}
          placeholder={isStreaming ? 'agent 正在执行…' : '给 agent 分配一个任务'}
          className="max-h-[200px] w-full resize-none bg-transparent px-5 pb-1 pt-4 text-[14px] leading-[1.6] text-text-primary placeholder:text-text-tertiary focus:outline-none disabled:opacity-60"
        />
        <div className="flex items-end justify-between gap-2 px-2.5 pb-2.5 pt-1">
          <div className="flex min-w-0 items-center gap-0.5">
            <button
              onClick={() => setPickerOpen((value) => !value)}
              className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-text-secondary transition-colors hover:bg-bg-tertiary hover:text-text-primary"
              title="选择运维项目"
            >
              <Plus size={17} />
            </button>
            <button
              onClick={() => setPickerOpen((value) => !value)}
              className="flex min-w-0 items-center gap-1.5 rounded-full px-2 py-1.5 text-[12px] text-text-secondary transition-colors hover:bg-bg-tertiary hover:text-text-primary"
            >
              <Folder size={13} />
              <span className="max-w-[150px] truncate">
                {activeTarget ? activeTarget.name : '选择项目'}
              </span>
            </button>
            <button
              onClick={() => setView('skills')}
              className="hidden items-center gap-1.5 rounded-full px-2 py-1.5 text-[12px] text-text-secondary transition-colors hover:bg-bg-tertiary hover:text-text-primary sm:flex"
            >
              <Plug size={13} />
              Plugins
            </button>
          </div>
          <div className="flex shrink-0 items-center gap-1.5">
            <button
              onClick={resetMessages}
              className="flex h-7 w-7 items-center justify-center rounded-full text-text-tertiary transition-colors hover:bg-bg-tertiary hover:text-text-primary"
              title="清空对话"
            >
              <Trash2 size={13} />
            </button>
            <span className="hidden text-[11px] text-text-tertiary sm:inline">
              devops-agent
            </span>
            <button
              onClick={isStreaming ? stopStreaming : submit}
              disabled={!isStreaming && !input.trim()}
              className="flex h-8 w-8 items-center justify-center rounded-full bg-text-primary text-bg-primary transition-opacity hover:opacity-85 disabled:opacity-30"
              title={isStreaming ? '停止' : '发送'}
            >
              {isStreaming ? <Square size={12} fill="currentColor" /> : <ArrowUp size={16} />}
            </button>
          </div>
        </div>
      </div>

      {pickerOpen && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setPickerOpen(false)} />
          <div className="absolute bottom-full left-0 z-20 mb-2 max-h-72 w-[340px] overflow-y-auto rounded-xl border border-border-primary bg-bg-primary py-1 shadow-[0_12px_40px_rgba(35,31,25,0.14)]">
            <div className="px-3 pb-1 pt-2 text-[10px] uppercase tracking-[0.12em] text-text-tertiary">
              选择项目
            </div>
            {targets.length === 0 && (
              <div className="px-3 py-2 text-[12px] text-text-tertiary">还没有运维项目</div>
            )}
            {targets.map((target) => {
              const selected = target.id === activeTargetId
              return (
                <button
                  key={target.id}
                  onClick={() => {
                    activateTarget(target.id)
                    setPickerOpen(false)
                  }}
                  className={`flex w-full items-center gap-2 px-3 py-2 text-left transition-colors hover:bg-bg-tertiary ${
                    selected ? 'text-text-primary' : 'text-text-secondary'
                  }`}
                >
                  <Folder size={14} className="shrink-0 text-text-tertiary" />
                  <span className="min-w-0 flex-1 truncate text-[13px]">{target.name}</span>
                  <span className="max-w-[120px] shrink-0 truncate text-[10px] text-text-tertiary">
                    {target.root}
                  </span>
                </button>
              )
            })}
            <div className="mt-1 border-t border-border-secondary pt-1">
              <button
                onClick={() => {
                  setPickerOpen(false)
                  setView('targets')
                }}
                className="flex w-full items-center gap-2 px-3 py-2 text-left text-[12px] text-text-tertiary transition-colors hover:bg-bg-tertiary hover:text-text-primary"
              >
                <Plus size={12} />
                管理运维项目
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  )
}

function AssistantText({ text, streaming }: { text: string; streaming?: boolean }) {
  return (
    <div className="markdown-body mb-7 break-words text-[14.5px] leading-[1.72] text-text-primary">
      <MarkdownText text={text} />
      {streaming && (
        <span className="ml-1 inline-block h-[14px] w-[7px] animate-pulse rounded-sm bg-text-primary align-[-2px]" />
      )}
    </div>
  )
}

function AgentResponseDivider() {
  return (
    <div className="my-7 flex items-center gap-3 text-[11px] text-text-tertiary">
      <span className="h-px flex-1 bg-border-primary" />
      <span>Agent 继续回复</span>
      <span className="h-px flex-1 bg-border-primary" />
    </div>
  )
}

function UserBubble({ text }: { text: string }) {
  return (
    <div className="mb-7 flex justify-end">
      <div className="max-w-[82%] whitespace-pre-wrap break-words rounded-[20px] bg-bg-tertiary px-4 py-2.5 text-[14px] leading-[1.65] text-text-primary">
        {text}
      </div>
    </div>
  )
}

function ToolCard({ record }: { record: ToolCallRecord }) {
  const [expanded, setExpanded] = useState(false)
  const command = toolCommand(record.input)
  const all = (record.output || '').replace(/\s+$/, '').split('\n')
  const hasOutput = Boolean(record.output && record.output.trim())
  const total = hasOutput ? all.length : 0
  const headCount = expanded ? total : Math.min(PREVIEW_LINES, total)
  const tailCount = expanded ? 0 : Math.min(PREVIEW_LINES, Math.max(0, total - headCount))
  const omitted = total - headCount - tailCount
  const headLines = all.slice(0, headCount)
  const tailLines = tailCount > 0 ? all.slice(total - tailCount) : []

  const running = record.status === 'running' || record.status === 'pending'
  const failed = record.status === 'error'
  const dotClass = running
    ? 'animate-pulse bg-status-warning'
    : failed
      ? 'bg-status-error'
      : 'bg-status-success'
  const verb = running ? 'Running' : 'Ran'

  return (
    <div className="mb-3 overflow-hidden rounded-xl border border-border-secondary">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left transition-colors hover:bg-bg-secondary"
      >
        <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${dotClass}`} />
        <span className="shrink-0 text-[12px] font-medium text-text-secondary">{verb}</span>
        <span className="min-w-0 flex-1 truncate font-mono text-[12px] text-text-primary">
          {command}
        </span>
        {hasOutput && (
          <ChevronDown
            size={12}
            className={`shrink-0 text-text-tertiary transition-transform ${
              expanded ? 'rotate-180' : ''
            }`}
          />
        )}
      </button>
      {hasOutput && (
        <pre
          className={`border-t border-border-secondary bg-bg-secondary px-3 py-2 font-mono text-[11.5px] leading-[1.65] text-text-secondary ${
            expanded ? 'max-h-80 overflow-auto' : ''
          }`}
        >
          {headLines.join('\n')}
          {omitted > 0 ? `\n… +${omitted} lines` : ''}
          {tailLines.length > 0 ? `\n${tailLines.join('\n')}` : ''}
        </pre>
      )}
      {!hasOutput && !running && (
        <div className="border-t border-border-secondary px-3 py-1.5 font-mono text-[11.5px] text-text-tertiary">
          (no output)
        </div>
      )}
    </div>
  )
}

function ApprovalPanel({
  actions,
  busyId,
  onConfirm,
  onCancel,
}: {
  actions: PendingAction[]
  busyId: string
  onConfirm: (actionId: string) => Promise<void>
  onCancel: (actionId: string, reason?: string) => Promise<void>
}) {
  const action = actions[0]
  if (!action) return null

  return (
    <div className="mb-3 overflow-hidden rounded-xl border border-status-warning/30">
      <div className="flex items-center justify-between border-b border-status-warning/20 bg-status-warning/5 px-3 py-2 text-[12px]">
        <span className="text-status-warning">需要审批 · {action.title}</span>
        <span className="shrink-0 text-text-tertiary">{actions.length} 条待处理</span>
      </div>
      <pre className="max-h-32 overflow-auto whitespace-pre-wrap break-words px-3 py-2 font-mono text-[12px] text-text-secondary">
        {formatActionCommand(action)}
      </pre>
      <div className="flex items-center gap-4 border-t border-status-warning/20 px-3 py-2 text-[12px]">
        <button
          disabled={busyId === action.id}
          onClick={() => onConfirm(action.id)}
          className="text-text-primary hover:underline disabled:opacity-50"
        >
          {busyId === action.id ? '执行中…' : '批准并执行'}
        </button>
        <button
          disabled={busyId === action.id}
          onClick={() => onCancel(action.id, 'Rejected from chat')}
          className="text-text-tertiary hover:underline disabled:opacity-50"
        >
          拒绝
        </button>
        <span className="ml-auto truncate text-[11px] text-text-tertiary">
          {action.target_id || 'global'} · {action.risk_level || 'approval'}
        </span>
      </div>
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
  if (tool === 'target_restart') {
    return action.summary || '重启当前运维项目服务'
  }
  if (tool === 'target_deploy') {
    return action.summary || '执行当前项目配置的部署命令'
  }
  return `${tool}\n${JSON.stringify(input, null, 2)}`
}

function toolCommand(input?: Record<string, any>) {
  if (!input) return ''
  const command = input.command ?? input.cmd
  if (typeof command === 'string' && command) return command
  const path = input.path
  if (typeof path === 'string' && path) return path
  if (Object.keys(input).length === 0) return ''
  return JSON.stringify(input)
}
