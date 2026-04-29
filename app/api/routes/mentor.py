from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.api.schemas import OutputResponse
from app.core.auth import require_user
from app.crews.mentor_crew.crew import mentor_chat

router = APIRouter()


class ChatRequest(BaseModel):
    chatInput: str = Field(..., min_length=1)
    sessionId: str | None = None


@router.post("/chat", response_model=OutputResponse)
async def chat(payload: ChatRequest, _user=Depends(require_user)) -> OutputResponse:
    try:
        response = await mentor_chat(
            chat_input=payload.chatInput,
            session_id=payload.sessionId,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"mentor chat failed: {exc}",
        ) from exc
    return OutputResponse(output=response)
