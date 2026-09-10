import { useState, useRef, useEffect } from 'react'
import { Send, Bot, User, Loader2, Play, Square, ChevronDown, ChevronRight, Wrench, CheckCircle2, XCircle, Clock } from 'lucide-react'
import { useAppStore } from '../store/useAppStore'
import type { ToolCallRecord } from '../store/useAppStore'

export default function Chat() {
  const { messages, isStreaming, sendMessage, stopStreaming, currentStatus, toolHistory, liveText, currentTurn } = useAppStore()
  const [input, setInput] = useState('')
  const [showTrace, setShowTrace] = useState(true)
  const scrollRef = useRef<HTMLDivElement>(null)

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

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  return (
    <div className="flex h-full flex-col">
      {/* 消息区 */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 py-6">
        <div className="mx-auto max-w-3xl space-y-5">
          {messages.length === 0 && <EmptyState />}

          {messages.map((msg, i) => (
            <MessageBubble
              key={i}
              role={msg.role}
              content={msg.content}
            />
          ))}

          {/* 执行轨迹面板（流式过程中显示） */}
          {isStreaming && (
            <ExecutionTrace
              currentStatus={currentStatus}
              currentTurn={currentTurn}
              toolHistory={toolHistory}
              liveText={liveText}
              showTrace={showTrace}
              onToggle={() => setShowTrace(!showTrace)}
            />
          )}

          {/* 停止按钮 */}
          {isStreaming && (
            <div className="flex justify-center">
              <button
                onClick={stopStreaming}
                className="flex items-center gap-2 rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-2 text-xs text-red-400 hover:bg-red-500/20 transition-colors"
              >
                <Square size={12} />
                停止生成
              </button>
            </div>
          )}
        </div>
      </div>

      {/* 输入区 */}
      <div className="border-t border-border-secondary bg-bg-secondary p-4">
        <div className="mx-auto max-w-3xl">
          <div className="flex items-end gap-2 rounded-xl border border-border-primary bg-bg-primary p-2 focus-within:border-accent-primary transition-colors">
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              disabled={isStreaming}
              placeholder={isStreaming ? 'Agent 正在工作...' : '输入消息，回车发送，Shift+Enter 换行...'}
              className="flex-1 resize-none bg-transparent px-2 py-2 text-sm text-text-primary placeholder:text-text-tertiary focus:outline-none disabled:opacity-60"
              rows={1}
              style={{ maxHeight: '160px', minHeight: '40px' }}
            />
            <button
              onClick={handleSend}
              disabled={isStreaming || !input.trim()}
              className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-accent-primary text-white hover:bg-accent-hover disabled:opacity-40 disabled:cursor-not-allowed transition-all"
            >
              {isStreaming ? <Loader2 size={16} className="animate-spin" /> : <Send size={16} />}
            </button>
          </div>
          <p className="mt-2 text-center text-[11px] text-text-tertiary">
            支持 22 个工具调用 · 自动上下文压缩 · 错误恢复
          </p>
        </div>
      </div>
    </div>
  )
}

function ExecutionTrace({
  currentStatus,
  currentTurn,
  toolHistory,
  liveText,
  showTrace,
  onToggle,
}: {
  currentStatus: string
  currentTurn: number
  toolHistory: ToolCallRecord[]
  liveText: string
  showTrace: boolean
  onToggle: () => void
}) {
  return (
    <div className="rounded-2xl border border-border-primary bg-bg-secondary/50 overflow-hidden">
      {/* 头部 */}
      <button
        onClick={onToggle}
        className="flex w-full items-center justify-between px-4 py-2.5 hover:bg-bg-secondary transition-colors"
      >
        <div className="flex items-center gap-2">
          {showTrace ? <ChevronDown size={14} className="text-text-secondary" /> : <ChevronRight size={14} className="text-text-secondary" />}
          <Loader2 size={14} className="animate-spin text-accent-primary" />
          <span className="text-xs font-medium text-text-primary">Agent 执行中</span>
          {currentTurn > 0 && (
            <span className="rounded-full bg-accent-primary/15 px-2 py-0.5 text-[10px] text-accent-primary">
              第 {currentTurn} 轮
            </span>
          )}
        </div>
        <span className="text-xs text-text-secondary">{currentStatus}</span>
      </button>

      {/* 轨迹展开区 */}
      {showTrace && (
        <div className="border-t border-border-primary/50 px-4 py-3 space-y-2">
          {toolHistory.length === 0 && !liveText && (
            <div className="flex items-center gap-2 text-xs text-text-tertiary">
              <Clock size={12} />
              等待工具调用...
            </div>
          )}

          {/* 工具调用列表 */}
          {toolHistory.map((t, i) => (
            <ToolCallRow key={i} record={t} />
          ))}

          {/* 流式文字输出 */}
          {liveText && (
            <div className="rounded-lg bg-accent-primary/5 border border-accent-primary/20 px-3 py-2">
              <div className="flex items-center gap-2 mb-1">
                <Bot size={12} className="text-accent-primary" />
                <span className="text-[10px] text-accent-primary font-medium">生成回复中</span>
              </div>
              <p className="text-xs text-text-primary whitespace-pre-wrap break-words">
                {liveText}
                <span className="inline-block w-1.5 h-3 bg-accent-primary animate-pulse ml-0.5" />
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

  const statusIcon = () => {
    switch (record.status) {
      case 'running':
        return <Loader2 size={12} className="animate-spin text-yellow-500" />
      case 'done':
        return <CheckCircle2 size={12} className="text-green-500" />
      case 'error':
        return <XCircle size={12} className="text-red-500" />
      default:
        return <Wrench size={12} className="text-text-tertiary" />
    }
  }

  return (
    <div className="rounded-lg border border-border-primary/50 bg-bg-primary/50">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex w-full items-center justify-between px-3 py-2 hover:bg-bg-primary transition-colors"
      >
        <div className="flex items-center gap-2">
          {expanded ? <ChevronDown size={12} className="text-text-secondary" /> : <ChevronRight size={12} className="text-text-secondary" />}
          {statusIcon()}
          <span className="text-xs font-medium text-text-primary">{record.tool}</span>
          {record.input && Object.keys(record.input).length > 0 && (
            <span className="text-[10px] text-text-tertiary truncate max-w-[120px]">
              {JSON.stringify(record.input)}
            </span>
          )}
        </div>
        {record.duration_ms !== undefined && (
          <span className="text-[10px] text-text-tertiary">{record.duration_ms}ms</span>
        )}
      </button>
      {expanded && record.output !== undefined && (
        <div className="border-t border-border-primary/30 px-3 py-2">
          <pre className="text-[11px] text-text-secondary whitespace-pre-wrap break-words max-h-40 overflow-auto">
            {record.output}
          </pre>
        </div>
      )}
    </div>
  )
}

function MessageBubble({ role, content }: { role: string; content: string }) {
  const isUser = role === 'user'

  return (
    <div className={`flex items-start gap-3 ${isUser ? 'flex-row-reverse' : ''}`}>
      <div
        className={`flex h-8 w-8 items-center justify-center rounded-full shrink-0 ${
          isUser
            ? 'bg-purple-500/15 text-purple-400'
            : 'bg-accent-primary/15 text-accent-primary'
        }`}
      >
        {isUser ? <User size={16} /> : <Bot size={16} />}
      </div>
      <div
        className={`max-w-[75%] rounded-2xl px-4 py-3 text-sm leading-relaxed ${
          isUser
            ? 'bg-accent-primary text-white rounded-tr-sm'
            : 'bg-bg-secondary border border-border-primary rounded-tl-sm'
        }`}
      >
        <div className="whitespace-pre-wrap break-words" style={{ fontFamily: 'inherit' }}>
          {content}
        </div>
      </div>
    </div>
  )
}

function EmptyState() {
  const quickPrompts = [
    '检查一下磁盘空间',
    '创建一个每日巡检任务',
    '看看有哪些工具可用',
    '列出所有 Docker 容器',
  ]
  const { sendMessage } = useAppStore()

  return (
    <div className="flex flex-col items-center justify-center py-16 text-center">
      <div className="mb-5 flex h-16 w-16 items-center justify-center rounded-2xl bg-gradient-to-br from-accent-primary to-purple-500 text-white shadow-lg shadow-accent-primary/20">
        <Bot size={28} />
      </div>
      <h2 className="text-xl font-semibold mb-1.5">AI DevOps Agent</h2>
      <p className="text-sm text-text-secondary mb-7 max-w-md">
        你的智能运维助手。说人话就能帮你执行命令、管理任务、定时巡检。
      </p>
      <div className="grid grid-cols-2 gap-2.5 w-full max-w-lg">
        {quickPrompts.map((p) => (
          <button
            key={p}
            onClick={() => sendMessage(p)}
            className="rounded-xl border border-border-primary bg-bg-secondary px-4 py-3 text-left text-sm text-text-secondary hover:border-accent-primary/50 hover:bg-accent-soft hover:text-text-primary transition-all"
          >
            {p}
          </button>
        ))}
      </div>
    </div>
  )
}
