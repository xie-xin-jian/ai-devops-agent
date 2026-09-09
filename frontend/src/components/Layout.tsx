import { useAppStore } from '../store/useAppStore'
import Sidebar from './Sidebar'
import TopBar from './TopBar'
import Toast from './Toast'

export default function Layout({ children }: { children: React.ReactNode }) {
  const view = useAppStore((s) => s.view)

  const titles: Record<string, string> = {
    chat: '对话',
    tasks: '任务管理',
    cron: '定时任务',
    tools: '工具库',
    mcp: 'MCP 管理',
  }

  return (
    <div className="flex h-full w-full bg-bg-primary text-text-primary">
      <Sidebar />
      <div className="flex flex-1 flex-col overflow-hidden">
        <TopBar title={titles[view] || ''} />
        <main className="flex-1 overflow-hidden">{children}</main>
      </div>
      <Toast />
    </div>
  )
}
