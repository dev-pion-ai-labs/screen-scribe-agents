import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.api.schemas import OutputResponse, SubtopicRequest
from app.core.auth import require_user
from app.crews.assignment_crew.crew import generate_assignment, revise_assignment
from app.crews.evaluator_crew.crew import evaluate_submission
from app.services.file_fetch import fetch_pdf_text

router = APIRouter()


class ReviseRequest(BaseModel):
    content: str = Field(..., min_length=1)
    subtopic: str = Field(..., min_length=1)
    changes: str = Field(..., min_length=1)


class EvaluateRequest(BaseModel):
    criteria: str = Field(..., min_length=1)
    subtopic: str = Field(..., min_length=1)
    file_url: str = Field(..., min_length=1)


class EvaluateResponse(OutputResponse):
    threadId: str


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


@router.post("/evaluate", response_model=EvaluateResponse)
async def evaluate(payload: EvaluateRequest, _user=Depends(require_user)) -> EvaluateResponse:
    try:
        submission_text = await fetch_pdf_text(payload.file_url)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"could not fetch or extract submission: {exc}",
        ) from exc

    if not submission_text:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="submission PDF appears to be empty or non-extractable",
        )

    try:
        markdown = await evaluate_submission(
            criteria=payload.criteria,
            subtopic=payload.subtopic,
            submission_text=submission_text,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"submission evaluation failed: {exc}",
        ) from exc

    return EvaluateResponse(output=markdown, threadId=f"thread_{uuid.uuid4().hex[:24]}")
