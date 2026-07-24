import { CheckCircle, XCircle, Info, X } from 'lucide-react'
import { useAppStore } from '../store/useAppStore'

export default function Toast() {
  const { toast, clearToast } = useAppStore()
  if (!toast) return null

  const icons = {
    success: <CheckCircle size={18} className="text-status-success" />,
    error: <XCircle size={18} className="text-status-error" />,
    info: <Info size={18} className="text-status-info" />,
  }

  const bgColors = {
    success: 'border-status-success/30 bg-status-success/10',
    error: 'border-status-error/30 bg-status-error/10',
    info: 'border-status-info/30 bg-status-info/10',
  }

  return (
    <div className="fixed top-4 right-4 z-50">
      <div
        className={`flex items-center gap-3 rounded-xl border px-4 py-3 shadow-lg backdrop-blur-sm min-w-[240px] ${bgColors[toast.type]}`}
      >
        {icons[toast.type]}
        <span className="text-sm text-text-primary flex-1">{toast.msg}</span>
        <button
          onClick={clearToast}
          className="text-text-tertiary hover:text-text-primary transition-colors"
        >
          <X size={16} />
        </button>
      </div>
    </div>
  )
}
