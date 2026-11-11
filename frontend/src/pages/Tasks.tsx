import { useEffect, useState } from 'react'
import {
  AlertCircle,
  Check,
  Clock,
  Hand,
  Play,
  Plus,
  Trash2,
} from 'lucide-react'
import { useAppStore } from '../store/useAppStore'
import Modal from '../components/Modal'
import Button from '../components/Button'
import { Input, Textarea } from '../components/Input'
import Badge from '../components/Badge'
import {
  SectionLabel,
  SplitView,
  WorkspaceEmpty,
  WorkspacePage,
  WorkspacePanel,
} from '../components/Workspace'
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
  const [selectedId, setSelectedId] = useState('')
  const [form, setForm] = useState({
    subject: '',
    description: '',
    priority: 'medium' as 'low' | 'medium' | 'high',
  })

  useEffect(() => {
    fetchTasks()
  }, [fetchTasks])

  const selected = tasks.find((task) => task.id === selectedId) || tasks[0]
  const activeCount = tasks.filter((task) => task.status !== 'completed').length

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
    <>
      <WorkspacePage
        title="任务"
        description={`${activeCount} 个待办 · ${tasks.length - activeCount} 个已完成`}
        actions={
          <Button onClick={() => setModalOpen(true)}>
            <Plus size={13} />
            新建任务
          </Button>
        }
        wide
      >
        {tasks.length === 0 ? (
          <WorkspaceEmpty
            icon={<Hand size={17} />}
            title="还没有任务"
            description="创建一个任务，让计划、依赖和执行结果在会话之间保持可见。"
          />
        ) : (
          <SplitView
            asideWidth="380px"
            aside={<TaskDetail task={selected} onClaim={claimTask} onComplete={setCompleteId} onDelete={deleteTask} />}
          >
            <WorkspacePanel>
              <div className="flex items-center justify-between border-b border-border-secondary px-4 py-3">
                <SectionLabel>任务列表</SectionLabel>
                <span className="text-[10px] text-text-tertiary">{tasks.length} 条</span>
              </div>
              <div>
                {tasks.map((task) => (
                  <TaskRow
                    key={task.id}
                    task={task}
                    active={(selected?.id || '') === task.id}
                    onSelect={() => setSelectedId(task.id)}
                  />
                ))}
              </div>
            </WorkspacePanel>
          </SplitView>
        )}
      </WorkspacePage>

      <Modal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        title="新建任务"
        footer={
          <>
            <Button variant="secondary" onClick={() => setModalOpen(false)}>取消</Button>
            <Button onClick={handleCreate} disabled={!form.subject.trim()}>创建</Button>
          </>
        }
      >
        <div className="space-y-4">
          <Input
            label="任务标题"
            placeholder="例如：每日服务器巡检"
            value={form.subject}
            onChange={(event) => setForm({ ...form, subject: event.target.value })}
          />
          <Textarea
            label="任务描述"
            placeholder="说明目标、范围或验证方式"
            rows={4}
            value={form.description}
            onChange={(event) => setForm({ ...form, description: event.target.value })}
          />
          <div>
            <SectionLabel>优先级</SectionLabel>
            <div className="mt-2 flex gap-2">
              {(['low', 'medium', 'high'] as const).map((priority) => (
                <button
                  key={priority}
                  onClick={() => setForm({ ...form, priority })}
                  className={`flex-1 rounded-lg border px-3 py-2 text-[12px] transition-colors ${
                    form.priority === priority
                      ? 'border-text-tertiary bg-bg-tertiary text-text-primary'
                      : 'border-border-primary text-text-secondary hover:bg-bg-hover'
                  }`}
                >
                  {priorityConfig[priority].label}优先级
                </button>
              ))}
            </div>
          </div>
        </div>
      </Modal>

      <Modal
        open={!!completeId}
        onClose={() => setCompleteId(null)}
        title="完成任务"
        footer={
          <>
            <Button variant="secondary" onClick={() => setCompleteId(null)}>取消</Button>
            <Button onClick={handleComplete}>确认完成</Button>
          </>
        }
      >
        <Textarea
          label="完成结果（可选）"
          placeholder="记录关键结果或证据"
          rows={4}
          value={completeResult}
          onChange={(event) => setCompleteResult(event.target.value)}
        />
      </Modal>
    </>
  )
}

function TaskRow({
  task,
  active,
  onSelect,
}: {
  task: Task
  active: boolean
  onSelect: () => void
}) {
  const status = statusConfig[task.status]
  const StatusIcon = status.icon
  return (
    <button
      onClick={onSelect}
      className={`flex w-full items-start gap-3 border-b border-border-secondary px-4 py-3 text-left transition-colors last:border-0 ${
        active ? 'bg-bg-active' : 'hover:bg-bg-hover'
      }`}
    >
      <StatusIcon
        size={14}
        className={`mt-0.5 shrink-0 ${
          task.status === 'completed'
            ? 'text-status-success'
            : task.status === 'in_progress'
              ? 'text-status-info'
              : task.status === 'blocked'
                ? 'text-status-warning'
                : 'text-text-tertiary'
        }`}
      />
      <div className="min-w-0 flex-1">
        <div className="truncate text-[13px] font-medium text-text-primary">{task.subject}</div>
        <div className="mt-1 flex items-center gap-2 text-[10.5px] text-text-tertiary">
          <span>{status.label}</span>
          <span>·</span>
          <span>{priorityConfig[task.priority].label}优先级</span>
          {task.owner && <><span>·</span><span>{task.owner}</span></>}
        </div>
      </div>
    </button>
  )
}

function TaskDetail({
  task,
  onClaim,
  onComplete,
  onDelete,
}: {
  task?: Task
  onClaim: (id: string) => Promise<void>
  onComplete: (id: string) => void
  onDelete: (id: string) => Promise<void>
}) {
  if (!task) {
    return (
      <WorkspacePanel padded className="min-h-[420px]">
        <WorkspaceEmpty icon={<Hand size={17} />} title="选择一条任务" />
      </WorkspacePanel>
    )
  }

  const status = statusConfig[task.status]
  const priority = priorityConfig[task.priority]
  return (
    <WorkspacePanel padded className="min-h-[420px]">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <SectionLabel>任务详情</SectionLabel>
          <h2 className="mt-2 text-[16px] font-medium leading-6 tracking-[-0.015em]">
            {task.subject}
          </h2>
        </div>
        <div className="flex shrink-0 gap-1">
          {task.status === 'pending' && (
            <Button size="sm" variant="secondary" onClick={() => onClaim(task.id)}>
              <Play size={12} />
              认领
            </Button>
          )}
          {task.status === 'in_progress' && (
            <Button size="sm" onClick={() => onComplete(task.id)}>
              <Check size={12} />
              完成
            </Button>
          )}
          <Button size="sm" variant="ghost" onClick={() => onDelete(task.id)} title="删除任务">
            <Trash2 size={13} className="text-status-error" />
          </Button>
        </div>
      </div>

      <div className="mt-4 flex flex-wrap gap-2">
        <Badge variant={status.variant}>{status.label}</Badge>
        <Badge variant={priority.variant}>{priority.label}优先级</Badge>
        {task.blockedBy?.length ? <Badge variant="warning">阻塞中</Badge> : null}
      </div>

      <div className="mt-5 space-y-4 text-[12px]">
        <div>
          <SectionLabel>描述</SectionLabel>
          <p className="mt-2 whitespace-pre-wrap leading-6 text-text-secondary">
            {task.description || '未填写任务描述。'}
          </p>
        </div>
        {!!task.blockedBy?.length && (
          <div>
            <SectionLabel>依赖</SectionLabel>
            <div className="mt-2 font-mono text-[11px] text-text-secondary">{task.blockedBy.join(', ')}</div>
          </div>
        )}
        <div className="grid grid-cols-2 gap-3 border-t border-border-secondary pt-4 text-[11px]">
          <Meta label="任务 ID" value={task.id} mono />
          <Meta label="Owner" value={task.owner || '-'} />
          <Meta label="Run" value={task.run_id || '-'} mono />
          <Meta label="创建时间" value={formatTime(task.created_at)} />
        </div>
        {task.result && (
          <div>
            <SectionLabel>完成结果</SectionLabel>
            <div className="mt-2 whitespace-pre-wrap rounded-lg bg-bg-secondary p-3 leading-6 text-text-secondary">
              {task.result}
            </div>
          </div>
        )}
      </div>
    </WorkspacePanel>
  )
}

function Meta({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="min-w-0">
      <div className="text-text-tertiary">{label}</div>
      <div className={`mt-1 truncate text-text-secondary ${mono ? 'font-mono text-[10.5px]' : ''}`} title={value}>
        {value}
      </div>
    </div>
  )
}

function formatTime(value: number) {
  return value ? new Date(value * 1000).toLocaleString() : '-'
}
