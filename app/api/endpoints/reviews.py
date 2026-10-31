from fastapi import APIRouter, Depends, status, Body
from typing import Optional
from bson import ObjectId
from app.core.security import get_current_user
from app.core.database import get_database
from app.schemas.review import ReviewCreate, ReviewUpdate
from app.services.review_service import (
    create_review,
    get_reviews,
    get_review,
    update_review,
    delete_review,
    generate_sample_reviews, generate_sample_reviews_gemini,
    generate_ai_reply,
    serialize_review
)

router = APIRouter()

async def _resolve_business_id(current_user, db) -> str:
    business_id = current_user.get("business_id")
    if business_id and ObjectId.is_valid(str(business_id)):
        return str(business_id)
    user_id = str(current_user.get("id", ""))
    biz = await db["businesses"].find_one({"owner_id": user_id})
    if biz:
        return str(biz["_id"])
    if ObjectId.is_valid(user_id):
        return user_id
    first_biz = await db["businesses"].find_one({})
    if first_biz:
        return str(first_biz["_id"])
    return user_id

@router.post("", status_code=status.HTTP_201_CREATED)
async def create(
    data: ReviewCreate,
    current_user=Depends(get_current_user),
    db=Depends(get_database)
):
    business_id = await _resolve_business_id(current_user, db)
    rev = await create_review(db, business_id, data)
    return {"success": True, "message": "Review created successfully", "data": rev}

@router.get("")
async def list_reviews(
    current_user=Depends(get_current_user),
    db=Depends(get_database)
):
    business_id = await _resolve_business_id(current_user, db)
    reviews = await get_reviews(db, business_id)
    if not reviews:
        # Automatically generate reviews with OpenAI API!
        reviews = await generate_sample_reviews_gemini(db, business_id, count=4)
    return {"success": True, "message": "Reviews fetched successfully", "data": reviews}

@router.post("/generate-ai-reviews")
async def generate_ai_reviews(
    current_user=Depends(get_current_user),
    db=Depends(get_database)
):
    """
    Manually triggers generation of authentic customer reviews using OpenAI API.
    """
    business_id = await _resolve_business_id(current_user, db)
    reviews = await generate_sample_reviews_gemini(db, business_id, count=4)
    return {"success": True, "message": "Reviews generated with OpenAI API", "data": reviews}

@router.get("/{review_id}")
async def get_single_review(
    review_id: str,
    current_user=Depends(get_current_user),
    db=Depends(get_database)
):
    business_id = await _resolve_business_id(current_user, db)
    rev = await get_review(db, business_id, review_id)
    return {"success": True, "message": "Review fetched successfully", "data": rev}

@router.put("/{review_id}")
async def update(
    review_id: str,
    data: ReviewUpdate,
    current_user=Depends(get_current_user),
    db=Depends(get_database)
):
    business_id = await _resolve_business_id(current_user, db)
    if not ObjectId.is_valid(review_id):
        # Create review in DB if it had temporary ID
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        doc = {
            "business_id": ObjectId(business_id) if ObjectId.is_valid(business_id) else business_id,
            "customer_name": "Customer",
            "rating": 5,
            "review_text": "Valued customer feedback",
            "status": data.status or "Replied",
            "reply": data.reply,
            "created_at": now,
            "updated_at": now
        }
        res = await db["reviews"].insert_one(doc)
        doc["_id"] = res.inserted_id
        return {"success": True, "message": "Review saved successfully", "data": serialize_review(doc)}

    rev = await update_review(db, business_id, review_id, data)
    return {"success": True, "message": "Review updated successfully", "data": rev}

@router.delete("/{review_id}")
async def delete(
    review_id: str,
    current_user=Depends(get_current_user),
    db=Depends(get_database)
):
    business_id = await _resolve_business_id(current_user, db)
    return await delete_review(db, business_id, review_id)

@router.post("/{review_id}/generate-reply")
async def generate_reply(
    review_id: str,
    payload: Optional[dict] = Body(None),
    current_user=Depends(get_current_user),
    db=Depends(get_database)
):
    business_id = await _resolve_business_id(current_user, db)
    reply = await generate_ai_reply(db, business_id, review_id, custom_data=payload)
    return {"success": True, "data": reply}

