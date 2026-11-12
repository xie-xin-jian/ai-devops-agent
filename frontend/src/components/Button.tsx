import { ButtonHTMLAttributes } from 'react'

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger'
  size?: 'sm' | 'md'
}

const variants = {
  primary: 'bg-accent-primary text-bg-primary hover:bg-accent-hover',
  secondary: 'bg-bg-secondary text-text-primary border border-border-primary hover:bg-bg-hover',
  ghost: 'text-text-secondary hover:bg-bg-hover hover:text-text-primary',
  danger: 'border border-status-error/20 bg-status-error/10 text-status-error hover:bg-status-error/15',
}

const sizes = {
  sm: 'h-7 px-2.5 text-[11px]',
  md: 'h-8 px-3 text-[12px]',
}

export default function Button({
  variant = 'primary',
  size = 'md',
  className = '',
  children,
  ...props
}: ButtonProps) {
  return (
    <button
      className={`inline-flex items-center justify-center gap-1.5 rounded-lg font-medium tracking-[-0.005em] transition-all disabled:cursor-not-allowed disabled:opacity-45 ${variants[variant]} ${sizes[size]} ${className}`}
      {...props}
    >
      {children}
    </button>
  )
}
