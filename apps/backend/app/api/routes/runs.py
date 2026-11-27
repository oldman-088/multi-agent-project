"""Run creation and chat message submission."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.security import User, current_user
from app.services.store import Store, get_store

router = APIRouter(prefix="/runs", tags=["runs"])


class RunCreate(BaseModel):
    agent_id: str


class MessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=100_000)


@router.post("", status_code=201)
def create_run(payload: RunCreate, user: User = Depends(current_user), store: Store = Depends(get_store)):
    if not store.agent_exists(payload.agent_id, user.organization_id):
        raise HTTPException(status_code=404, detail="Agent not found")
    return store.create_run(user.organization_id, payload.agent_id)


@router.post("/{run_id}/messages", status_code=202)
def send_message(run_id: str, payload: MessageCreate, user: User = Depends(current_user), store: Store = Depends(get_store)):
    if not store.run_exists(run_id, user.organization_id):
        raise HTTPException(status_code=404, detail="Run not found")
    return store.append_event(run_id, user.organization_id, "message", {"content": payload.content})
