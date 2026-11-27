"""Agent and agent-version REST endpoints."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.security import User, current_user
from app.services.store import Store, get_store

router = APIRouter(prefix="/agents", tags=["agents"])


class AgentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    instructions: str = Field(default="", max_length=20_000)
    tools: list[str] = Field(default_factory=list)


@router.post("", status_code=201)
def create_agent(payload: AgentCreate, user: User = Depends(current_user), store: Store = Depends(get_store)):
    return store.create_agent(user.organization_id, payload.model_dump())


@router.get("")
def list_agents(user: User = Depends(current_user), store: Store = Depends(get_store)):
    return store.list_agents(user.organization_id)


@router.get("/{agent_id}/versions")
def list_versions(agent_id: str, user: User = Depends(current_user), store: Store = Depends(get_store)):
    if not store.agent_exists(agent_id, user.organization_id):
        raise HTTPException(status_code=404, detail="Agent not found")
    return store.list_versions(agent_id, user.organization_id)


@router.post("/{agent_id}/versions", status_code=201)
def create_version(agent_id: str, payload: AgentCreate, user: User = Depends(current_user), store: Store = Depends(get_store)):
    if not store.agent_exists(agent_id, user.organization_id):
        raise HTTPException(status_code=404, detail="Agent not found")
    return store.create_version(agent_id, user.organization_id, payload.model_dump())
