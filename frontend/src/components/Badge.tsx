interface BadgeProps {
  variant?: 'success' | 'warning' | 'error' | 'info' | 'default'
  children: React.ReactNode
}

const variants = {
  success: 'bg-status-success/10 text-status-success border-status-success/30',
  warning: 'bg-status-warning/10 text-status-warning border-status-warning/30',
  error: 'bg-status-error/10 text-status-error border-status-error/30',
  info: 'bg-status-info/10 text-status-info border-status-info/30',
  default: 'bg-bg-tertiary text-text-secondary border-border-primary',
}

export default function Badge({ variant = 'default', children }: BadgeProps) {
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium ${variants[variant]}`}
    >
      {children}
    </span>
  )
}
