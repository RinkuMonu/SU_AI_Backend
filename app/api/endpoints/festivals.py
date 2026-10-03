from fastapi import APIRouter, Depends, Body
from app.core.security import get_current_user
from app.core.database import get_database
from app.services.festival_service import (
    get_upcoming_festivals,
    generate_festival_campaign,
    INDIAN_FESTIVALS,
)
from datetime import datetime, timezone, timedelta
from bson import ObjectId
import logging

router = APIRouter(prefix="/festivals", tags=["Festival Engine"])
logger = logging.getLogger(__name__)


async def _resolve_business_id(current_user, db):
    business_id = current_user.get("business_id")
    if business_id:
        return str(business_id)
    user_id = str(current_user.get("id", ""))
    business = await db["businesses"].find_one({"owner_id": user_id})
    if business:
        return str(business["_id"])

    # Auto-create a default dev business so features work during development
    from app.core.config import settings
    if settings.ENVIRONMENT == "development":
        result = await db["businesses"].insert_one({
            "owner_id": user_id,
            "name": "Demo Business",
            "category": "Retail / Fashion",
            "location": "Jaipur, Rajasthan",
            "target_audience": "Men & Women 18-35",
            "brand_tone": "Friendly and professional",
            "language": "Hinglish",
            "auto_publish_enabled": False,
            "autopilot_schedule": {},
        })
        return str(result.inserted_id)
    return None


def _serialize(doc: dict) -> dict:
    doc["id"] = str(doc.pop("_id"))
    if "created_at" in doc and hasattr(doc["created_at"], "isoformat"):
        doc["created_at"] = doc["created_at"].isoformat()
    return doc


@router.get("/upcoming")
async def get_upcoming(
    current_user=Depends(get_current_user),
    db=Depends(get_database),
):
    """
    Returns upcoming festivals and any pre-generated draft campaigns.
    Also returns the list of festivals on the horizon so the frontend
    can show a preview even if no campaign is generated yet.
    """
    business_id = await _resolve_business_id(current_user, db)
    from datetime import date
    today = date.today()
    upcoming_festivals = []
    for f in INDIAN_FESTIVALS:
        fest_date = date.fromisoformat(f["date"])
        upcoming_festivals.append({**f, "days_left": (fest_date - today).days})

    campaigns = []
    if business_id:
        cursor = db["festival_campaigns"].find(
            {"business_id": business_id}
        ).sort("festival_date", 1)
        async for doc in cursor:
            campaigns.append(_serialize(doc))

    return {
        "success": True,
        "data": {
            "upcoming_festivals": upcoming_festivals,
            "campaigns": campaigns,
        },
    }


@router.post("/generate")
async def generate_campaign(
    festival_name: str,
    current_user=Depends(get_current_user),
    db=Depends(get_database),
):
    """
    Manually triggers campaign generation for a specific festival name.
    """
    business_id = await _resolve_business_id(current_user, db)
    if not business_id:
        return {"success": False, "message": "No business profile found."}

    # Find the festival in our list
    from datetime import date
    today = date.today()
    festival = next(
        (f for f in INDIAN_FESTIVALS if f["name"].lower() == festival_name.lower()), None
    )
    if not festival:
        return {"success": False, "message": f"Festival '{festival_name}' not found."}
    
    fest_date = date.fromisoformat(festival["date"])
    festival_with_days = {**festival, "days_left": (fest_date - today).days}

    # Check if already exists
    existing = await db["festival_campaigns"].find_one({
        "business_id": business_id,
        "festival_name": festival_with_days["name"],
        "festival_date": festival_with_days["date"],
    })
    if existing:
        return {"success": True, "message": "Campaign already exists.", "data": _serialize(existing)}

    campaign = await generate_festival_campaign(db, business_id, festival_with_days)
    if not campaign:
        return {"success": False, "message": "AI failed to generate campaign. Please try again."}

    result = await db["festival_campaigns"].insert_one(campaign)
    campaign["id"] = str(result.inserted_id)
    campaign.pop("_id", None)
    if "created_at" in campaign and hasattr(campaign["created_at"], "isoformat"):
        campaign["created_at"] = campaign["created_at"].isoformat()

    return {"success": True, "data": campaign}


@router.post("/{campaign_id}/approve")
async def approve_campaign(
    campaign_id: str,
    current_user=Depends(get_current_user),
    db=Depends(get_database),
):
    """
    User approves a draft campaign. The system:
    1. Marks the campaign as 'approved'
    2. Injects all assets into the `post_queue` for the Autopilot to publish them.
    """
    business_id = await _resolve_business_id(current_user, db)
    if not business_id:
        return {"success": False, "message": "No business profile found."}

    if not ObjectId.is_valid(campaign_id):
        return {"success": False, "message": "Invalid campaign ID."}

    campaign = await db["festival_campaigns"].find_one({
        "_id": ObjectId(campaign_id),
        "business_id": business_id,
    })
    if not campaign:
        return {"success": False, "message": "Campaign not found."}
    if campaign.get("status") == "approved":
        return {"success": True, "message": "Campaign already approved."}

    # Inject each asset into post_queue
    user_id = str(current_user.get("id", ""))
    queue_items = []
    for asset in campaign.get("assets", []):
        scheduled_date_str = asset.get("scheduled_date")
        try:
            from datetime import date
            sched_date = date.fromisoformat(scheduled_date_str)
            scheduled_for = datetime(sched_date.year, sched_date.month, sched_date.day,
                                     9, 0, 0, tzinfo=timezone.utc)
        except Exception:
            scheduled_for = datetime.now(timezone.utc) + timedelta(days=1)

        queue_items.append({
            "business_id": business_id,
            "user_id": user_id,
            "content_id": None,  # Festival campaigns create content inline
            "platform": asset.get("platform", "instagram"),
            "asset_type": asset.get("type"),
            "festival_name": campaign["festival_name"],
            "asset_content": asset.get("content", {}),
            "scheduled_for": scheduled_for,
            "status": "pending",
            "source": "festival_engine",
            "created_at": datetime.now(timezone.utc),
        })

    if queue_items:
        await db["post_queue"].insert_many(queue_items)

    await db["festival_campaigns"].update_one(
        {"_id": ObjectId(campaign_id)},
        {"$set": {"status": "approved"}},
    )

    return {
        "success": True,
        "message": f"🎉 {campaign['festival_name']} campaign approved! {len(queue_items)} posts scheduled.",
    }


@router.delete("/{campaign_id}")
async def delete_campaign(
    campaign_id: str,
    current_user=Depends(get_current_user),
    db=Depends(get_database),
):
    """Delete a draft campaign."""
    business_id = await _resolve_business_id(current_user, db)
    if not business_id or not ObjectId.is_valid(campaign_id):
        return {"success": False, "message": "Invalid request."}

    await db["festival_campaigns"].delete_one({
        "_id": ObjectId(campaign_id),
        "business_id": business_id,
    })
    return {"success": True, "message": "Campaign deleted."}
