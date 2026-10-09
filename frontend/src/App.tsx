import { useEffect } from 'react'
import Layout from './components/Layout'
import Chat from './pages/Chat'
import Tasks from './pages/Tasks'
import Cron from './pages/Cron'
import Tools from './pages/Tools'
import MCP from './pages/MCP'
import Skills from './pages/Skills'
import PendingActions from './pages/PendingActions'
import Audit from './pages/Audit'
import Sandboxes from './pages/Sandboxes'
import Recovery from './pages/Recovery'
import { useAppStore } from './store/useAppStore'

function App() {
  const view = useAppStore((s) => s.view)
  const checkHealth = useAppStore((s) => s.checkHealth)
  const fetchMessages = useAppStore((s) => s.fetchMessages)

  // 初始化主题
  useEffect(() => {
    const migrated = localStorage.getItem('theme_version') === '2'
    const saved = migrated
      ? (localStorage.getItem('theme') || 'light')
      : 'light'
    localStorage.setItem('theme_version', '2')
    localStorage.setItem('theme', saved)
    document.documentElement.classList.toggle('dark', saved === 'dark')
    document.documentElement.classList.toggle('light', saved !== 'dark')
    useAppStore.setState({ theme: saved === 'dark' ? 'dark' : 'light' })
  }, [])

  // 健康检查
  useEffect(() => {
    checkHealth()
    const timer = setInterval(checkHealth, 10000)
    return () => clearInterval(timer)
  }, [checkHealth])

  useEffect(() => {
    fetchMessages()
  }, [fetchMessages])

  const pages: Record<string, React.ReactNode> = {
    chat: <Chat />,
    tasks: <Tasks />,
    cron: <Cron />,
    tools: <Tools />,
    mcp: <MCP />,
    skills: <Skills />,
    actions: <PendingActions />,
    audit: <Audit />,
    sandboxes: <Sandboxes />,
    recovery: <Recovery />,
  }

  return <Layout>{pages[view] || <Chat />}</Layout>
}

export default App
