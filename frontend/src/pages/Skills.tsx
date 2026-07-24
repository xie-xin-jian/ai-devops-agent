import { useEffect, useState } from 'react'
import { BookOpen, RefreshCw, ArrowLeft, Sparkles } from 'lucide-react'
import { useAppStore } from '../store/useAppStore'
import Button from '../components/Button'

export default function Skills() {
  const { skills, selectedSkill, fetchSkills, fetchSkillDetail, clearSelectedSkill } = useAppStore()
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    fetchSkills()
  }, [fetchSkills])

  const handleSelect = async (name: string) => {
    setLoading(true)
    try {
      await fetchSkillDetail(name)
    } finally {
      setLoading(false)
    }
  }

  const handleBack = () => {
    clearSelectedSkill()
  }

  const handleReload = async () => {
    await fetchSkills()
    if (selectedSkill) {
      await fetchSkillDetail(selectedSkill.name)
    }
  }

  if (selectedSkill) {
    return (
      <div className="h-full overflow-y-auto p-6">
        <div className="mx-auto max-w-4xl">
          <div className="mb-6 flex items-center justify-between">
            <div className="flex items-center gap-3">
              <button
                onClick={handleBack}
                className="flex items-center gap-1 text-sm text-text-secondary hover:text-text-primary"
              >
                <ArrowLeft size={16} />
                返回列表
              </button>
            </div>
            <Button variant="secondary" onClick={handleReload}>
              <RefreshCw size={14} />
              刷新
            </Button>
          </div>

          <div className="rounded-xl border border-border-primary bg-bg-secondary p-6">
            <div className="mb-4 flex items-center gap-3">
              <div className="flex h-12 w-12 items-center justify-center rounded-lg bg-accent-soft text-accent-primary">
                <BookOpen size={24} />
              </div>
              <div>
                <h1 className="text-xl font-medium">{selectedSkill.name}</h1>
                <p className="text-sm text-text-secondary">{selectedSkill.description}</p>
              </div>
            </div>

            <div className="prose prose-invert max-w-none">
              <pre className="whitespace-pre-wrap rounded-lg bg-bg-primary p-4 font-mono text-sm text-text-primary">
                {selectedSkill.content}
              </pre>
            </div>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="h-full overflow-y-auto p-6">
      <div className="mx-auto max-w-5xl">
        <div className="mb-6 flex items-center justify-between">
          <div>
            <p className="text-sm text-text-secondary">
              技能知识库 · 按需加载的运维知识指南
            </p>
          </div>
          <Button variant="secondary" onClick={handleReload}>
            <RefreshCw size={14} />
            刷新
          </Button>
        </div>

        {skills.length === 0 ? (
          <div className="rounded-xl border border-dashed border-border-primary py-20 text-center">
            <BookOpen size={36} className="mx-auto mb-3 text-text-tertiary" />
            <p className="text-text-secondary mb-1">暂无技能</p>
            <p className="text-sm text-text-tertiary">在 skills/ 目录下添加 SKILL.md 文件</p>
          </div>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {skills.map((s) => (
              <div
                key={s.name}
                onClick={() => handleSelect(s.name)}
                className="cursor-pointer rounded-xl border border-border-primary bg-bg-secondary p-4 hover:border-accent-primary hover:bg-accent-soft/20 transition-all"
              >
                <div className="flex items-start gap-3 mb-3">
                  <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-status-info/15 text-status-info">
                    <BookOpen size={20} />
                  </div>
                  <div className="min-w-0">
                    <h3 className="font-medium truncate">{s.name}</h3>
                  </div>
                </div>
                <p className="text-sm text-text-secondary line-clamp-2">
                  {s.description}
                </p>
              </div>
            ))}
          </div>
        )}

        {/* 说明卡片 */}
        <div className="mt-8 rounded-xl border border-border-primary bg-accent-soft/30 p-5">
          <div className="flex items-start gap-3">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-accent-soft text-accent-primary">
              <Sparkles size={20} />
            </div>
            <div>
              <h3 className="font-medium mb-1">什么是 Skill？</h3>
              <p className="text-sm text-text-secondary leading-relaxed">
                Skill 是可按需加载的知识技能包。当你在对话中提出相关问题时，
                Agent 会自动调用 <code className="rounded bg-bg-tertiary px-1.5 py-0.5 text-xs">load_skill</code> 工具，
                把对应的技能内容加载到上下文中，指导 AI 更好地完成任务。
              </p>
              <div className="mt-3 space-y-1 text-sm text-text-secondary">
                <p><strong className="text-text-primary">Skill 文件位置：</strong>项目根目录的 <code className="rounded bg-bg-tertiary px-1.5 py-0.5 text-xs">skills/</code> 目录</p>
                <p><strong className="text-text-primary">Skill 文件格式：</strong>每个技能一个子目录，包含 <code className="rounded bg-bg-tertiary px-1.5 py-0.5 text-xs">SKILL.md</code> 文件</p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
