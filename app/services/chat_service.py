import logging
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from bson import ObjectId
from fastapi import HTTPException, status

from app.core.database import get_database
from app.schemas.chat import (
    ConversationResponse,
    MessageResponse,
    ParticipantSummary,
    RecommendedBusiness,
    AttachmentMetadata
)
from app.services.chat_ws_manager import chat_ws_manager

logger = logging.getLogger(__name__)

class ChatService:
    @staticmethod
    async def _get_participant_details(db, user_id: str) -> ParticipantSummary:
        """Fetch real user/business/influencer profile details for conversation header."""
        name = "User"
        username = None
        avatar = ""
        role = "user"

        if ObjectId.is_valid(user_id):
            u = await db["users"].find_one({"_id": ObjectId(user_id)})
        else:
            u = await db["users"].find_one({"$or": [{"_id": user_id}, {"id": user_id}]})

        if u:
            name = u.get("name") or u.get("fullName") or u.get("username") or f"User {str(user_id)[-4:]}"
            username = u.get("username")
            avatar = u.get("profileImageUrl") or u.get("image") or ""
            role = u.get("role") or "user"

        # If influencer, enrich with influencer profile
        inf = await db["influencer_profiles"].find_one({"user_id": str(user_id)})
        if inf:
            name = inf.get("full_name") or inf.get("fullName") or name
            username = inf.get("username") or username
            avatar = inf.get("profile_image") or inf.get("profileImageUrl") or avatar
            role = "influencer"

        # If business owner, enrich with business info
        biz = await db["businesses"].find_one({"$or": [{"owner_id": str(user_id)}, {"ownerId": str(user_id)}, {"user_id": str(user_id)}]})
        if biz:
            if not inf:  # Prefer business name if primarily a business
                name = biz.get("name") or biz.get("business_name") or name
                avatar = biz.get("logo") or biz.get("logo_url") or avatar
                role = "business"

        return ParticipantSummary(
            user_id=str(user_id),
            name=name,
            username=username,
            avatar=avatar,
            role=role
        )

    @classmethod
    async def get_or_create_conversation(
        cls,
        current_user_id: str,
        target_user_id: Optional[str] = None,
        business_user_id: Optional[str] = None,
        creator_user_id: Optional[str] = None,
        collaboration_id: Optional[str] = None,
        campaign_id: Optional[str] = None,
        initial_message: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Creates or retrieves an existing conversation between a business and a creator.
        Prevents duplicate conversations.
        """
        db = get_database()
        now = datetime.now(timezone.utc)

        # 1. Resolve participants
        b_id = business_user_id
        c_id = creator_user_id

        if not b_id or not c_id:
            if not target_user_id:
                raise HTTPException(status_code=400, detail="Must provide target_user_id or both business_user_id and creator_user_id")
            
            # Determine roles
            curr_user_doc = None
            if ObjectId.is_valid(current_user_id):
                curr_user_doc = await db["users"].find_one({"_id": ObjectId(current_user_id)})
            
            curr_role = (curr_user_doc.get("role") if curr_user_doc else "") or ""
            
            if curr_role in ["influencer", "creator"]:
                c_id = current_user_id
                b_id = target_user_id
            else:
                b_id = current_user_id
                c_id = target_user_id

        # Current user must be one of the participants
        if current_user_id not in [b_id, c_id]:
            raise HTTPException(status_code=403, detail="Cannot create conversation for other users")

        if b_id == c_id:
            raise HTTPException(status_code=400, detail="Cannot start a conversation with yourself")

        # 2. Check for existing conversation
        query: Dict[str, Any] = {
            "$or": [
                {"business_user_id": b_id, "creator_user_id": c_id},
                {"business_user_id": c_id, "creator_user_id": b_id}
            ]
        }
        if collaboration_id:
            query["collaboration_id"] = collaboration_id

        existing = await db["conversations"].find_one(query)
        if existing:
            # If conversation was archived, reactivate it
            if existing.get("status") == "archived":
                await db["conversations"].update_one(
                    {"_id": existing["_id"]},
                    {"$set": {"status": "active", "updated_at": now}}
                )
                existing["status"] = "active"
            return existing

        # 3. Create new conversation document
        new_conv = {
            "business_user_id": b_id,
            "creator_user_id": c_id,
            "collaboration_id": collaboration_id,
            "campaign_id": campaign_id,
            "last_message": initial_message or "",
            "last_message_at": now if initial_message else None,
            "unread_counts": {b_id: 0, c_id: 0},
            "status": "active",
            "created_at": now,
            "updated_at": now
        }

        res = await db["conversations"].insert_one(new_conv)
        new_conv["_id"] = res.inserted_id

        # If initial message provided, save it
        if initial_message:
            recipient_id = c_id if current_user_id == b_id else b_id
            msg_doc = {
                "conversation_id": str(res.inserted_id),
                "sender_id": current_user_id,
                "message_type": "text",
                "text": initial_message,
                "attachments": [],
                "read": False,
                "created_at": now
            }
            await db["conversation_messages"].insert_one(msg_doc)
            await db["conversations"].update_one(
                {"_id": res.inserted_id},
                {"$inc": {f"unread_counts.{recipient_id}": 1}}
            )
            new_conv["unread_counts"][recipient_id] = 1

        return new_conv

    @classmethod
    async def list_conversations(cls, user_id: str) -> Dict[str, Any]:
        """
        List all active conversations for the authenticated user.
        If empty, includes recommended businesses from MongoDB.
        """
        db = get_database()
        cursor = db["conversations"].find({
            "$or": [{"business_user_id": user_id}, {"creator_user_id": user_id}],
            "status": {"$ne": "deleted"}
        }).sort("updated_at", -1)

        convs = await cursor.to_list(length=100)
        formatted_list: List[ConversationResponse] = []
        unread_total = 0

        for c in convs:
            conv_id = str(c["_id"])
            unread_dict = c.get("unread_counts") or {}
            user_unread = unread_dict.get(user_id, 0)
            unread_total += user_unread

            other_user_id = c["creator_user_id"] if c["business_user_id"] == user_id else c["business_user_id"]
            other_summary = await cls._get_participant_details(db, other_user_id)

            formatted_list.append(ConversationResponse(
                id=conv_id,
                business_user_id=c.get("business_user_id", ""),
                creator_user_id=c.get("creator_user_id", ""),
                collaboration_id=c.get("collaboration_id"),
                campaign_id=c.get("campaign_id"),
                last_message=c.get("last_message"),
                last_message_at=c["last_message_at"].isoformat() if c.get("last_message_at") else None,
                unread_counts=unread_dict,
                unread_count=user_unread,
                status=c.get("status", "active"),
                created_at=c["created_at"].isoformat() if c.get("created_at") else datetime.now(timezone.utc).isoformat(),
                updated_at=c["updated_at"].isoformat() if c.get("updated_at") else datetime.now(timezone.utc).isoformat(),
                other_participant=other_summary
            ))

        recommended: List[RecommendedBusiness] = []
        if not formatted_list:
            recommended = await cls.get_recommended_businesses(limit=5)

        return {
            "success": True,
            "data": formatted_list,
            "recommended_businesses": recommended,
            "unread_total": unread_total
        }

    @classmethod
    async def get_conversation_by_id(cls, conversation_id: str, user_id: str) -> ConversationResponse:
        """Retrieve conversation by ID and verify user authorization."""
        db = get_database()
        if not ObjectId.is_valid(conversation_id):
            raise HTTPException(status_code=400, detail="Invalid conversation ID format")

        conv = await db["conversations"].find_one({"_id": ObjectId(conversation_id)})
        if not conv:
            raise HTTPException(status_code=404, detail="Conversation not found")

        # Security check: User must be a participant
        if user_id not in [conv.get("business_user_id"), conv.get("creator_user_id")]:
            raise HTTPException(status_code=403, detail="You are not authorized to view this conversation")

        other_user_id = conv["creator_user_id"] if conv["business_user_id"] == user_id else conv["business_user_id"]
        other_summary = await cls._get_participant_details(db, other_user_id)
        unread_dict = conv.get("unread_counts") or {}

        return ConversationResponse(
            id=str(conv["_id"]),
            business_user_id=conv.get("business_user_id", ""),
            creator_user_id=conv.get("creator_user_id", ""),
            collaboration_id=conv.get("collaboration_id"),
            campaign_id=conv.get("campaign_id"),
            last_message=conv.get("last_message"),
            last_message_at=conv["last_message_at"].isoformat() if conv.get("last_message_at") else None,
            unread_counts=unread_dict,
            unread_count=unread_dict.get(user_id, 0),
            status=conv.get("status", "active"),
            created_at=conv["created_at"].isoformat() if conv.get("created_at") else datetime.now(timezone.utc).isoformat(),
            updated_at=conv["updated_at"].isoformat() if conv.get("updated_at") else datetime.now(timezone.utc).isoformat(),
            other_participant=other_summary
        )

    @classmethod
    async def list_messages(
        cls,
        conversation_id: str,
        user_id: str,
        limit: int = 50,
        before_id: Optional[str] = None
    ) -> List[MessageResponse]:
        """Fetch chronological messages for a conversation, after verifying membership."""
        db = get_database()
        if not ObjectId.is_valid(conversation_id):
            raise HTTPException(status_code=400, detail="Invalid conversation ID format")

        conv = await db["conversations"].find_one({"_id": ObjectId(conversation_id)})
        if not conv:
            raise HTTPException(status_code=404, detail="Conversation not found")

        if user_id not in [conv.get("business_user_id"), conv.get("creator_user_id")]:
            raise HTTPException(status_code=403, detail="You are not authorized to view messages in this conversation")

        query: Dict[str, Any] = {"conversation_id": conversation_id}
        if before_id and ObjectId.is_valid(before_id):
            query["_id"] = {"$lt": ObjectId(before_id)}

        cursor = db["conversation_messages"].find(query).sort("created_at", -1).limit(limit)
        docs = await cursor.to_list(length=limit)
        docs.reverse()  # Return in chronological order

        results: List[MessageResponse] = []
        for d in docs:
            results.append(MessageResponse(
                id=str(d["_id"]),
                conversation_id=str(d["conversation_id"]),
                sender_id=str(d["sender_id"]),
                sender_role=d.get("sender_role"),
                message_type=d.get("message_type", "text"),
                text=d.get("text", ""),
                attachments=[AttachmentMetadata(**a) for a in d.get("attachments", [])],
                read=d.get("read", False),
                read_at=d["read_at"].isoformat() if d.get("read_at") else None,
                created_at=d["created_at"].isoformat() if d.get("created_at") else datetime.now(timezone.utc).isoformat()
            ))

        return results

    @classmethod
    async def send_message(
        cls,
        conversation_id: str,
        sender_id: str,
        text: Optional[str] = None,
        attachments: Optional[List[Dict[str, Any]]] = None,
        message_type: str = "text"
    ) -> MessageResponse:
        """
        Saves a message in MongoDB first, updates conversation state,
        then broadcasts to real-time WebSocket connections.
        """
        db = get_database()
        now = datetime.now(timezone.utc)

        if not ObjectId.is_valid(conversation_id):
            raise HTTPException(status_code=400, detail="Invalid conversation ID")

        conv = await db["conversations"].find_one({"_id": ObjectId(conversation_id)})
        if not conv:
            raise HTTPException(status_code=404, detail="Conversation not found")

        # Security check: Sender must be a participant
        b_id = conv.get("business_user_id")
        c_id = conv.get("creator_user_id")
        if sender_id not in [b_id, c_id]:
            raise HTTPException(status_code=403, detail="You are not a participant in this conversation")

        # Validation
        cleaned_text = (text or "").strip()
        attachment_list = attachments or []
        if not cleaned_text and not attachment_list:
            raise HTTPException(status_code=400, detail="Message text or attachments required")

        if len(cleaned_text) > 4000:
            raise HTTPException(status_code=400, detail="Message text exceeds 4000 characters limit")

        recipient_id = c_id if sender_id == b_id else b_id
        sender_role = "business" if sender_id == b_id else "influencer"

        # 1. Persist message in MongoDB FIRST
        msg_doc = {
            "conversation_id": conversation_id,
            "sender_id": sender_id,
            "sender_role": sender_role,
            "message_type": message_type,
            "text": cleaned_text,
            "attachments": attachment_list,
            "read": False,
            "read_at": None,
            "created_at": now
        }

        try:
            insert_result = await db["conversation_messages"].insert_one(msg_doc)
            msg_id = str(insert_result.inserted_id)
        except Exception as e:
            logger.error(f"Failed to persist message to database: {e}")
            raise HTTPException(status_code=500, detail="Database failure saving message")

        # 2. Update conversation record
        summary_text = cleaned_text or ("[Attachment]" if attachment_list else "")
        await db["conversations"].update_one(
            {"_id": ObjectId(conversation_id)},
            {
                "$set": {
                    "last_message": summary_text,
                    "last_message_at": now,
                    "updated_at": now
                },
                "$inc": {f"unread_counts.{recipient_id}": 1}
            }
        )

        resp = MessageResponse(
            id=msg_id,
            conversation_id=conversation_id,
            sender_id=sender_id,
            sender_role=sender_role,
            message_type=message_type,
            text=cleaned_text,
            attachments=[AttachmentMetadata(**a) for a in attachment_list],
            read=False,
            created_at=now.isoformat()
        )

        # 3. Broadcast to WebSocket rooms
        event_payload = {
            "event": "new_message",
            "conversation_id": conversation_id,
            "message": resp.model_dump()
        }
        await chat_ws_manager.broadcast_to_conversation(conversation_id, event_payload)
        await chat_ws_manager.send_to_user(recipient_id, {
            "event": "unread_update",
            "conversation_id": conversation_id,
            "sender_id": sender_id,
            "preview": summary_text
        })

        return resp

    @classmethod
    async def mark_messages_read(cls, conversation_id: str, user_id: str) -> int:
        """Mark all unread incoming messages as read and reset unread count."""
        db = get_database()
        now = datetime.now(timezone.utc)

        if not ObjectId.is_valid(conversation_id):
            raise HTTPException(status_code=400, detail="Invalid conversation ID")

        conv = await db["conversations"].find_one({"_id": ObjectId(conversation_id)})
        if not conv:
            raise HTTPException(status_code=404, detail="Conversation not found")

        if user_id not in [conv.get("business_user_id"), conv.get("creator_user_id")]:
            raise HTTPException(status_code=403, detail="Not authorized to modify this conversation")

        # Update incoming unread messages
        res = await db["conversation_messages"].update_many(
            {
                "conversation_id": conversation_id,
                "sender_id": {"$ne": user_id},
                "read": False
            },
            {
                "$set": {"read": True, "read_at": now}
            }
        )

        # Reset unread count for user in conversation
        await db["conversations"].update_one(
            {"_id": ObjectId(conversation_id)},
            {"$set": {f"unread_counts.{user_id}": 0, "updated_at": now}}
        )

        # Notify via WebSocket
        other_user_id = conv["creator_user_id"] if conv["business_user_id"] == user_id else conv["business_user_id"]
        await chat_ws_manager.broadcast_to_conversation(conversation_id, {
            "event": "messages_read",
            "conversation_id": conversation_id,
            "read_by": user_id,
            "read_at": now.isoformat()
        })
        await chat_ws_manager.send_to_user(other_user_id, {
            "event": "read_receipt",
            "conversation_id": conversation_id
        })

        return res.modified_count

    @classmethod
    async def get_unread_message_count(cls, user_id: str) -> int:
        """Sum of all unread messages for this user across all conversations."""
        db = get_database()
        cursor = db["conversations"].find({
            "$or": [{"business_user_id": user_id}, {"creator_user_id": user_id}],
            "status": "active"
        })
        convs = await cursor.to_list(length=200)
        total = 0
        for c in convs:
            unread_dict = c.get("unread_counts") or {}
            total += unread_dict.get(user_id, 0)
        return total

    @classmethod
    async def get_recommended_businesses(cls, limit: int = 5) -> List[RecommendedBusiness]:
        """Fetch actual eligible business records from MongoDB for empty inbox discovery."""
        db = get_database()
        cursor = db["businesses"].find({
            "$or": [
                {"name": {"$exists": True, "$ne": ""}},
                {"business_name": {"$exists": True, "$ne": ""}}
            ]
        }).limit(limit)

        biz_docs = await cursor.to_list(length=limit)
        results: List[RecommendedBusiness] = []
        for b in biz_docs:
            biz_name = b.get("name") or b.get("business_name") or "Verified Partner Brand"
            results.append(RecommendedBusiness(
                id=str(b["_id"]),
                name=biz_name,
                category=b.get("category") or b.get("industry") or "Retail & E-commerce",
                logo=b.get("logo") or b.get("logo_url") or "",
                location=b.get("city") or b.get("location") or "India",
                description=b.get("description") or f"Collaborate with {biz_name} on active campaigns."
            ))

        return results
