import { useEffect } from 'react'
import { BookOpen, RefreshCw } from 'lucide-react'
import { useAppStore } from '../store/useAppStore'
import Button from '../components/Button'
import MarkdownText from '../components/MarkdownText'
import {
  SectionLabel,
  WorkspaceEmpty,
  WorkspacePage,
  WorkspacePanel,
} from '../components/Workspace'

export default function Skills() {
  const {
    skills,
    selectedSkill,
    fetchSkills,
    fetchSkillDetail,
    clearSelectedSkill,
  } = useAppStore()

  useEffect(() => {
    fetchSkills()
  }, [fetchSkills])

  const handleReload = async () => {
    await fetchSkills()
    if (selectedSkill) await fetchSkillDetail(selectedSkill.name)
  }

  return (
    <WorkspacePage
      title="技能"
      description="按需加载的运维知识包。完整内容只在相关任务中进入上下文。"
      actions={
        <Button variant="secondary" onClick={handleReload}>
          <RefreshCw size={12} />
          刷新
        </Button>
      }
      wide
    >
      {skills.length === 0 ? (
        <WorkspaceEmpty
          icon={<BookOpen size={17} />}
          title="暂无技能"
          description="在项目 skills/ 目录中添加 SKILL.md 后会出现在这里。"
        />
      ) : (
        <div className="grid gap-4 lg:grid-cols-[300px_minmax(0,1fr)]">
          <WorkspacePanel>
            <div className="flex items-center justify-between border-b border-border-secondary px-4 py-3">
              <SectionLabel>技能列表</SectionLabel>
              <span className="text-[10px] text-text-tertiary">{skills.length}</span>
            </div>
            {skills.map((skill) => (
              <button
                key={skill.name}
                onClick={() => fetchSkillDetail(skill.name)}
                className={`w-full border-b border-border-secondary px-4 py-3 text-left transition-colors last:border-0 ${
                  selectedSkill?.name === skill.name
                    ? 'bg-bg-active'
                    : 'hover:bg-bg-hover'
                }`}
              >
                <div className="flex items-center gap-2">
                  <BookOpen size={13} className="shrink-0 text-text-tertiary" />
                  <span className="truncate text-[12.5px] font-medium">{skill.name}</span>
                </div>
                <p className="mt-1 line-clamp-2 pl-5 text-[11px] leading-5 text-text-tertiary">
                  {skill.description}
                </p>
              </button>
            ))}
          </WorkspacePanel>

          <WorkspacePanel padded className="min-h-[520px]">
            {selectedSkill ? (
              <>
                <div className="flex items-start justify-between gap-3 border-b border-border-secondary pb-4">
                  <div>
                    <SectionLabel>Skill 内容</SectionLabel>
                    <h2 className="mt-2 text-[17px] font-medium tracking-[-0.015em]">{selectedSkill.name}</h2>
                    <p className="mt-1 text-[11.5px] leading-5 text-text-tertiary">{selectedSkill.description}</p>
                  </div>
                  <Button size="sm" variant="ghost" onClick={clearSelectedSkill}>关闭</Button>
                </div>
                <div className="markdown-body mt-5 text-[13px] leading-[1.72] text-text-primary">
                  <MarkdownText text={selectedSkill.content} />
                </div>
              </>
            ) : (
              <WorkspaceEmpty
                icon={<BookOpen size={17} />}
                title="选择一个技能"
                description="可以在这里阅读完整的运维指南。"
              />
            )}
          </WorkspacePanel>
        </div>
      )}
    </WorkspacePage>
  )
}
