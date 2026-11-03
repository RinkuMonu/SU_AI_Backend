import json
import logging
from typing import Optional, List
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    WebSocket,
    WebSocketDisconnect,
    status
)
from app.core.security import get_current_user, CurrentUser, decode_access_token
from app.schemas.chat import (
    ConversationCreate,
    ConversationResponse,
    ConversationListResponse,
    MessageCreate,
    MessageResponse,
    ReadReceiptResponse
)
from app.services.chat_service import ChatService
from app.services.chat_ws_manager import chat_ws_manager

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Chats & Messaging"])

# =====================================================================
# REST ENDPOINTS FOR BUSINESS-CREATOR MESSAGING
# =====================================================================

@router.get("/conversations", response_model=ConversationListResponse)
async def list_conversations(current_user: CurrentUser = Depends(get_current_user)):
    """
    List all active conversations for the authenticated user.
    If no conversations exist, returns real recommended businesses from MongoDB for discovery.
    """
    user_id = str(current_user.id)
    return await ChatService.list_conversations(user_id)


@router.post("/conversations", response_model=ConversationResponse)
async def create_conversation(
    payload: ConversationCreate,
    current_user: CurrentUser = Depends(get_current_user)
):
    """
    Initiate or retrieve an existing conversation between a business and a creator.
    Prevents duplicate conversations.
    """
    user_id = str(current_user.id)
    conv_doc = await ChatService.get_or_create_conversation(
        current_user_id=user_id,
        target_user_id=payload.target_user_id,
        business_user_id=payload.business_user_id,
        creator_user_id=payload.creator_user_id,
        collaboration_id=payload.collaboration_id,
        campaign_id=payload.campaign_id,
        initial_message=payload.initial_message
    )
    return await ChatService.get_conversation_by_id(str(conv_doc["_id"]), user_id)


@router.get("/conversations/{conversation_id}", response_model=ConversationResponse)
async def get_conversation(
    conversation_id: str,
    current_user: CurrentUser = Depends(get_current_user)
):
    """
    Retrieve details of a single conversation. Enforces strict participant authorization.
    """
    user_id = str(current_user.id)
    return await ChatService.get_conversation_by_id(conversation_id, user_id)


@router.get("/conversations/{conversation_id}/messages", response_model=List[MessageResponse])
async def list_messages(
    conversation_id: str,
    limit: int = Query(50, ge=1, le=100),
    before_id: Optional[str] = Query(None, description="Cursor for pagination"),
    current_user: CurrentUser = Depends(get_current_user)
):
    """
    Retrieve message history for a conversation.
    Strictly verifies user is a participant.
    """
    user_id = str(current_user.id)
    return await ChatService.list_messages(
        conversation_id=conversation_id,
        user_id=user_id,
        limit=limit,
        before_id=before_id
    )


@router.post("/conversations/{conversation_id}/messages", response_model=MessageResponse)
async def send_message(
    conversation_id: str,
    payload: MessageCreate,
    current_user: CurrentUser = Depends(get_current_user)
):
    """
    Send a message within an authorized conversation.
    Persists in MongoDB before reporting success or broadcasting.
    """
    user_id = str(current_user.id)
    raw_attachments = [a.model_dump() for a in payload.attachments]
    return await ChatService.send_message(
        conversation_id=conversation_id,
        sender_id=user_id,
        text=payload.text,
        attachments=raw_attachments,
        message_type=payload.message_type
    )


@router.patch("/conversations/{conversation_id}/read", response_model=ReadReceiptResponse)
async def mark_conversation_read(
    conversation_id: str,
    current_user: CurrentUser = Depends(get_current_user)
):
    """
    Mark all unread incoming messages in a conversation as read.
    Resets the unread count for the current user.
    """
    user_id = str(current_user.id)
    count = await ChatService.mark_messages_read(conversation_id, user_id)
    return ReadReceiptResponse(
        success=True,
        conversation_id=conversation_id,
        unread_count=0,
        message=f"Marked {count} messages as read"
    )


# =====================================================================
# REAL-TIME WEBSOCKET CHANNELS
# =====================================================================

@router.websocket("/ws/{conversation_id}")
async def websocket_conversation_endpoint(
    websocket: WebSocket,
    conversation_id: str,
    token: Optional[str] = Query(None)
):
    """
    Authenticated WebSocket endpoint for real-time conversation messaging.
    Connect with query param: ?token=<jwt_access_token>
    """
    if not token:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    payload = decode_access_token(token)
    if not payload or not payload.get("sub"):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    user_id = str(payload.get("sub"))

    # Verify authorization
    try:
        await ChatService.get_conversation_by_id(conversation_id, user_id)
    except Exception:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await chat_ws_manager.connect(websocket, conversation_id, user_id)

    try:
        while True:
            data_text = await websocket.receive_text()
            try:
                data = json.loads(data_text)
                action = data.get("action")

                if action == "ping":
                    await websocket.send_text(json.dumps({"event": "pong"}))

                elif action == "send_message":
                    text = data.get("text")
                    attachments = data.get("attachments", [])
                    msg_type = data.get("message_type", "text")
                    await ChatService.send_message(
                        conversation_id=conversation_id,
                        sender_id=user_id,
                        text=text,
                        attachments=attachments,
                        message_type=msg_type
                    )

                elif action == "mark_read":
                    await ChatService.mark_messages_read(conversation_id, user_id)

            except json.JSONDecodeError:
                pass
            except Exception as e:
                logger.error(f"Error handling WebSocket message: {e}")
                await websocket.send_text(json.dumps({"event": "error", "detail": str(e)}))

    except WebSocketDisconnect:
        chat_ws_manager.disconnect(websocket, conversation_id, user_id)
    except Exception as e:
        logger.error(f"WebSocket unhandled error: {e}")
        chat_ws_manager.disconnect(websocket, conversation_id, user_id)


@router.websocket("/ws")
async def websocket_global_endpoint(
    websocket: WebSocket,
    token: Optional[str] = Query(None)
):
    """
    Authenticated WebSocket endpoint for global user notifications and unread badges.
    Connect with query param: ?token=<jwt_access_token>
    """
    if not token:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    payload = decode_access_token(token)
    if not payload or not payload.get("sub"):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    user_id = str(payload.get("sub"))
    await chat_ws_manager.connect(websocket, "global", user_id)

    try:
        while True:
            data_text = await websocket.receive_text()
            try:
                data = json.loads(data_text)
                if data.get("action") == "ping":
                    await websocket.send_text(json.dumps({"event": "pong"}))
            except Exception:
                pass
    except WebSocketDisconnect:
        chat_ws_manager.disconnect(websocket, "global", user_id)
    except Exception as e:
        logger.error(f"Global WebSocket error: {e}")
        chat_ws_manager.disconnect(websocket, "global", user_id)
