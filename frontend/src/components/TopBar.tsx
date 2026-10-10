import { FolderOpen, Moon, Sun, RotateCcw } from 'lucide-react'
import { useAppStore } from '../store/useAppStore'

export default function TopBar({ title }: { title: string }) {
  const {
    theme,
    toggleTheme,
    view,
    resetMessages,
    targets,
    activeTargetId,
    activateTarget,
    setView,
  } = useAppStore()
  const activeTarget = targets.find((target) => target.id === activeTargetId)

  return (
    <header className="flex h-14 items-center justify-between border-b border-border-secondary bg-bg-primary px-6">
      <div className="flex items-center gap-3">
        <h1 className="text-base font-semibold">{title}</h1>
        {view === 'chat' && (
          targets.length > 0 ? (
            <label className="flex items-center gap-1.5 rounded-lg border border-border-primary bg-bg-secondary px-2 py-1 text-xs text-text-secondary">
              <FolderOpen size={13} className="text-accent-primary" />
              <select
                value={activeTargetId}
                onChange={(event) => activateTarget(event.target.value)}
                className="max-w-52 bg-transparent outline-none"
              >
                <option value="">未选择项目</option>
                {targets.map((target) => (
                  <option key={target.id} value={target.id}>{target.name}</option>
                ))}
              </select>
            </label>
          ) : (
            <button
              onClick={() => setView('targets')}
              className="rounded-lg border border-border-primary bg-bg-secondary px-2 py-1 text-xs text-text-secondary hover:text-text-primary"
            >
              选择运维项目
            </button>
          )
        )}
        {activeTarget && view === 'chat' && (
          <span className="hidden max-w-64 truncate font-mono text-[11px] text-text-tertiary xl:block">
            {activeTarget.root}
          </span>
        )}
      </div>

      <div className="flex items-center gap-2">
        {view === 'chat' && (
          <button
            onClick={resetMessages}
            className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs text-text-secondary hover:bg-bg-hover hover:text-text-primary transition-colors"
            title="重置对话"
          >
            <RotateCcw size={14} />
            重置
          </button>
        )}

        <button
          onClick={toggleTheme}
          className="flex h-8 w-8 items-center justify-center rounded-lg text-text-secondary hover:bg-bg-hover hover:text-text-primary transition-colors"
          title={theme === 'dark' ? '切换亮色' : '切换暗色'}
        >
          {theme === 'dark' ? <Sun size={16} /> : <Moon size={16} />}
        </button>
      </div>
    </header>
  )
}
