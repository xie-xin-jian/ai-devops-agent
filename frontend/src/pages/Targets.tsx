import { useEffect, useState } from 'react'
import {
  ArrowLeft,
  Check,
  Folder,
  FolderOpen,
  Pencil,
  Plus,
  RefreshCw,
  Server,
  Trash2,
  X,
} from 'lucide-react'
import { targetApi } from '../api'
import Badge from '../components/Badge'
import Button from '../components/Button'
import { useAppStore } from '../store/useAppStore'
import type { Target, TargetBrowserResult } from '../types'

type TargetForm = {
  id?: string
  name: string
  root: string
  description: string
  service: string
  health_url: string
  deploy_command: string
  restart_command: string
  log_path: string
}

const emptyForm = (): TargetForm => ({
  name: '',
  root: '',
  description: '',
  service: '',
  health_url: '',
  deploy_command: '',
  restart_command: '',
  log_path: '',
})

export default function Targets() {
  const {
    targets,
    activeTargetId,
    fetchTargets,
    createTarget,
    updateTarget,
    activateTarget,
    deleteTarget,
    showToast,
  } = useAppStore()
  const [loading, setLoading] = useState(false)
  const [busyId, setBusyId] = useState('')
  const [form, setForm] = useState<TargetForm | null>(null)
  const [browserOpen, setBrowserOpen] = useState(false)

  const load = async () => {
    setLoading(true)
    try {
      await fetchTargets()
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  const beginCreate = () => setForm(emptyForm())

  const beginEdit = (target: Target) => {
    setForm({
      id: target.id,
      name: target.name,
      root: target.root,
      description: target.description,
      service: target.service,
      health_url: target.health_url,
      deploy_command: target.deploy_command,
      restart_command: target.restart_command,
      log_path: target.log_path,
    })
  }

  const save = async () => {
    if (!form?.root) {
      showToast('error', '请先选择项目目录')
      return
    }
    setBusyId(form.id || 'new')
    try {
      const target = form.id
        ? await updateTarget(form.id, form)
        : await createTarget(form)
      await activateTarget(target.id)
      setForm(null)
      showToast('success', `已切换到项目：${target.name}`)
    } catch (error: any) {
      showToast('error', error.message || '保存项目配置失败')
    } finally {
      setBusyId('')
    }
  }

  const remove = async (target: Target) => {
    if (!window.confirm(`确认删除项目配置“${target.name}”？`)) return
    setBusyId(target.id)
    try {
      await deleteTarget(target.id)
      showToast('success', '项目配置已删除')
    } catch (error: any) {
      showToast('error', error.message || '删除失败')
    } finally {
      setBusyId('')
    }
  }

  return (
    <div className="h-full overflow-y-auto p-6">
      <div className="mx-auto max-w-6xl">
        <div className="mb-5 flex items-center justify-between">
          <div>
            <h2 className="text-lg font-semibold">运维目标</h2>
            <p className="mt-1 text-sm text-text-secondary">
              选择服务器上的项目目录，Agent 的工具将严格限制在该目录内。
            </p>
          </div>
          <div className="flex gap-2">
            <Button variant="secondary" onClick={load} disabled={loading}>
              <RefreshCw size={16} className={loading ? 'animate-spin' : ''} />
              刷新
            </Button>
            <Button onClick={beginCreate}>
              <Plus size={16} />
              添加项目
            </Button>
          </div>
        </div>

        {targets.length === 0 ? (
          <div className="rounded-xl border border-dashed border-border-primary py-20 text-center">
            <Server size={36} className="mx-auto mb-3 text-text-tertiary" />
            <p className="text-sm text-text-secondary">还没有配置运维项目</p>
            <Button className="mt-4" onClick={beginCreate}>
              <Plus size={16} />
              选择项目目录
            </Button>
          </div>
        ) : (
          <div className="grid gap-3 lg:grid-cols-2">
            {targets.map((target) => {
              const active = target.id === activeTargetId
              return (
                <div
                  key={target.id}
                  className={`rounded-xl border bg-bg-secondary p-4 ${
                    active ? 'border-accent-primary' : 'border-border-primary'
                  }`}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="mb-2 flex items-center gap-2">
                        <FolderOpen size={17} className="text-accent-primary" />
                        <h3 className="font-medium">{target.name}</h3>
                        {active && <Badge variant="success">当前项目</Badge>}
                      </div>
                      <div className="space-y-1 text-xs text-text-secondary">
                        <div className="break-all font-mono">{target.root}</div>
                        <div>
                          Service: {target.service || '-'}
                          {' · '}
                          Health: {target.health_url || '-'}
                        </div>
                      </div>
                    </div>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => beginEdit(target)}
                      title="编辑项目配置"
                    >
                      <Pencil size={14} />
                    </Button>
                  </div>

                  <div className="mt-4 flex gap-2">
                    <Button
                      size="sm"
                      variant={active ? 'secondary' : 'primary'}
                      disabled={active || busyId === target.id}
                      onClick={() => activateTarget(target.id)}
                    >
                      <Check size={14} />
                      {active ? '已选择' : '设为当前项目'}
                    </Button>
                    <Button
                      size="sm"
                      variant="danger"
                      disabled={busyId === target.id}
                      onClick={() => remove(target)}
                    >
                      <Trash2 size={14} />
                      删除
                    </Button>
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>

      {form && (
        <TargetFormPanel
          form={form}
          busy={busyId === (form.id || 'new')}
          onChange={setForm}
          onClose={() => setForm(null)}
          onBrowse={() => setBrowserOpen(true)}
          onSave={save}
        />
      )}

      {browserOpen && form && (
        <DirectoryBrowser
          initialPath={form.root}
          onClose={() => setBrowserOpen(false)}
          onSelect={(path) => {
            setForm((current) => current ? {
              ...current,
              root: path,
              name: current.name || path.split('/').filter(Boolean).pop() || path,
            } : current)
            setBrowserOpen(false)
          }}
        />
      )}
    </div>
  )
}

function TargetFormPanel({
  form,
  busy,
  onChange,
  onClose,
  onBrowse,
  onSave,
}: {
  form: TargetForm
  busy: boolean
  onChange: (form: TargetForm) => void
  onClose: () => void
  onBrowse: () => void
  onSave: () => void
}) {
  const set = (key: keyof TargetForm, value: string) => {
    onChange({ ...form, [key]: value })
  }

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/35 p-4">
      <div className="w-full max-w-2xl rounded-xl border border-border-primary bg-bg-primary shadow-xl">
        <div className="flex items-center justify-between border-b border-border-secondary px-5 py-4">
          <div>
            <h3 className="font-semibold">{form.id ? '编辑项目' : '添加运维项目'}</h3>
            <p className="mt-1 text-xs text-text-tertiary">
              只有选择目录是必填项，其他配置可以以后补充。
            </p>
          </div>
          <Button variant="ghost" size="sm" onClick={onClose}>
            <X size={16} />
          </Button>
        </div>

        <div className="grid gap-4 p-5 md:grid-cols-2">
          <Field label="项目目录" className="md:col-span-2">
            <div className="flex gap-2">
              <input
                value={form.root}
                readOnly
                placeholder="尚未选择服务器目录"
                className="min-w-0 flex-1 rounded-lg border border-border-primary bg-bg-secondary px-3 py-2 font-mono text-xs"
              />
              <Button variant="secondary" onClick={onBrowse}>
                <Folder size={15} />
                浏览服务器
              </Button>
            </div>
          </Field>
          <Field label="项目名称">
            <input value={form.name} onChange={(e) => set('name', e.target.value)} className={inputClass} />
          </Field>
          <Field label="服务名">
            <input value={form.service} onChange={(e) => set('service', e.target.value)} placeholder="trip-planner" className={inputClass} />
          </Field>
          <Field label="健康检查 URL" className="md:col-span-2">
            <input value={form.health_url} onChange={(e) => set('health_url', e.target.value)} placeholder="http://127.0.0.1:8001/health" className={inputClass} />
          </Field>
          <Field label="日志路径">
            <input value={form.log_path} onChange={(e) => set('log_path', e.target.value)} placeholder="logs/app.log" className={inputClass} />
          </Field>
          <Field label="部署命令">
            <input value={form.deploy_command} onChange={(e) => set('deploy_command', e.target.value)} placeholder="./scripts/deploy.sh" className={inputClass} />
          </Field>
          <Field label="重启命令" className="md:col-span-2">
            <input value={form.restart_command} onChange={(e) => set('restart_command', e.target.value)} placeholder="留空时使用 systemctl restart <service>" className={inputClass} />
          </Field>
          <Field label="项目说明" className="md:col-span-2">
            <textarea value={form.description} onChange={(e) => set('description', e.target.value)} rows={2} className={inputClass} />
          </Field>
        </div>

        <div className="flex justify-end gap-2 border-t border-border-secondary px-5 py-4">
          <Button variant="secondary" onClick={onClose}>取消</Button>
          <Button onClick={onSave} disabled={busy || !form.root}>
            <Check size={15} />
            {busy ? '保存中...' : '保存并设为当前项目'}
          </Button>
        </div>
      </div>
    </div>
  )
}

function DirectoryBrowser({
  initialPath,
  onClose,
  onSelect,
}: {
  initialPath: string
  onClose: () => void
  onSelect: (path: string) => void
}) {
  const [path, setPath] = useState(initialPath)
  const [data, setData] = useState<TargetBrowserResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const navigate = async (nextPath: string) => {
    setLoading(true)
    setError('')
    try {
      const result = await targetApi.browse(nextPath)
      setData(result)
      setPath(result.current)
    } catch (e: any) {
      setError(e.message || '无法浏览目录')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    navigate(path)
  }, [])

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="flex h-[min(680px,90vh)] w-full max-w-3xl flex-col rounded-xl border border-border-primary bg-bg-primary shadow-xl">
        <div className="flex items-center justify-between border-b border-border-secondary px-5 py-4">
          <div className="min-w-0">
            <h3 className="font-semibold">选择服务器项目目录</h3>
            <div className="mt-1 truncate font-mono text-xs text-text-tertiary">
              {path || '允许的根目录'}
            </div>
          </div>
          <Button variant="ghost" size="sm" onClick={onClose}>
            <X size={16} />
          </Button>
        </div>

        <div className="flex min-h-0 flex-1 flex-col">
          <div className="flex items-center gap-2 border-b border-border-secondary px-4 py-2">
            <Button
              variant="secondary"
              size="sm"
              disabled={!data?.parent || loading}
              onClick={() => navigate(data?.parent || '')}
            >
              <ArrowLeft size={14} />
              上级
            </Button>
            <span className="truncate font-mono text-xs text-text-secondary">
              {data?.current || '根目录'}
            </span>
          </div>

          {error && (
            <div className="border-b border-status-error/20 bg-status-error/10 px-4 py-2 text-xs text-status-error">
              {error}
            </div>
          )}

          <div className="min-h-0 flex-1 overflow-y-auto p-2">
            {data?.entries.map((entry) => (
              <button
                key={entry.path}
                onClick={() => navigate(entry.path)}
                className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left text-sm hover:bg-bg-hover"
              >
                <Folder size={17} className="shrink-0 text-accent-primary" />
                <span className="min-w-0 flex-1 truncate">{entry.name}</span>
              </button>
            ))}
            {!loading && !data?.entries.length && (
              <div className="px-4 py-12 text-center text-sm text-text-tertiary">
                {data?.message || '当前目录下没有子目录'}
              </div>
            )}
          </div>
        </div>

        <div className="flex justify-end gap-2 border-t border-border-secondary px-5 py-4">
          <Button variant="secondary" onClick={onClose}>取消</Button>
          <Button disabled={!data?.current || !data.selectable || loading} onClick={() => onSelect(data!.current)}>
            <Check size={15} />
            选择当前目录
          </Button>
        </div>
      </div>
    </div>
  )
}

function Field({
  label,
  className = '',
  children,
}: {
  label: string
  className?: string
  children: React.ReactNode
}) {
  return (
    <label className={className}>
      <div className="mb-1.5 text-xs font-medium text-text-secondary">{label}</div>
      {children}
    </label>
  )
}

const inputClass = 'w-full rounded-lg border border-border-primary bg-bg-secondary px-3 py-2 text-sm outline-none focus:border-accent-primary'
