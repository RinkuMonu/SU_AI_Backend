from fastapi import APIRouter, Depends
from pydantic import BaseModel
from app.core.security import get_current_user
from app.core.database import get_database
from app.services.agent_service import AgentService
import logging

router = APIRouter(prefix="/agent", tags=["UNI AI Agent"])
logger = logging.getLogger(__name__)
agent_service = AgentService()

class CommandRequest(BaseModel):
    command: str

@router.post("/command")
async def execute_command(
    request: CommandRequest,
    current_user=Depends(get_current_user),
    db=Depends(get_database)
):
    """
    Receives a natural language command (Hindi/Hinglish/English),
    parses the intent, and routes it to the correct AI service.
    """
    user_id = str(current_user.get("id", "")) if isinstance(current_user, dict) else str(getattr(current_user, "id", ""))
    if not user_id:
        return {"success": False, "message": "Unauthorized"}
        
    result = await agent_service.parse_and_execute(db, user_id, request.command)
    return result
