from fastapi import APIRouter, Depends, status
from app.core.security import get_current_user
from app.core.database import get_database
from app.schemas.message import MessageCreate, MessageUpdate
from app.services.message_service import (
    create_message,
    get_messages,
    get_message,
    update_message,
    delete_message
)

router = APIRouter()

@router.post("", status_code=status.HTTP_201_CREATED)
async def create(
    data: MessageCreate,
    current_user=Depends(get_current_user),
    db=Depends(get_database)
):
    business_id = current_user.get("business_id")
    if not business_id:
        business_id = current_user["id"]
    business_id = str(business_id)
    msg = await create_message(db, business_id, data)
    return {"success": True, "message": "Message created successfully", "data": msg}

@router.get("")
async def list_messages(
    current_user=Depends(get_current_user),
    db=Depends(get_database)
):
    business_id = current_user.get("business_id")
    if not business_id:
        business_id = current_user["id"]
    business_id = str(business_id)
    messages = await get_messages(db, business_id)
    return {"success": True, "message": "Messages fetched successfully", "data": messages}

@router.get("/{message_id}")
async def get_single_message(
    message_id: str,
    current_user=Depends(get_current_user),
    db=Depends(get_database)
):
    business_id = current_user.get("business_id")
    if not business_id:
        business_id = current_user["id"]
    business_id = str(business_id)
    msg = await get_message(db, business_id, message_id)
    return {"success": True, "message": "Message fetched successfully", "data": msg}

@router.put("/{message_id}")
async def update(
    message_id: str,
    data: MessageUpdate,
    current_user=Depends(get_current_user),
    db=Depends(get_database)
):
    business_id = current_user.get("business_id")
    if not business_id:
        business_id = current_user["id"]
    business_id = str(business_id)
    msg = await update_message(db, business_id, message_id, data)
    return {"success": True, "message": "Message updated successfully", "data": msg}

@router.delete("/{message_id}")
async def delete(
    message_id: str,
    current_user=Depends(get_current_user),
    db=Depends(get_database)
):
    business_id = current_user.get("business_id")
    if not business_id:
        business_id = current_user["id"]
    business_id = str(business_id)
    return await delete_message(db, business_id, message_id)
