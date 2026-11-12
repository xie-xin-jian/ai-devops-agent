import { useEffect, useState } from 'react'
import { Box, RefreshCw } from 'lucide-react'
import { sandboxApi } from '../api'
import Badge from '../components/Badge'
import Button from '../components/Button'
import {
  SectionLabel,
  WorkspaceEmpty,
  WorkspacePage,
  WorkspacePanel,
} from '../components/Workspace'

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
    const timer = setInterval(load, 10_000)
    return () => clearInterval(timer)
  }, [])

  return (
    <WorkspacePage
      title="工作区"
      description={`当前有 ${data.active.length} 个活动 Sandbox，Run 结束后会自动清理。`}
      actions={
        <Button variant="secondary" onClick={load} disabled={loading}>
          <RefreshCw size={12} className={loading ? 'animate-spin' : ''} />
          刷新
        </Button>
      }
      wide
    >
      {data.active.length === 0 ? (
        <WorkspaceEmpty
          icon={<Box size={17} />}
          title="当前没有活动工作区"
          description="Sandbox 只在 Run 执行期间存在，用于隔离文件类工具。"
        />
      ) : (
        <WorkspacePanel>
          <div className="flex items-center justify-between border-b border-border-secondary px-4 py-3">
            <SectionLabel>活动工作区</SectionLabel>
            <Badge variant="info">{data.active.length} 个</Badge>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px]">
              <thead>
                <tr className="border-b border-border-primary bg-bg-secondary">
                  <Th>Run</Th>
                  <Th>来源</Th>
                  <Th>工作区路径</Th>
                  <Th>状态</Th>
                  <Th>更新时间</Th>
                </tr>
              </thead>
              <tbody>
                {data.active.map((item) => (
                  <tr key={item.run_id} className="border-b border-border-secondary last:border-0">
                    <td className="px-4 py-3 font-mono text-[10.5px]">{item.run_id}</td>
                    <td className="px-4 py-3 text-[11px] text-text-secondary">{item.source || '-'}</td>
                    <td className="px-4 py-3">
                      <div className="max-w-md truncate font-mono text-[10.5px] text-text-secondary">
                        {item.workspace_host_path || '-'}
                      </div>
                    </td>
                    <td className="px-4 py-3"><Badge variant="info">{item.status}</Badge></td>
                    <td className="whitespace-nowrap px-4 py-3 text-[10.5px] text-text-tertiary">
                      {formatTime(item.updated_at || item.created_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </WorkspacePanel>
      )}
    </WorkspacePage>
  )
}

function Th({ children }: { children: React.ReactNode }) {
  return (
    <th className="px-4 py-2.5 text-left text-[10px] font-medium uppercase tracking-[0.1em] text-text-tertiary">
      {children}
    </th>
  )
}

function formatTime(value: number) {
  return value ? new Date(value * 1000).toLocaleString() : '-'
}
