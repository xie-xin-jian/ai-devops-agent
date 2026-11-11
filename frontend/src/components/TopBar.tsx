import { Moon, Sun, RotateCcw } from 'lucide-react'
import { useAppStore } from '../store/useAppStore'

export default function TopBar({ title }: { title: string }) {
  const { theme, toggleTheme, view, resetMessages } = useAppStore()

  return (
    <header className="flex h-10 items-center justify-between border-b border-border-secondary bg-bg-primary px-4">
      <div className="flex items-center gap-3">
        <h1 className="text-[12px] text-text-primary">{title}</h1>
      </div>

      <div className="flex items-center gap-1">
        {view === 'chat' && (
          <button
            onClick={resetMessages}
            className="flex items-center gap-1 px-2 py-1 text-[11px] text-text-secondary transition-colors hover:text-text-primary"
            title="重置对话"
          >
            <RotateCcw size={12} />
            重置
          </button>
        )}

        <button
          onClick={toggleTheme}
          className="flex h-6 w-6 items-center justify-center text-text-secondary transition-colors hover:text-text-primary"
          title={theme === 'dark' ? '切换亮色' : '切换暗色'}
        >
          {theme === 'dark' ? <Sun size={13} /> : <Moon size={13} />}
        </button>
      </div>
    </header>
  )
}
