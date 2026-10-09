import { useEffect, useState } from 'react'
import { Box, RefreshCw, type LucideIcon } from 'lucide-react'
import { sandboxApi } from '../api'
import Badge from '../components/Badge'
import Button from '../components/Button'

export default function Sandboxes() {
  const [data, setData] = useState<{ active: any[] }>({ active: [] })
  const [loading, setLoading] = useState(false)

  const load = async () => {
    setLoading(true)
    try {
      setData(await sandboxApi.list())
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
    const timer = setInterval(load, 10000)
    return () => clearInterval(timer)
  }, [])

  return (
    <div className="h-full overflow-y-auto p-6">
      <div className="mx-auto max-w-6xl">
        <div className="mb-5 flex items-center justify-between">
          <p className="text-sm text-text-secondary">
            活动容器 {data.active.length}
          </p>
          <Button variant="secondary" onClick={load} disabled={loading}>
            <RefreshCw size={16} className={loading ? 'animate-spin' : ''} />
            刷新
          </Button>
        </div>

        <Section
          title="活动 Sandbox"
          icon={Box}
          empty="当前没有活动容器"
          items={data.active}
          render={(item) => (
            <SandboxRow
              key={item.run_id}
              item={item}
            />
          )}
        />
      </div>
    </div>
  )
}

function Section({
  title,
  icon: Icon,
  items,
  empty,
  render,
}: {
  title: string
  icon: LucideIcon
  items: any[]
  empty: string
  render: (item: any) => React.ReactNode
}) {
  return (
    <section>
      <div className="mb-3 flex items-center gap-2">
        <Icon size={17} className="text-text-secondary" />
        <h2 className="text-sm font-medium">{title}</h2>
      </div>
      {items.length === 0 ? (
        <div className="rounded-xl border border-dashed border-border-primary py-12 text-center text-sm text-text-tertiary">
          {empty}
        </div>
      ) : (
        <div className="overflow-hidden rounded-xl border border-border-primary">
          <table className="w-full">
            <thead>
              <tr className="border-b border-border-primary bg-bg-tertiary/50">
                <Th>Run</Th>
                <Th>来源</Th>
                <Th>工作区</Th>
                <Th>状态</Th>
                <Th>创建/更新时间</Th>
              </tr>
            </thead>
            <tbody>{items.map(render)}</tbody>
          </table>
        </div>
      )}
    </section>
  )
}

function SandboxRow({ item }: { item: any }) {
  return (
    <tr className="border-b border-border-secondary last:border-0">
      <td className="px-4 py-3 font-mono text-xs">{item.run_id}</td>
      <td className="px-4 py-3 text-xs text-text-secondary">{item.source || '-'}</td>
      <td className="px-4 py-3">
        <div className="max-w-md truncate font-mono text-[11px] text-text-secondary">
          {item.workspace_host_path || item.workspace_container_path || '-'}
        </div>
      </td>
      <td className="px-4 py-3">
        <Badge variant="info">
          {item.status}
        </Badge>
      </td>
      <td className="px-4 py-3 text-xs text-text-tertiary">
        {formatTime(item.updated_at || item.created_at)}
      </td>
    </tr>
  )
}

function Th({ children }: { children: React.ReactNode }) {
  return (
    <th className="px-4 py-3 text-left text-xs font-medium text-text-secondary">
      {children}
    </th>
  )
}

function formatTime(value: number) {
  return value ? new Date(value * 1000).toLocaleString() : '-'
}
