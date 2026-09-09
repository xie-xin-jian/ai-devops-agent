import { useEffect } from 'react'
import Layout from './components/Layout'
import Chat from './pages/Chat'
import Tasks from './pages/Tasks'
import Cron from './pages/Cron'
import Tools from './pages/Tools'
import MCP from './pages/MCP'
import Skills from './pages/Skills'
import { useAppStore } from './store/useAppStore'

function App() {
  const view = useAppStore((s) => s.view)
  const checkHealth = useAppStore((s) => s.checkHealth)

  // 初始化主题
  useEffect(() => {
    const saved = localStorage.getItem('theme')
    if (saved === 'light') {
      document.documentElement.classList.remove('dark')
      document.documentElement.classList.add('light')
      useAppStore.setState({ theme: 'light' })
    }
  }, [])

  // 健康检查
  useEffect(() => {
    checkHealth()
    const timer = setInterval(checkHealth, 10000)
    return () => clearInterval(timer)
  }, [checkHealth])

  const pages: Record<string, React.ReactNode> = {
    chat: <Chat />,
    tasks: <Tasks />,
    cron: <Cron />,
    tools: <Tools />,
    mcp: <MCP />,
    skills: <Skills />,
  }

  return <Layout>{pages[view] || <Chat />}</Layout>
}

export default App
