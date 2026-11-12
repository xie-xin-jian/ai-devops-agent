import { InputHTMLAttributes, TextareaHTMLAttributes } from 'react'

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: string
}

export function Input({ label, className = '', ...props }: InputProps) {
  return (
    <div className="flex flex-col gap-1.5">
      {label && <label className="text-xs font-medium text-text-secondary">{label}</label>}
      <input
        className={`h-9 w-full rounded-lg border border-border-primary bg-bg-secondary px-3 text-[13px] text-text-primary transition-colors placeholder:text-text-tertiary focus:border-text-tertiary focus:bg-bg-primary ${className}`}
        {...props}
      />
    </div>
  )
}

interface TextareaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  label?: string
}

export function Textarea({ label, className = '', ...props }: TextareaProps) {
  return (
    <div className="flex flex-col gap-1.5">
      {label && <label className="text-xs font-medium text-text-secondary">{label}</label>}
      <textarea
        className={`w-full resize-none rounded-lg border border-border-primary bg-bg-secondary px-3 py-2.5 text-[13px] text-text-primary transition-colors placeholder:text-text-tertiary focus:border-text-tertiary focus:bg-bg-primary ${className}`}
        {...props}
      />
    </div>
  )
}
