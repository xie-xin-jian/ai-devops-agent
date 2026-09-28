from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from agent.skill import SKILL_REGISTRY, scan_skills, list_skills, load_skill
from agent.rbac import SKILL_READ, Principal
from api.auth import require_permissions

router = APIRouter(prefix="/api/skills", tags=["skills"])


class SkillResponse(BaseModel):
    name: str
    description: str


class SkillDetailResponse(SkillResponse):
    content: str


@router.get("")
def list_skills_endpoint(
    _principal: Principal = Depends(require_permissions(SKILL_READ)),
):
    scan_skills()
    skills = [
        {"name": s["name"], "description": s["description"]}
        for s in SKILL_REGISTRY.values()
    ]
    return {"skills": skills, "count": len(skills)}


@router.get("/{name}")
def get_skill_detail(
    name: str,
    _principal: Principal = Depends(require_permissions(SKILL_READ)),
):
    content = load_skill(name)
    skill = SKILL_REGISTRY.get(name)
    if not skill:
        raise HTTPException(status_code=404, detail=content)
    return {"name": name, "description": skill["description"], "content": content}


@router.post("/reload")
def reload_skills(
    _principal: Principal = Depends(require_permissions(SKILL_READ)),
):
    scan_skills()
    return {"message": "Skills reloaded", "count": len(SKILL_REGISTRY)}
