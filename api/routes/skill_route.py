from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from agent.skill import SKILL_REGISTRY, scan_skills, list_skills, load_skill

router = APIRouter(prefix="/api/skills", tags=["skills"])


class SkillResponse(BaseModel):
    name: str
    description: str


class SkillDetailResponse(SkillResponse):
    content: str


@router.get("")
def list_skills_endpoint():
    scan_skills()
    skills = [
        {"name": s["name"], "description": s["description"]}
        for s in SKILL_REGISTRY.values()
    ]
    return {"skills": skills, "count": len(skills)}


@router.get("/{name}")
def get_skill_detail(name: str):
    content = load_skill(name)
    skill = SKILL_REGISTRY.get(name)
    if not skill:
        raise HTTPException(status_code=404, detail=content)
    return {"name": name, "description": skill["description"], "content": content}


@router.post("/reload")
def reload_skills():
    scan_skills()
    return {"message": "Skills reloaded", "count": len(SKILL_REGISTRY)}
