import type { Message, Task, CronJob, MCPServer, Tool, HealthStatus, StdioMCPConfig, Skill, SkillDetail } from '../types'

const API_BASE = ''

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(`${API_BASE}${url}`, {
      headers: {
        'Content-Type': 'application/json',
        ...options?.headers,
      },
      ...options,
    })
  } catch (e: any) {
    throw new Error('无法连接服务器，请确认后端已启动 (python run.py)')
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.error || err.detail || `请求失败: ${res.status}`)
  }
  return res.json()
}

// 对话
export const chatApi = {
  send: (message: string) =>
    request<{ response: string; message_id?: string }>('/api/chat/', {
      method: 'POST',
      body: JSON.stringify({ message }),
    }),
}

// 任务 - 后端返回 {tasks: [...]} 或数组，字段已补全
export const taskApi = {
  list: async () => {
    const res = await request<any>('/api/tasks/')
    const list = Array.isArray(res) ? res : (res.tasks || [])
    return { tasks: list as Task[] }
  },
  get: (id: string) => request<Task>(`/api/tasks/${id}`),
  create: (data: Partial<Task>) =>
    request<Task>('/api/tasks/', {
      method: 'POST',
      body: JSON.stringify({
        subject: data.subject,
        description: data.description,
        blockedBy: data.blockedBy,
      }),
    }),
  claim: (id: string) =>
    request<Task>(`/api/tasks/${id}/claim`, {
      method: 'POST',
      body: JSON.stringify({ owner: 'ui' }),
    }),
  complete: (id: string, result?: string) =>
    request<Task>(`/api/tasks/${id}/complete`, {
      method: 'POST',
      body: JSON.stringify({ result }),
    }),
  remove: (id: string) =>
    request<{ success: boolean }>(`/api/tasks/${id}`, { method: 'DELETE' }),
}

// Cron - 后端字段是 id/cron/prompt/recurring，前端字段不同，做映射
export const cronApi = {
  list: async () => {
    const res: any = await request<any>('/api/cron/')
    const arr = Array.isArray(res) ? res : (res.jobs || [])
    const jobs: CronJob[] = arr.map((j: any) => ({
      id: j.id,
      name: j.name || j.id,
      description: j.description || '',
      cron_expression: j.cron_expression || j.cron || '',
      message: j.message || j.prompt || '',
      enabled: j.enabled !== false && j.recurring !== false,
      created_at: j.created_at || 0,
      last_run_at: j.last_run_at,
    }))
    return { jobs, total: jobs.length }
  },
  create: (data: Partial<CronJob>) =>
    request<any>('/api/cron/', {
      method: 'POST',
      body: JSON.stringify({
        cron: data.cron_expression,
        prompt: data.message,
        recurring: data.enabled !== false,
      }),
    }),
  remove: (id: string) =>
    request<any>(`/api/cron/${id}`, { method: 'DELETE' }),
}

// MCP - 后端返回 {connected, available, custom, stdio_servers}，做映射
// connected: [{name, tools}] 对象数组
// available: [name] 字符串数组
// custom: [{name, description, tools}] 对象数组
// stdio_servers: [name] 字符串数组
export const mcpApi = {
  list: async () => {
    const res = await request<any>('/api/mcp/')
    const connectedArr: any[] = Array.isArray(res.connected) ? res.connected : []
    const availableArr: string[] = Array.isArray(res.available) ? res.available : []
    const customArr: any[] = Array.isArray(res.custom) ? res.custom : []
    const stdioArr: string[] = Array.isArray(res.stdio_servers) ? res.stdio_servers : []

    // 提取名称集合
    const connectedNames = new Set(connectedArr.map((c: any) =>
      typeof c === 'string' ? c : c?.name
    ).filter(Boolean))

    const customNames = new Set(customArr.map((c: any) =>
      typeof c === 'string' ? c : c?.name
    ).filter(Boolean))

    const stdioNames = new Set(stdioArr)

    // 收集所有服务器名称
    const allNames = new Set<string>()
    availableArr.forEach((n: string) => allNames.add(n))
    customNames.forEach((n: string) => allNames.add(n))
    stdioNames.forEach((n: string) => allNames.add(n))
    connectedNames.forEach((n: string) => allNames.add(n))

    // 构建描述和工具数量映射
    const descMap: Record<string, string> = {}
    const toolCountMap: Record<string, number> = {}
    const typeMap: Record<string, 'builtin' | 'custom' | 'stdio'> = {}

    availableArr.forEach((n: string) => {
      descMap[n] = 'Mock 服务器'
      typeMap[n] = 'builtin'
    })
    customArr.forEach((c: any) => {
      if (c && typeof c === 'object' && c.name) {
        descMap[c.name] = c.description || '自定义服务器'
        toolCountMap[c.name] = Array.isArray(c.tools) ? c.tools.length : 0
        typeMap[c.name] = 'custom'
      }
    })
    stdioArr.forEach((n: string) => {
      descMap[n] = '标准 MCP 服务器'
      typeMap[n] = 'stdio'
    })
    connectedArr.forEach((c: any) => {
      if (c && typeof c === 'object' && c.name) {
        if (!descMap[c.name]) descMap[c.name] = '已连接服务器'
        toolCountMap[c.name] = Array.isArray(c.tools) ? c.tools.length : (toolCountMap[c.name] || 0)
      }
    })

    const servers: MCPServer[] = Array.from(allNames).map((name: string) => ({
      name,
      connected: connectedNames.has(name),
      tool_count: toolCountMap[name] || 0,
      description: descMap[name] || '未知服务器',
      type: typeMap[name],
    }))
    return { servers }
  },
  connect: (name: string) =>
    request<any>('/api/mcp/connect', {
      method: 'POST',
      body: JSON.stringify({ name }),
    }),
  disconnect: (name: string) =>
    request<any>('/api/mcp/disconnect', {
      method: 'POST',
      body: JSON.stringify({ name }),
    }),
  // 标准 MCP 服务器（stdio）
  connectStdio: (config: StdioMCPConfig) =>
    request<any>('/api/mcp/stdio/connect', {
      method: 'POST',
      body: JSON.stringify(config),
    }),
  disconnectStdio: (name: string) =>
    request<any>('/api/mcp/stdio/disconnect', {
      method: 'POST',
      body: JSON.stringify({ name }),
    }),
  tools: async () => {
    const res = await request<any>('/api/mcp/tools')
    // 后端返回 {tools: ["name1", ...]}，转成 Tool 对象
    const names: string[] = res.tools || []
    const tools: Tool[] = names.map((n: string) => ({
      name: n,
      description: 'MCP 工具',
      input_schema: { type: 'object', properties: {} },
    }))
    return { tools }
  },
  reload: () => request<any>('/api/mcp/reload', { method: 'POST' }),
  customList: () => request<Record<string, any>>('/api/mcp/custom'),
  customCreate: (name: string, data: any) =>
    request<any>('/api/mcp/custom', {
      method: 'POST',
      body: JSON.stringify({ name, ...data }),
    }),
  customDelete: (name: string) =>
    request<any>(`/api/mcp/custom/${name}`, { method: 'DELETE' }),
}

// Skills
export const skillApi = {
  list: async () => {
    const res = await request<any>('/api/skills/')
    const skills: Skill[] = res.skills || []
    return { skills, count: res.count || 0 }
  },
  get: async (name: string) => {
    const res = await request<any>(`/api/skills/${name}`)
    return res as SkillDetail
  },
  reload: () => request<any>('/api/skills/reload', { method: 'POST' }),
}

// 系统
// 后端 /tools 返回字符串数组 ["read_file", ...]，需要转成 Tool 对象
const TOOL_DESCRIPTIONS: Record<string, string> = {
  read_file: '读取文件内容',
  write_file: '写入文件内容',
  edit_file: '编辑文件指定部分',
  glob: '按模式匹配文件',
  bash: '执行 shell 命令',
  service_status: '查询系统服务状态',
  disk_usage: '查看磁盘使用情况',
  docker_ps: '列出 Docker 容器',
  system_info: '查看系统基本信息',
  memory_usage: '查看内存使用情况',
  cpu_usage: '查看 CPU 使用情况',
  process_top: '查看 CPU 占用最高的进程',
  process_search: '按名称搜索进程',
  network_interfaces: '查看网络接口配置',
  port_listen: '查看监听端口',
  ping_host: 'Ping 测试网络连通性',
  disk_io: '查看磁盘 IO 统计',
  system_logs: '查看系统日志',
  docker_logs: '查看 Docker 容器日志',
  docker_stats: '查看 Docker 容器资源使用',
  todo_write: '管理待办事项',
  create_task: '创建任务',
  list_tasks: '列出所有任务',
  get_task: '获取任务详情',
  claim_task: '认领任务',
  complete_task: '完成任务',
  list_skills: '列出可用技能',
  load_skill: '加载指定技能',
  spawn_subagent: '启动子 Agent',
  compact: '压缩上下文',
  schedule_cron: '创建定时任务',
  list_crons: '列出定时任务',
  cancel_cron: '取消定时任务',
  connect_mcp: '连接 MCP 服务器',
}

export const systemApi = {
  health: async () => {
    const res = await request<any>('/health')
    return { status: res.status, workdir: res.workdir || '' } as HealthStatus
  },
  tools: async () => {
    const res = await request<any>('/tools')
    const rawTools = res.tools || res || []
    const arr = Array.isArray(rawTools) ? rawTools : []
    // 后端返回的是字符串数组，转成 Tool 对象
    const tools: Tool[] = arr.map((item: any) => {
      if (typeof item === 'string') {
        return {
          name: item,
          description: TOOL_DESCRIPTIONS[item] || (item.startsWith('mcp__') ? 'MCP 工具' : '工具'),
          input_schema: { type: 'object', properties: {}, required: [] },
        }
      }
      // 如果已经是对象，保证字段完整
      return {
        name: item.name || 'unknown',
        description: item.description || '',
        input_schema: item.input_schema || { type: 'object', properties: {}, required: [] },
      }
    })
    return { tools }
  },
  reset: () => request<{ ok: boolean }>('/api/reset/', { method: 'POST' }),
  messages: () => request<{ messages: Message[] }>('/api/messages/'),
}
