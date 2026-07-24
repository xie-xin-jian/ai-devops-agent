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
  last_run_at?: number
}

// MCP 服务器
export interface MCPServer {
  name: string
  connected: boolean
  tool_count: number
  description?: string
  type?: 'builtin' | 'custom' | 'stdio'  // 服务器类型
}

// 标准 MCP 服务器连接参数
export interface StdioMCPConfig {
  name: string
  command: string
  args: string[]
  cwd?: string
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

// Skill
export interface Skill {
  name: string
  description: string
}

export interface SkillDetail extends Skill {
  content: string
}
