import { useState, useEffect } from 'react'
import { Plus, Trash2, Clock, PlayCircle } from 'lucide-react'
import { useAppStore } from '../store/useAppStore'
import Modal from '../components/Modal'
import Button from '../components/Button'
import { Input, Textarea } from '../components/Input'
import Badge from '../components/Badge'

export default function Cron() {
  const { cronJobs, fetchCronJobs, createCronJob, deleteCronJob } = useAppStore()
  const [modalOpen, setModalOpen] = useState(false)

  useEffect(() => {
    fetchCronJobs()
  }, [fetchCronJobs])

  const [form, setForm] = useState({
    name: '',
    description: '',
    cron_expression: '0 9 * * *',
    message: '',
  })

  const handleCreate = () => {
    if (!form.name.trim() || !form.message.trim()) return
    createCronJob({
      ...form,
      enabled: true,
    })
    setForm({ name: '', description: '', cron_expression: '0 9 * * *', message: '' })
    setModalOpen(false)
  }

  const quickCron = [
    { label: '每分钟', expr: '* * * * *' },
    { label: '每小时', expr: '0 * * * *' },
    { label: '每天 9 点', expr: '0 9 * * *' },
    { label: '每周一', expr: '0 9 * * 1' },
  ]

  return (
    <div className="h-full overflow-y-auto p-6">
      <div className="mx-auto max-w-5xl">
        {/* 头部 */}
        <div className="mb-6 flex items-center justify-between">
          <div>
            <p className="text-sm text-text-secondary">
              共 {cronJobs.length} 个定时任务
            </p>
          </div>
          <Button onClick={() => setModalOpen(true)}>
            <Plus size={16} />
            新建定时任务
          </Button>
        </div>

        {/* 列表 */}
        {cronJobs.length === 0 ? (
          <div className="rounded-xl border border-dashed border-border-primary py-20 text-center">
            <Clock size={36} className="mx-auto mb-3 text-text-tertiary" />
            <p className="text-text-secondary mb-1">还没有定时任务</p>
            <p className="text-sm text-text-tertiary">创建第一个定时巡检任务吧</p>
          </div>
        ) : (
          <div className="overflow-hidden rounded-xl border border-border-primary">
            <table className="w-full">
              <thead>
                <tr className="border-b border-border-primary bg-bg-tertiary/50">
                  <th className="px-4 py-3 text-left text-xs font-medium text-text-secondary">名称</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-text-secondary">Cron 表达式</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-text-secondary">消息</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-text-secondary">状态</th>
                  <th className="px-4 py-3 text-right text-xs font-medium text-text-secondary">操作</th>
                </tr>
              </thead>
              <tbody>
                {cronJobs.map((job) => (
                  <tr key={job.id} className="border-b border-border-secondary last:border-0 hover:bg-bg-hover/50">
                    <td className="px-4 py-3">
                      <div className="font-medium text-sm">{job.name}</div>
                      {job.description && (
                        <div className="text-xs text-text-tertiary mt-0.5">{job.description}</div>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <code className="text-xs bg-bg-tertiary px-2 py-1 rounded">{job.cron_expression}</code>
                    </td>
                    <td className="px-4 py-3 text-sm text-text-secondary max-w-xs truncate">
                      {job.message}
                    </td>
                    <td className="px-4 py-3">
                      <Badge variant={job.enabled ? 'success' : 'default'}>
                        <PlayCircle size={10} className="mr-1" />
                        {job.enabled ? '运行中' : '已停止'}
                      </Badge>
                    </td>
                    <td className="px-4 py-3 text-right">
                      <Button size="sm" variant="ghost" onClick={() => deleteCronJob(job.id)}>
                        <Trash2 size={14} className="text-status-error" />
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* 新建弹窗 */}
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
            onChange={(e) => setForm({ ...form, name: e.target.value })}
          />
          <Input
            label="任务描述"
            placeholder="可选"
            value={form.description}
            onChange={(e) => setForm({ ...form, description: e.target.value })}
          />
          <div>
            <label className="mb-1.5 block text-xs font-medium text-text-secondary">
              Cron 表达式
            </label>
            <Input
              placeholder="0 9 * * *"
              value={form.cron_expression}
              onChange={(e) => setForm({ ...form, cron_expression: e.target.value })}
            />
            <div className="mt-2 flex flex-wrap gap-1.5">
              {quickCron.map((q) => (
                <button
                  key={q.expr}
                  onClick={() => setForm({ ...form, cron_expression: q.expr })}
                  className="rounded-md border border-border-primary px-2 py-1 text-xs text-text-secondary hover:border-accent-primary/50 hover:text-accent-primary transition-colors"
                >
                  {q.label}
                </button>
              ))}
            </div>
            <p className="mt-2 text-[11px] text-text-tertiary">
              格式：分 时 日 月 周（例：0 9 * * * = 每天 9 点）
            </p>
          </div>
          <Textarea
            label="触发时发送的消息"
            placeholder="例如：执行每日巡检，检查磁盘、内存、服务状态"
            rows={3}
            value={form.message}
            onChange={(e) => setForm({ ...form, message: e.target.value })}
          />
        </div>
      </Modal>
    </div>
  )
}
