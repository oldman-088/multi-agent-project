"""Replayable per-run event stream and tool approval endpoints."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.security import User, current_user
from app.services.store import Store, get_store

router = APIRouter(prefix="/runs", tags=["events"])


class ToolApprovalRequest(BaseModel):
    tool_name: str = Field(min_length=1, max_length=120)
    arguments: dict = Field(default_factory=dict)


@router.get("/{run_id}/events")
def get_events(run_id: str, after_sequence: int = 0, user: User = Depends(current_user), store: Store = Depends(get_store)):
    if after_sequence < 0:
        raise HTTPException(status_code=422, detail="after_sequence must be non-negative")
    if not store.run_exists(run_id, user.organization_id):
        raise HTTPException(status_code=404, detail="Run not found")
    return {"events": store.events_after(run_id, after_sequence), "next_sequence": store.last_sequence(run_id)}


@router.post("/{run_id}/tool-approvals", status_code=201)
def request_tool_approval(run_id: str, payload: ToolApprovalRequest, user: User = Depends(current_user), store: Store = Depends(get_store)):
    if not store.run_exists(run_id, user.organization_id):
        raise HTTPException(status_code=404, detail="Run not found")
    approval = store.add_approval(run_id, user.organization_id, payload.tool_name, payload.arguments)
    return approval


@router.post("/{run_id}/approvals/{approval_id}")
def approve_tool(run_id: str, approval_id: str, user: User = Depends(current_user), store: Store = Depends(get_store)):
    if not store.run_exists(run_id, user.organization_id):
        raise HTTPException(status_code=404, detail="Run not found")
    approval = store.resolve_approval(run_id, approval_id, user.organization_id)
    if approval is None:
        raise HTTPException(status_code=404, detail="Approval not found")
    return approval
