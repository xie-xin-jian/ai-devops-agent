import { useState, useEffect } from 'react'
import { Plus, Check, Trash2, Play, Clock, AlertCircle, Hand } from 'lucide-react'
import { useAppStore } from '../store/useAppStore'
import Modal from '../components/Modal'
import Button from '../components/Button'
import { Input, Textarea } from '../components/Input'
import Badge from '../components/Badge'
import type { Task } from '../types'

const statusConfig = {
  pending: { label: '待处理', variant: 'default' as const, icon: Clock },
  in_progress: { label: '进行中', variant: 'info' as const, icon: Play },
  completed: { label: '已完成', variant: 'success' as const, icon: Check },
  blocked: { label: '阻塞', variant: 'warning' as const, icon: AlertCircle },
}

const priorityConfig = {
  low: { label: '低', variant: 'default' as const },
  medium: { label: '中', variant: 'info' as const },
  high: { label: '高', variant: 'error' as const },
}

export default function Tasks() {
  const { tasks, fetchTasks, createTask, claimTask, completeTask, deleteTask } = useAppStore()
  const [modalOpen, setModalOpen] = useState(false)
  const [completeId, setCompleteId] = useState<string | null>(null)
  const [completeResult, setCompleteResult] = useState('')

  useEffect(() => {
    fetchTasks()
  }, [fetchTasks])

  const [form, setForm] = useState({
    subject: '',
    description: '',
    priority: 'medium' as 'low' | 'medium' | 'high',
  })

  const handleCreate = () => {
    if (!form.subject.trim()) return
    createTask(form)
    setForm({ subject: '', description: '', priority: 'medium' })
    setModalOpen(false)
  }

  const handleComplete = () => {
    if (!completeId) return
    completeTask(completeId, completeResult || undefined)
    setCompleteId(null)
    setCompleteResult('')
  }

  return (
    <div className="h-full overflow-y-auto p-6">
      <div className="mx-auto max-w-5xl">
        {/* 头部 */}
        <div className="mb-6 flex items-center justify-between">
          <div>
            <p className="text-sm text-text-secondary">
              共 {tasks.length} 个任务 · {tasks.filter(t => t.status === 'completed').length} 已完成
            </p>
          </div>
          <Button onClick={() => setModalOpen(true)}>
            <Plus size={16} />
            新建任务
          </Button>
        </div>

        {/* 任务列表 */}
        {tasks.length === 0 ? (
          <div className="rounded-xl border border-dashed border-border-primary py-20 text-center">
            <Hand size={36} className="mx-auto mb-3 text-text-tertiary" />
            <p className="text-text-secondary mb-1">还没有任务</p>
            <p className="text-sm text-text-tertiary">点击右上角创建第一个任务</p>
          </div>
        ) : (
          <div className="space-y-3">
            {tasks.map((task) => (
              <TaskCard
                key={task.id}
                task={task}
                onClaim={() => claimTask(task.id)}
                onComplete={() => setCompleteId(task.id)}
                onDelete={() => deleteTask(task.id)}
              />
            ))}
          </div>
        )}
      </div>

      {/* 新建任务弹窗 */}
      <Modal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        title="新建任务"
        footer={
          <>
            <Button variant="secondary" onClick={() => setModalOpen(false)}>
              取消
            </Button>
            <Button onClick={handleCreate} disabled={!form.subject.trim()}>
              创建
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <Input
            label="任务标题"
            placeholder="例如：每日服务器巡检"
            value={form.subject}
            onChange={(e) => setForm({ ...form, subject: e.target.value })}
          />
          <Textarea
            label="任务描述"
            placeholder="详细描述任务内容..."
            rows={4}
            value={form.description}
            onChange={(e) => setForm({ ...form, description: e.target.value })}
          />
          <div>
            <label className="mb-1.5 block text-xs font-medium text-text-secondary">
              优先级
            </label>
            <div className="flex gap-2">
              {(['low', 'medium', 'high'] as const).map((p) => (
                <button
                  key={p}
                  onClick={() => setForm({ ...form, priority: p })}
                  className={`flex-1 rounded-lg border px-3 py-2 text-sm transition-colors ${
                    form.priority === p
                      ? 'border-accent-primary bg-accent-soft text-accent-primary'
                      : 'border-border-primary text-text-secondary hover:bg-bg-hover'
                  }`}
                >
                  {priorityConfig[p].label}优先级
                </button>
              ))}
            </div>
          </div>
        </div>
      </Modal>

      {/* 完成任务弹窗 */}
      <Modal
        open={!!completeId}
        onClose={() => setCompleteId(null)}
        title="完成任务"
        footer={
          <>
            <Button variant="secondary" onClick={() => setCompleteId(null)}>
              取消
            </Button>
            <Button onClick={handleComplete}>确认完成</Button>
          </>
        }
      >
        <Textarea
          label="完成结果（可选）"
          placeholder="记录任务完成情况..."
          rows={4}
          value={completeResult}
          onChange={(e) => setCompleteResult(e.target.value)}
        />
      </Modal>
    </div>
  )
}

function TaskCard({
  task,
  onClaim,
  onComplete,
  onDelete,
}: {
  task: Task
  onClaim: () => void
  onComplete: () => void
  onDelete: () => void
}) {
  const status = statusConfig[task.status]
  const priority = priorityConfig[task.priority]
  const StatusIcon = status.icon

  return (
    <div className="rounded-xl border border-border-primary bg-bg-secondary p-4 transition-all hover:border-border-secondary hover:shadow-sm">
      <div className="flex items-start justify-between gap-4">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2.5 mb-1.5">
            <StatusIcon size={16} className={
              task.status === 'completed' ? 'text-status-success' :
              task.status === 'in_progress' ? 'text-status-info' :
              task.status === 'blocked' ? 'text-status-warning' :
              'text-text-tertiary'
            } />
            <h3 className="font-medium truncate">{task.subject}</h3>
            <Badge variant={status.variant}>{status.label}</Badge>
            <Badge variant={priority.variant}>{priority.label}优先级</Badge>
          </div>
          {task.description && (
            <p className="text-sm text-text-secondary line-clamp-2 mb-2 ml-6">
              {task.description}
            </p>
          )}
          <div className="text-xs text-text-tertiary ml-6">
            {task.created_at
              ? `创建于 ${new Date(task.created_at * 1000).toLocaleString()}`
              : '刚创建'}
          </div>
        </div>
        <div className="flex items-center gap-1 shrink-0">
          {task.status === 'pending' && (
            <Button size="sm" variant="ghost" onClick={onClaim} title="认领">
              <Play size={14} />
            </Button>
          )}
          {task.status === 'in_progress' && (
            <Button size="sm" variant="ghost" onClick={onComplete} title="完成">
              <Check size={14} />
            </Button>
          )}
          <Button size="sm" variant="ghost" onClick={onDelete} title="删除">
            <Trash2 size={14} className="text-status-error" />
          </Button>
        </div>
      </div>
    </div>
  )
}
