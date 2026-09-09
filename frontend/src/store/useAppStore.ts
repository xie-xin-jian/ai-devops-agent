import { create } from 'zustand'
import type { Message, Task, CronJob, MCPServer, Tool, StdioMCPConfig, SseMCPConfig, Skill, SkillDetail } from '../types'
import { chatApi, taskApi, cronApi, mcpApi, systemApi, skillApi } from '../api'

type View = 'chat' | 'tasks' | 'cron' | 'tools' | 'mcp' | 'skills'

interface AppState {
  view: View
  setView: (v: View) => void

  theme: 'dark' | 'light'
  toggleTheme: () => void

  messages: Message[]
  isLoading: boolean
  sessionId: string
  sendMessage: (msg: string) => Promise<void>
  resetMessages: () => Promise<void>

  tasks: Task[]
  fetchTasks: () => Promise<void>
  createTask: (t: Partial<Task>) => Promise<void>
  claimTask: (id: string) => Promise<void>
  completeTask: (id: string, result?: string) => Promise<void>
  deleteTask: (id: string) => Promise<void>

  cronJobs: CronJob[]
  fetchCronJobs: () => Promise<void>
  createCronJob: (j: Partial<CronJob>) => Promise<void>
  deleteCronJob: (id: string) => Promise<void>

  mcpServers: MCPServer[]
  fetchMcpServers: () => Promise<void>
  connectMcp: (name: string) => Promise<void>
  disconnectMcp: (name: string) => Promise<void>
  connectStdioMcp: (config: StdioMCPConfig) => Promise<void>
  disconnectStdioMcp: (name: string) => Promise<void>
  connectSseMcp: (config: SseMCPConfig) => Promise<void>
  disconnectSseMcp: (name: string) => Promise<void>

  skills: Skill[]
  selectedSkill: SkillDetail | null
  fetchSkills: () => Promise<void>
  fetchSkillDetail: (name: string) => Promise<void>
  clearSelectedSkill: () => void

  tools: Tool[]
  fetchTools: () => Promise<void>

  health: { ok: boolean; workdir: string }
  checkHealth: () => Promise<void>

  toast: { id: number; type: 'success' | 'error' | 'info'; msg: string } | null
  showToast: (type: 'success' | 'error' | 'info', msg: string) => void
  clearToast: () => void
}

let toastId = 0

export const useAppStore = create<AppState>((set, get) => ({
  view: 'chat',
  setView: (v) => set({ view: v }),

  theme: 'dark',
  toggleTheme: () => {
    const next = get().theme === 'dark' ? 'light' : 'dark'
    document.documentElement.classList.toggle('dark', next === 'dark')
    document.documentElement.classList.toggle('light', next === 'light')
    set({ theme: next })
    localStorage.setItem('theme', next)
  },

  messages: [],
  isLoading: false,
  sessionId: localStorage.getItem('session_id') || '',
  sendMessage: async (msg: string) => {
    if (!msg.trim() || get().isLoading) return
    const userMsg: Message = { role: 'user', content: msg, timestamp: Date.now() }
    set((s) => ({ messages: [...s.messages, userMsg], isLoading: true }))
    try {
      const res = await chatApi.send(msg, get().sessionId)
      if (res.session_id && res.session_id !== get().sessionId) {
        localStorage.setItem('session_id', res.session_id)
      }
      const aiMsg: Message = {
        role: 'assistant',
        content: res.response,
        timestamp: Date.now(),
      }
      set((s) => ({ messages: [...s.messages, aiMsg], isLoading: false, sessionId: res.session_id }))
    } catch (e: any) {
      set({ isLoading: false })
      get().showToast('error', e.message || '发送失败')
    }
  },
  resetMessages: async () => {
    try {
      await systemApi.reset(get().sessionId)
      set({ messages: [] })
      get().showToast('success', '对话已重置')
    } catch (e: any) {
      get().showToast('error', e.message || '重置失败')
    }
  },

  tasks: [],
  fetchTasks: async () => {
    try {
      const res = await taskApi.list()
      const list = Array.isArray(res) ? res : (res.tasks || [])
      set({ tasks: list })
    } catch (e: any) {
      set({ tasks: [] })
      get().showToast('error', e.message || '加载任务失败')
    }
  },
  createTask: async (t) => {
    try {
      await taskApi.create(t)
      await get().fetchTasks()
      get().showToast('success', '任务创建成功')
    } catch (e: any) {
      get().showToast('error', e.message || '创建任务失败')
    }
  },
  claimTask: async (id) => {
    try {
      await taskApi.claim(id)
      await get().fetchTasks()
      get().showToast('success', '已认领任务')
    } catch (e: any) {
      get().showToast('error', e.message || '认领失败')
    }
  },
  completeTask: async (id, result) => {
    try {
      await taskApi.complete(id, result)
      await get().fetchTasks()
      get().showToast('success', '任务已完成')
    } catch (e: any) {
      get().showToast('error', e.message || '完成任务失败')
    }
  },
  deleteTask: async (id) => {
    try {
      await taskApi.remove(id)
      await get().fetchTasks()
      get().showToast('success', '任务已删除')
    } catch (e: any) {
      get().showToast('error', e.message || '删除失败')
    }
  },

  cronJobs: [],
  fetchCronJobs: async () => {
    try {
      const res = await cronApi.list()
      set({ cronJobs: res.jobs || [] })
    } catch (e: any) {
      set({ cronJobs: [] })
      get().showToast('error', e.message || '加载定时任务失败')
    }
  },
  createCronJob: async (j) => {
    try {
      await cronApi.create(j)
      await get().fetchCronJobs()
      get().showToast('success', '定时任务创建成功')
    } catch (e: any) {
      get().showToast('error', e.message || '创建失败')
    }
  },
  deleteCronJob: async (id) => {
    try {
      await cronApi.remove(id)
      await get().fetchCronJobs()
      get().showToast('success', '定时任务已删除')
    } catch (e: any) {
      get().showToast('error', e.message || '删除失败')
    }
  },

  mcpServers: [],
  fetchMcpServers: async () => {
    try {
      const res = await mcpApi.list()
      set({ mcpServers: res.servers || [] })
    } catch (e: any) {
      set({ mcpServers: [] })
      get().showToast('error', e.message || '加载 MCP 失败')
    }
  },
  connectMcp: async (name) => {
    try {
      await mcpApi.connect(name)
      await get().fetchMcpServers()
      await get().fetchTools()
      get().showToast('success', `已连接 ${name}`)
    } catch (e: any) {
      get().showToast('error', e.message || '连接失败')
    }
  },
  disconnectMcp: async (name) => {
    try {
      await mcpApi.disconnect(name)
      await get().fetchMcpServers()
      await get().fetchTools()
      get().showToast('success', `已断开 ${name}`)
    } catch (e: any) {
      get().showToast('error', e.message || '断开失败')
    }
  },
  connectStdioMcp: async (config) => {
    try {
      await mcpApi.connectStdio(config)
      await get().fetchMcpServers()
      await get().fetchTools()
      get().showToast('success', `已连接标准 MCP 服务器 ${config.name}`)
    } catch (e: any) {
      get().showToast('error', e.message || '连接失败')
    }
  },
  disconnectStdioMcp: async (name) => {
    try {
      await mcpApi.disconnectStdio(name)
      await get().fetchMcpServers()
      await get().fetchTools()
      get().showToast('success', `已断开 ${name}`)
    } catch (e: any) {
      get().showToast('error', e.message || '断开失败')
    }
  },
  connectSseMcp: async (config) => {
    try {
      await mcpApi.connectSse(config)
      await get().fetchMcpServers()
      await get().fetchTools()
      get().showToast('success', `已连接远程 MCP 服务器 ${config.name}`)
    } catch (e: any) {
      get().showToast('error', e.message || '连接失败')
    }
  },
  disconnectSseMcp: async (name) => {
    try {
      await mcpApi.disconnectSse(name)
      await get().fetchMcpServers()
      await get().fetchTools()
      get().showToast('success', `已断开 ${name}`)
    } catch (e: any) {
      get().showToast('error', e.message || '断开失败')
    }
  },

  skills: [],
  selectedSkill: null,
  fetchSkills: async () => {
    try {
      const res = await skillApi.list()
      set({ skills: res.skills || [] })
    } catch (e: any) {
      set({ skills: [] })
    }
  },
  fetchSkillDetail: async (name) => {
    try {
      const res = await skillApi.get(name)
      set({ selectedSkill: res })
    } catch (e: any) {
      set({ selectedSkill: null })
      get().showToast('error', '加载技能详情失败')
    }
  },
  clearSelectedSkill: () => set({ selectedSkill: null }),

  tools: [],
  fetchTools: async () => {
    try {
      const res = await systemApi.tools()
      set({ tools: res.tools || [] })
    } catch (e: any) {
      set({ tools: [] })
    }
  },

  health: { ok: false, workdir: '' },
  checkHealth: async () => {
    try {
      const res = await systemApi.health()
      set({ health: { ok: res.status === 'ok', workdir: res.workdir } })
    } catch {
      set({ health: { ok: false, workdir: '' } })
    }
  },

  toast: null,
  showToast: (type, msg) => {
    const id = ++toastId
    set({ toast: { id, type, msg } })
    setTimeout(() => {
      if (get().toast?.id === id) set({ toast: null })
    }, 3000)
  },
  clearToast: () => set({ toast: null }),
}))
