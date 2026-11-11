import { useEffect, useState } from 'react'
import {
  CheckCircle2,
  Clock,
  FileText,
  Loader2,
  PlayCircle,
  Plus,
  RefreshCw,
  Trash2,
  XCircle,
} from 'lucide-react'
import { useAppStore } from '../store/useAppStore'
import { cronApi } from '../api'
import Modal from '../components/Modal'
import Button from '../components/Button'
import { Input, Textarea } from '../components/Input'
import Badge from '../components/Badge'
import {
  SectionLabel,
  WorkspaceEmpty,
  WorkspacePage,
  WorkspacePanel,
} from '../components/Workspace'
import type { CronJob, CronLog } from '../types'

export default function Cron() {
  const { cronJobs, fetchCronJobs, createCronJob, deleteCronJob } = useAppStore()
  const [modalOpen, setModalOpen] = useState(false)
  const [logsOpen, setLogsOpen] = useState(false)
  const [logsJob, setLogsJob] = useState<CronJob | null>(null)
  const [logs, setLogs] = useState<CronLog[]>([])
  const [logsLoading, setLogsLoading] = useState(false)
  const [form, setForm] = useState({
    name: '',
    description: '',
    cron_expression: '0 9 * * *',
    message: '',
  })

  useEffect(() => {
    fetchCronJobs()
    const timer = setInterval(fetchCronJobs, 10_000)
    return () => clearInterval(timer)
  }, [fetchCronJobs])

  const handleCreate = () => {
    if (!form.name.trim() || !form.message.trim()) return
    createCronJob({ ...form, enabled: true })
    setForm({ name: '', description: '', cron_expression: '0 9 * * *', message: '' })
    setModalOpen(false)
  }

  const quickCron = [
    { label: '每分钟', expr: '* * * * *' },
    { label: '每小时', expr: '0 * * * *' },
    { label: '每天 9 点', expr: '0 9 * * *' },
    { label: '每周一', expr: '0 9 * * 1' },
  ]

  const openLogs = async (job: CronJob) => {
    setLogsJob(job)
    setLogsOpen(true)
    setLogsLoading(true)
    try {
      setLogs(await cronApi.logs(job.id))
    } catch {
      setLogs([])
    } finally {
      setLogsLoading(false)
    }
  }

  return (
    <>
      <WorkspacePage
        title="定时任务"
        description={`${cronJobs.length} 个 Agent 定时任务，按 Cron 表达式自动触发。`}
        actions={
          <>
            <Button variant="secondary" onClick={fetchCronJobs}>
              <RefreshCw size={12} />
              刷新
            </Button>
            <Button onClick={() => setModalOpen(true)}>
              <Plus size={12} />
              新建
            </Button>
          </>
        }
        wide
      >
        {cronJobs.length === 0 ? (
          <WorkspaceEmpty
            icon={<Clock size={17} />}
            title="还没有定时任务"
            description="创建巡检、日志清理或证书检查等周期性 Agent 任务。"
          />
        ) : (
          <WorkspacePanel>
            <div className="flex items-center justify-between border-b border-border-secondary px-4 py-3">
              <SectionLabel>任务列表</SectionLabel>
              <span className="text-[10px] text-text-tertiary">每 10 秒刷新</span>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[860px]">
                <thead>
                  <tr className="border-b border-border-primary bg-bg-secondary">
                    <Th>名称</Th>
                    <Th>Cron</Th>
                    <Th>消息</Th>
                    <Th>上次运行</Th>
                    <Th>状态</Th>
                    <Th>操作</Th>
                  </tr>
                </thead>
                <tbody>
                  {cronJobs.map((job) => (
                    <tr key={job.id} className="border-b border-border-secondary last:border-0 hover:bg-bg-hover/60">
                      <td className="px-4 py-3">
                        <div className="text-[12.5px] font-medium">{job.name}</div>
                        {job.description && (
                          <div className="mt-0.5 text-[10.5px] text-text-tertiary">{job.description}</div>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <code className="rounded border border-border-secondary bg-bg-secondary px-1.5 py-0.5 font-mono text-[10.5px]">
                          {job.cron_expression}
                        </code>
                      </td>
                      <td className="max-w-xs px-4 py-3">
                        <div className="truncate text-[11.5px] text-text-secondary">{job.message}</div>
                      </td>
                      <td className="px-4 py-3">
                        <div className="text-[10.5px] text-text-secondary">{formatRunTime(job.last_run_at)}</div>
                        {job.last_finished_at && (
                          <div className="mt-0.5 text-[10px] text-text-tertiary">
                            完成 {formatRunTime(job.last_finished_at)}
                          </div>
                        )}
                      </td>
                      <td className="px-4 py-3"><CronStatus job={job} /></td>
                      <td className="px-4 py-3">
                        <div className="flex justify-end gap-1">
                          <Button size="sm" variant="ghost" onClick={() => openLogs(job)} title="查看日志">
                            <FileText size={13} />
                          </Button>
                          <Button size="sm" variant="ghost" onClick={() => deleteCronJob(job.id)} title="删除">
                            <Trash2 size={13} className="text-status-error" />
                          </Button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </WorkspacePanel>
        )}
      </WorkspacePage>

      <Modal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        title="新建定时任务"
        footer={
          <>
            <Button variant="secondary" onClick={() => setModalOpen(false)}>取消</Button>
            <Button onClick={handleCreate} disabled={!form.name.trim() || !form.message.trim()}>创建</Button>
          </>
        }
      >
        <div className="space-y-4">
          <Input
            label="任务名称"
            placeholder="例如：每日巡检"
            value={form.name}
            onChange={(event) => setForm({ ...form, name: event.target.value })}
          />
          <Input
            label="任务描述"
            placeholder="可选"
            value={form.description}
            onChange={(event) => setForm({ ...form, description: event.target.value })}
          />
          <div>
            <SectionLabel>Cron 表达式</SectionLabel>
            <div className="mt-2">
              <Input
                placeholder="0 9 * * *"
                value={form.cron_expression}
                onChange={(event) => setForm({ ...form, cron_expression: event.target.value })}
              />
            </div>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {quickCron.map((item) => (
                <button
                  key={item.expr}
                  onClick={() => setForm({ ...form, cron_expression: item.expr })}
                  className="rounded-md border border-border-primary px-2 py-1 text-[10.5px] text-text-secondary hover:bg-bg-hover"
                >
                  {item.label}
                </button>
              ))}
            </div>
            <p className="mt-2 text-[10.5px] text-text-tertiary">格式：分 时 日 月 周</p>
          </div>
          <Textarea
            label="触发时发送的消息"
            placeholder="例如：执行每日巡检，检查磁盘、内存和服务状态"
            rows={3}
            value={form.message}
            onChange={(event) => setForm({ ...form, message: event.target.value })}
          />
        </div>
      </Modal>

      <Modal
        open={logsOpen}
        onClose={() => setLogsOpen(false)}
        title={`执行记录 · ${logsJob?.name || ''}`}
      >
        <div className="max-h-[65vh] space-y-3 overflow-y-auto">
          {logsLoading && (
            <div className="flex items-center justify-center py-10 text-text-secondary">
              <Loader2 size={16} className="mr-2 animate-spin" />
              加载中…
            </div>
          )}
          {!logsLoading && logs.length === 0 && (
            <p className="py-10 text-center text-[12px] text-text-tertiary">暂无执行记录。</p>
          )}
          {!logsLoading && logs.map((log) => (
            <div key={`${log.job_id}-${log.fired_at}`} className="rounded-lg border border-border-primary bg-bg-secondary p-3">
              <div className="mb-2 flex items-center justify-between gap-3">
                <span className="text-[10.5px] text-text-secondary">{formatRunTime(log.fired_at)}</span>
                <Badge variant={log.success ? 'success' : 'error'}>
                  {log.success ? '成功' : '失败'}
                </Badge>
              </div>
              <pre className="max-h-48 overflow-auto whitespace-pre-wrap rounded bg-bg-primary p-2 text-[10.5px] text-text-secondary">
                {log.error || log.output || '(无输出)'}
              </pre>
            </div>
          ))}
        </div>
      </Modal>
    </>
  )
}

function Th({ children }: { children: React.ReactNode }) {
  return (
    <th className="px-4 py-2.5 text-left text-[10px] font-medium uppercase tracking-[0.1em] text-text-tertiary">
      {children}
    </th>
  )
}

function formatRunTime(value?: string) {
  if (!value) return '尚未运行'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}

function CronStatus({ job }: { job: CronJob }) {
  if (!job.enabled) return <Badge><PlayCircle size={9} className="mr-1" />已停止</Badge>
  if (job.running) return <Badge variant="info"><Loader2 size={9} className="mr-1 animate-spin" />执行中</Badge>
  if (job.last_success === true) return <Badge variant="success"><CheckCircle2 size={9} className="mr-1" />成功</Badge>
  if (job.last_success === false) return <Badge variant="error"><XCircle size={9} className="mr-1" />失败</Badge>
  return <Badge variant="warning"><Clock size={9} className="mr-1" />等待运行</Badge>
}
