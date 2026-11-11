interface BadgeProps {
  variant?: 'success' | 'warning' | 'error' | 'info' | 'default'
  children: React.ReactNode
}

const variants = {
  success: 'bg-status-success/8 text-status-success border-status-success/20',
  warning: 'bg-status-warning/8 text-status-warning border-status-warning/20',
  error: 'bg-status-error/8 text-status-error border-status-error/20',
  info: 'bg-status-info/8 text-status-info border-status-info/20',
  default: 'bg-bg-secondary text-text-secondary border-border-primary',
}

export default function Badge({ variant = 'default', children }: BadgeProps) {
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10.5px] font-medium leading-4 ${variants[variant]}`}
    >
      {children}
    </span>
  )
}
