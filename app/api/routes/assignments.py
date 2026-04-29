from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.api.schemas import OutputResponse, SubtopicRequest
from app.core.auth import require_user
from app.crews.assignment_crew.crew import generate_assignment, revise_assignment

router = APIRouter()


class ReviseRequest(BaseModel):
    content: str = Field(..., min_length=1)
    subtopic: str = Field(..., min_length=1)
    changes: str = Field(..., min_length=1)


class EvaluateOutputResponse(OutputResponse):
    threadId: str | None = None


@router.post("/generate", response_model=OutputResponse)
async def generate(payload: SubtopicRequest, _user=Depends(require_user)) -> OutputResponse:
    try:
        markdown = await generate_assignment(payload.subtopic)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"assignment generation failed: {exc}",
        ) from exc
    return OutputResponse(output=markdown)


@router.post("/revise", response_model=OutputResponse)
async def revise(payload: ReviseRequest, _user=Depends(require_user)) -> OutputResponse:
    try:
        markdown = await revise_assignment(
            subtopic=payload.subtopic,
            content=payload.content,
            changes=payload.changes,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"assignment revision failed: {exc}",
        ) from exc
    return OutputResponse(output=markdown)
