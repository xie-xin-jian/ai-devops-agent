import { create } from 'zustand'
import type { Message, Task, CronJob, MCPServer, Tool, StdioMCPConfig, SseMCPConfig, Skill, SkillDetail, Target, PendingAction } from '../types'
import type { StreamEvent } from '../api'
import { actionApi, chatApi, taskApi, cronApi, mcpApi, systemApi, skillApi, targetApi } from '../api'

type View =
  | 'chat'
  | 'tasks'
  | 'cron'
  | 'tools'
  | 'mcp'
  | 'skills'
  | 'actions'
  | 'audit'
  | 'recovery'
  | 'sandboxes'
  | 'targets'

export interface ToolCallRecord {
  turn: number
  tool: string
  input?: Record<string, any>
  output?: string
  duration_ms?: number
  status: 'pending' | 'running' | 'done' | 'error'
}

export interface ChatSession {
  id: string
  title: string
  updatedAt: number
}

function loadChatSessions(): ChatSession[] {
  try {
    const raw = localStorage.getItem('chat_sessions')
    const parsed = raw ? JSON.parse(raw) : []
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

function persistChatSessions(sessions: ChatSession[]) {
  localStorage.setItem('chat_sessions', JSON.stringify(sessions.slice(0, 50)))
}

function initialTheme(): 'dark' | 'light' {
  const migrated = localStorage.getItem('theme_version') === '2'
  return migrated && localStorage.getItem('theme') === 'dark'
    ? 'dark'
    : 'light'
}

interface AppState {
  view: View
  setView: (v: View) => void

  theme: 'dark' | 'light'
  toggleTheme: () => void

  messages: Message[]
  isLoading: boolean
  sessionId: string
  chatSessions: ChatSession[]
  fetchChatSessions: () => Promise<void>
  sendMessage: (msg: string) => Promise<void>
  fetchMessages: () => Promise<void>
  resetMessages: () => Promise<void>
  newChat: () => void
  switchChat: (sessionId: string) => Promise<void>
  deleteChat: (sessionId: string) => Promise<void>

  // 流式状态（用于执行轨迹面板）
  isStreaming: boolean
  currentTurn: number
  toolHistory: ToolCallRecord[]
  liveText: string            // 正在流式输出的文字
  currentStatus: string       // Agent 当前状态（"正在调大模型"等）
  streamAbortController: AbortController | null
  stopStreaming: () => void

  targets: Target[]
  activeTargetId: string
  fetchTargets: () => Promise<void>
  createTarget: (payload: Partial<Target>) => Promise<Target>
  updateTarget: (targetId: string, payload: Partial<Target>) => Promise<Target>
  activateTarget: (targetId: string) => Promise<void>
  deleteTarget: (targetId: string) => Promise<void>

  pendingActions: PendingAction[]
  pendingActionBusyId: string
  fetchPendingActions: () => Promise<void>
  confirmPendingAction: (actionId: string) => Promise<void>
  cancelPendingAction: (actionId: string, reason?: string) => Promise<void>

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

function upsertChatSession(
  sessionId: string,
  title: string,
  set: (partial: Partial<AppState>) => void,
  get: () => AppState,
) {
  const cleanTitle = title.replace(/\s+/g, ' ').trim().slice(0, 32) || '新对话'
  const existing = get().chatSessions.find((item) => item.id === sessionId)
  const next = [
    {
      id: sessionId,
      title: existing?.title && existing.title !== '新对话'
        ? existing.title
        : cleanTitle,
      updatedAt: Date.now(),
    },
    ...get().chatSessions.filter((item) => item.id !== sessionId),
  ].sort((a, b) => b.updatedAt - a.updatedAt)
  set({ chatSessions: next })
  persistChatSessions(next)
}

function updateSessionTitle(
  sessionId: string,
  title: string,
  set: (partial: Partial<AppState>) => void,
  get: () => AppState,
) {
  upsertChatSession(sessionId, title, set, get)
}

let toastId = 0

export const useAppStore = create<AppState>((set, get) => ({
  view: 'chat',
  setView: (v) => set({ view: v }),

  theme: initialTheme(),
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
  chatSessions: loadChatSessions(),
  fetchChatSessions: async () => {
    try {
      const res = await chatApi.sessions()
      const local = get().chatSessions
      const merged = (res.sessions || []).map((session) => {
        const existing = local.find((item) => item.id === session.id)
        return {
          id: session.id,
          title: existing?.title || session.title || '新对话',
          updatedAt: session.updated_at * 1000,
        }
      })
      const serverIds = new Set(merged.map((item) => item.id))
      const remainingLocal = local.filter((item) => !serverIds.has(item.id))
      const next = [...merged, ...remainingLocal]
        .sort((a, b) => b.updatedAt - a.updatedAt)
        .slice(0, 50)
      set({ chatSessions: next })
      persistChatSessions(next)
    } catch {
      // Keep the local session index if server-side discovery is unavailable.
    }
  },
  isStreaming: false,
  currentTurn: 0,
  toolHistory: [],
  liveText: '',
  currentStatus: '',
  streamAbortController: null,
  targets: [],
  activeTargetId: '',
  pendingActions: [],
  pendingActionBusyId: '',

  fetchMessages: async () => {
    const sessionId = get().sessionId
    if (!sessionId) return
    try {
      const res = await systemApi.messages(sessionId)
      if (!get().isStreaming) {
        set({ messages: res.messages || [] })
        const firstUser = (res.messages || []).find((item: Message) => item.role === 'user')
        if (firstUser?.content) {
          updateSessionTitle(sessionId, firstUser.content, set, get)
        }
      }
    } catch {
      // History restoration should not block the chat page from loading.
    }
  },

  sendMessage: async (msg: string) => {
    if (!msg.trim() || get().isStreaming) return
    const userMsg: Message = { role: 'user', content: msg, timestamp: Date.now() }
    set((s) => ({
      messages: [...s.messages, userMsg],
      isStreaming: true,
      isLoading: true,
      toolHistory: [],
      liveText: '',
      currentStatus: '准备中...',
      currentTurn: 0,
    }))
    if (get().sessionId) {
      updateSessionTitle(get().sessionId, msg, set, get)
    }

    const controller = new AbortController()
    set({ streamAbortController: controller })

    try {
      const nextSessionId = await chatApi.stream(
        msg,
        get().sessionId,
        (event: StreamEvent) => {
          switch (event.type) {
            case 'pending_action':
              set((state) => {
                const pending = event.pending_action
                if (!pending) {
                  return {
                    currentStatus: '已生成待审批动作',
                  }
                }
                const nextAction = pending as PendingAction
                return {
                  pendingActions: state.pendingActions.some(
                    (item) => item.id === nextAction.id
                  )
                    ? state.pendingActions
                    : [...state.pendingActions, nextAction],
                  currentStatus: `待审批：${pending.title}`,
                }
              })
              break
            case 'status':
              set({ currentStatus: event.message || '', currentTurn: event.turn || 0 })
              break
            case 'thinking':
              set({ currentStatus: `第 ${event.turn} 轮：思考中...` })
              break
            case 'tool_use':
              set((s) => ({
                toolHistory: [...s.toolHistory, {
                  turn: event.turn!,
                  tool: event.tool!,
                  input: event.input,
                  status: 'running',
                }],
                currentStatus: `正在调用 ${event.tool}`,
              }))
              break
            case 'tool_result':
              set((s) => ({
                toolHistory: s.toolHistory.map((t) =>
                  t.turn === event.turn && t.tool === event.tool
                    ? { ...t, output: event.output, duration_ms: event.duration_ms, status: 'done' }
                    : t
                ),
                currentStatus: `${event.tool} 完成 (${event.duration_ms}ms)`,
              }))
              break
            case 'text_delta':
              set((s) => ({ liveText: s.liveText + event.delta }))
              break
            case 'error':
              set({ currentStatus: `错误: ${event.message}` })
              break
            case 'done':
              set((s) => {
                const aiMsg: Message = {
                  role: 'assistant',
                  content: event.text || s.liveText,
                  timestamp: Date.now(),
                }
                return {
                  messages: [...s.messages, aiMsg],
                  liveText: '',
                  isStreaming: false,
                  isLoading: false,
                  currentStatus: `完成，共 ${event.total_turns} 轮`,
                }
              })
              void get().fetchPendingActions()
              break
            case 'cancelled':
              set((s) => {
                const cancelledMsg: Message | null = event.text
                  ? {
                      role: 'assistant',
                      content: event.text,
                      timestamp: Date.now(),
                    }
                  : null
                return {
                  messages: cancelledMsg ? [...s.messages, cancelledMsg] : s.messages,
                  liveText: '',
                  isStreaming: false,
                  isLoading: false,
                  currentStatus: '已停止',
                }
              })
              break
          }
        },
        (sessionId) => {
          if (sessionId) {
            upsertChatSession(sessionId, msg, set, get)
          }
          if (sessionId && sessionId !== get().sessionId) {
            localStorage.setItem('session_id', sessionId)
            set({ sessionId })
          }
        },
        get().activeTargetId,
        controller.signal,
      )
      if (nextSessionId && nextSessionId !== get().sessionId) {
        localStorage.setItem('session_id', nextSessionId)
        set({ sessionId: nextSessionId })
      }
      if (nextSessionId) {
        upsertChatSession(nextSessionId, msg, set, get)
      }
    } catch (e: any) {
      if (e?.name !== 'AbortError') {
        set({ isStreaming: false, isLoading: false, currentStatus: '请求失败' })
        get().showToast('error', e.message || '发送失败')
      }
    } finally {
      set({ streamAbortController: null })
    }
  },

  stopStreaming: () => {
    const sessionId = get().sessionId
    const ctrl = get().streamAbortController
    if (sessionId) {
      systemApi.cancel(sessionId).catch(() => {
        // The local abort still stops the visible stream if cancellation fails.
      })
    }
    if (ctrl) ctrl.abort()
    set({ isStreaming: false, isLoading: false, currentStatus: '已停止' })
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

  fetchTargets: async () => {
    try {
      const res = await targetApi.list(get().sessionId)
      const activeTargetId = res.active_target_id || ''
      set({
        targets: res.targets || [],
        activeTargetId,
      })
    } catch {
      set({ targets: [] })
    }
  },

  createTarget: async (payload) => {
    const target = await targetApi.create(payload)
    set((state) => ({
      targets: [...state.targets, target].sort((a, b) => a.name.localeCompare(b.name)),
    }))
    return target
  },

  updateTarget: async (targetId, payload) => {
    const target = await targetApi.update(targetId, payload)
    set((state) => ({
      targets: state.targets
        .map((item) => (item.id === targetId ? target : item))
        .sort((a, b) => a.name.localeCompare(b.name)),
    }))
    return target
  },

  activateTarget: async (targetId) => {
    if (!targetId) {
      set({ activeTargetId: '', currentStatus: '未选择运维项目' })
      return
    }
    const result = await targetApi.activate(targetId, get().sessionId)
    if (result.session_id && result.session_id !== get().sessionId) {
      localStorage.setItem('session_id', result.session_id)
      set({ sessionId: result.session_id })
    }
    set({
      activeTargetId: targetId,
      currentStatus: `当前项目：${result.target.name}`,
    })
  },

  deleteTarget: async (targetId) => {
    await targetApi.remove(targetId)
    set((state) => ({
      targets: state.targets.filter((target) => target.id !== targetId),
      activeTargetId: state.activeTargetId === targetId ? '' : state.activeTargetId,
    }))
  },

  fetchPendingActions: async () => {
    const sessionId = get().sessionId
    if (!sessionId) {
      set({ pendingActions: [] })
      return
    }
    try {
      const result = await actionApi.pending(sessionId, 'pending')
      set({
        pendingActions: [...(result.actions || [])].sort(
          (a, b) => a.created_at - b.created_at
        ),
      })
    } catch {
      // Approval discovery should not block the chat view.
    }
  },

  confirmPendingAction: async (actionId) => {
    set({ pendingActionBusyId: actionId })
    try {
      await actionApi.confirm(actionId)
      set((state) => ({
        pendingActions: state.pendingActions.filter(
          (action) => action.id !== actionId
        ),
        currentStatus: '审批已提交，Agent 继续执行...',
      }))
      if (!get().isStreaming) {
        await get().fetchMessages()
        await get().fetchPendingActions()
      }
      get().showToast('success', '命令已批准并执行')
    } catch (error: any) {
      get().showToast('error', error.message || '审批执行失败')
    } finally {
      set({ pendingActionBusyId: '' })
    }
  },

  cancelPendingAction: async (actionId, reason = 'Rejected from chat') => {
    set({ pendingActionBusyId: actionId })
    try {
      await actionApi.cancel(actionId, 'api-user', reason)
      set((state) => ({
        pendingActions: state.pendingActions.filter(
          (action) => action.id !== actionId
        ),
      }))
      get().showToast('success', '命令已拒绝')
    } catch (error: any) {
      get().showToast('error', error.message || '拒绝失败')
    } finally {
      set({ pendingActionBusyId: '' })
    }
  },

  newChat: () => {
    if (get().isStreaming) {
      get().stopStreaming()
    }
    set({
      sessionId: '',
      messages: [],
      liveText: '',
      currentStatus: '',
      currentTurn: 0,
      toolHistory: [],
      isStreaming: false,
      isLoading: false,
      pendingActions: [],
    })
    localStorage.removeItem('session_id')
  },

  switchChat: async (sessionId) => {
    if (!sessionId || sessionId === get().sessionId) return
    if (get().isStreaming) {
      get().stopStreaming()
    }
    set({
      sessionId,
      messages: [],
      liveText: '',
      currentStatus: '正在加载会话...',
      currentTurn: 0,
      toolHistory: [],
    })
    localStorage.setItem('session_id', sessionId)
    await get().fetchMessages()
    await get().fetchTargets()
    await get().fetchPendingActions()
    set({ currentStatus: '' })
  },

  deleteChat: async (sessionId) => {
    systemApi.reset(sessionId).catch(() => {
      // Local removal still works if the backend session has expired.
    })
    const next = get().chatSessions.filter((item) => item.id !== sessionId)
    set({ chatSessions: next })
    persistChatSessions(next)
    if (get().sessionId === sessionId) {
      get().newChat()
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
