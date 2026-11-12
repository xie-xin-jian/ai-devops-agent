import { X } from 'lucide-react'

interface ModalProps {
  open: boolean
  onClose: () => void
  title: string
  children: React.ReactNode
  footer?: React.ReactNode
}

export default function Modal({ open, onClose, title, children, footer }: ModalProps) {
  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* 遮罩 */}
      <div
        className="absolute inset-0 bg-black/50 backdrop-blur-sm"
        onClick={onClose}
      />

      {/* 弹窗 */}
      <div className="relative mx-4 w-full max-w-lg overflow-hidden rounded-2xl border border-border-primary bg-bg-primary shadow-[0_24px_80px_rgba(20,18,15,0.24)]">
        {/* 头部 */}
        <div className="flex items-center justify-between border-b border-border-secondary px-5 py-4">
          <h3 className="text-[13px] font-semibold">{title}</h3>
          <button
            onClick={onClose}
            className="text-text-tertiary hover:text-text-primary transition-colors"
          >
            <X size={18} />
          </button>
        </div>

        {/* 内容 */}
        <div className="px-5 py-5">{children}</div>

        {/* 底部 */}
        {footer && (
          <div className="flex justify-end gap-2 border-t border-border-secondary bg-bg-secondary/60 px-5 py-3">
            {footer}
          </div>
        )}
      </div>
    </div>
  )
}
