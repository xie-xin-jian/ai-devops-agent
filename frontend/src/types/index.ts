// 消息类型
export interface Message {
  role: 'user' | 'assistant' | 'tool_result'
  content: string
  tool_name?: string
  timestamp?: number
}

// 任务
export interface Task {
  id: string
  subject: string
  description: string
  status: 'pending' | 'in_progress' | 'completed' | 'blocked'
  priority: 'low' | 'medium' | 'high'
  blockedBy?: string[]
  details?: string
  result?: string
  created_at: number
  updated_at: number
  assignee?: string
}

// Cron 任务
export interface CronJob {
  id: string
  name: string
  description: string
  cron_expression: string
  message: string
  enabled: boolean
  created_at: number
  running?: boolean
  last_run_at?: string
  last_finished_at?: string
  last_success?: boolean | null
}

export interface CronLog {
  job_id: string
  cron: string
  prompt: string
  fired_at: string
  finished_at: string
  success: boolean
  output: string
  error: string | null
}

// MCP 服务器
export interface MCPServer {
  name: string
  connected: boolean
  tool_count: number
  description?: string
  type?: 'builtin' | 'custom' | 'stdio' | 'sse'  // 服务器类型
}

// 标准 MCP 服务器连接参数（Stdio 本地子进程）
export interface StdioMCPConfig {
  name: string
  command: string
  args: string[]
  cwd?: string
}

// 远程 MCP 服务器连接参数（SSE 远程连接）
export interface SseMCPConfig {
  name: string
  url: string
}

// 工具
export interface Tool {
  name: string
  description: string
  input_schema: {
    type: string
    properties?: Record<string, any>
    required?: string[]
  }
}

// 健康状态
export interface HealthStatus {
  status: 'ok' | 'error'
  workdir: string
}

// 运维目标项目
export interface Target {
  id: string
  name: string
  root: string
  description: string
  service: string
  health_url: string
  deploy_command: string
  restart_command: string
  log_path: string
  created_at: number
  updated_at: number
}

export interface TargetBrowserEntry {
  name: string
  path: string
}

export interface TargetBrowserResult {
  allowed_roots: string[]
  current: string
  parent: string
  entries: TargetBrowserEntry[]
  selectable: boolean
  message?: string
}

export interface PendingAction {
  id: string
  session_id: string
  target_id: string
  run_id: string
  tool_use_id: string
  action_code: string
  title: string
  risk_level: string
  status: string
  summary: string
  payload: {
    tool?: string
    input?: Record<string, any>
  }
  steps: Array<{
    tool: string
    description: string
    input?: Record<string, any>
    status?: string
  }>
  impact: string
  rollback_plan: string
  verification: string
  result_payload: Record<string, any>
  created_at: number
  updated_at: number
}

// Skill
export interface Skill {
  name: string
  description: string
}

export interface SkillDetail extends Skill {
  content: string
}
