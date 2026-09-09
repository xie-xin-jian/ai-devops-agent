import { Moon, Sun, RotateCcw, Trash2 } from 'lucide-react'
import { useAppStore } from '../store/useAppStore'

export default function TopBar({ title }: { title: string }) {
  const { theme, toggleTheme, view, resetMessages } = useAppStore()

  return (
    <header className="flex h-14 items-center justify-between border-b border-border-secondary bg-bg-primary px-6">
      <div className="flex items-center gap-3">
        <h1 className="text-base font-semibold">{title}</h1>
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
