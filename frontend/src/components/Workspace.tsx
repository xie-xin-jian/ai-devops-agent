import type { ReactNode } from 'react'

export function WorkspacePage({
  title,
  description,
  actions,
  children,
  wide = false,
}: {
  title: string
  description?: string
  actions?: ReactNode
  children: ReactNode
  wide?: boolean
}) {
  return (
    <div className="workspace-page">
      <div className={`workspace-inner ${wide ? 'max-w-[1320px]' : 'max-w-[1120px]'}`}>
        <header className="workspace-page-header">
          <div className="min-w-0">
            <h1>{title}</h1>
            {description && <p>{description}</p>}
          </div>
          {actions && <div className="workspace-page-actions">{actions}</div>}
        </header>
        {children}
      </div>
    </div>
  )
}

export function WorkspaceToolbar({ children }: { children: ReactNode }) {
  return <div className="workspace-toolbar">{children}</div>
}

export function WorkspacePanel({
  children,
  className = '',
  padded = false,
}: {
  children: ReactNode
  className?: string
  padded?: boolean
}) {
  return (
    <div className={`workspace-panel ${padded ? 'workspace-panel-padded' : ''} ${className}`}>
      {children}
    </div>
  )
}

export function SplitView({
  children,
  aside,
  asideWidth = '400px',
}: {
  children: ReactNode
  aside: ReactNode
  asideWidth?: string
}) {
  return (
    <div
      className="workspace-split"
      style={{ gridTemplateColumns: `minmax(0, 1fr) ${asideWidth}` }}
    >
      {children}
      {aside}
    </div>
  )
}

export function WorkspaceEmpty({
  icon,
  title,
  description,
}: {
  icon: ReactNode
  title: string
  description?: string
}) {
  return (
    <div className="workspace-empty">
      <div className="workspace-empty-icon">{icon}</div>
      <div className="text-[13px] font-medium text-text-primary">{title}</div>
      {description && (
        <div className="mt-1 max-w-sm text-center text-[12px] leading-5 text-text-tertiary">
          {description}
        </div>
      )}
    </div>
  )
}

export function SectionLabel({ children }: { children: ReactNode }) {
  return <div className="workspace-section-label">{children}</div>
}

export function InlineNotice({
  tone = 'info',
  children,
}: {
  tone?: 'info' | 'warning' | 'error'
  children: ReactNode
}) {
  return <div className={`workspace-notice workspace-notice-${tone}`}>{children}</div>
}
