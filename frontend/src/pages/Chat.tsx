import { useState, useRef, useEffect } from 'react'
import { Send, Bot, User, Loader2 } from 'lucide-react'
import { useAppStore } from '../store/useAppStore'

export default function Chat() {
  const { messages, isLoading, sendMessage } = useAppStore()
  const [input, setInput] = useState('')
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [messages, isLoading])

  const handleSend = () => {
    if (!input.trim() || isLoading) return
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

          {isLoading && (
            <div className="flex items-start gap-3">
              <div className="flex h-8 w-8 items-center justify-center rounded-full bg-accent-primary/15 text-accent-primary shrink-0">
                <Bot size={16} />
              </div>
              <div className="flex items-center gap-2 rounded-xl bg-bg-secondary px-4 py-3 text-text-secondary">
                <Loader2 size={16} className="animate-spin" />
                <span className="text-sm">思考中...</span>
              </div>
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
              placeholder="输入消息，回车发送，Shift+Enter 换行..."
              className="flex-1 resize-none bg-transparent px-2 py-2 text-sm text-text-primary placeholder:text-text-tertiary focus:outline-none"
              rows={1}
              style={{ maxHeight: '160px', minHeight: '40px' }}
            />
            <button
              onClick={handleSend}
              disabled={isLoading || !input.trim()}
              className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-accent-primary text-white hover:bg-accent-hover disabled:opacity-40 disabled:cursor-not-allowed transition-all"
            >
              <Send size={16} />
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
