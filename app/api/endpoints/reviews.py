from fastapi import APIRouter, Depends, status
from app.core.security import get_current_user
from app.core.database import get_database
from app.schemas.review import ReviewCreate, ReviewUpdate
from app.services.review_service import (
    create_review,
    get_reviews,
    get_review,
    update_review,
    delete_review
)

router = APIRouter()

@router.post("", status_code=status.HTTP_201_CREATED)
async def create(
    data: ReviewCreate,
    current_user=Depends(get_current_user),
    db=Depends(get_database)
):
    business_id = current_user.get("business_id")
    if not business_id:
        business_id = current_user["id"]
    business_id = str(business_id)
    rev = await create_review(db, business_id, data)
    return {"success": True, "message": "Review created successfully", "data": rev}

@router.get("")
async def list_reviews(
    current_user=Depends(get_current_user),
    db=Depends(get_database)
):
    business_id = current_user.get("business_id")
    if not business_id:
        business_id = current_user["id"]
    business_id = str(business_id)
    reviews = await get_reviews(db, business_id)
    return {"success": True, "message": "Reviews fetched successfully", "data": reviews}

@router.get("/{review_id}")
async def get_single_review(
    review_id: str,
    current_user=Depends(get_current_user),
    db=Depends(get_database)
):
    business_id = current_user.get("business_id")
    if not business_id:
        business_id = current_user["id"]
    business_id = str(business_id)
    rev = await get_review(db, business_id, review_id)
    return {"success": True, "message": "Review fetched successfully", "data": rev}

@router.put("/{review_id}")
async def update(
    review_id: str,
    data: ReviewUpdate,
    current_user=Depends(get_current_user),
    db=Depends(get_database)
):
    business_id = current_user.get("business_id")
    if not business_id:
        business_id = current_user["id"]
    business_id = str(business_id)
    rev = await update_review(db, business_id, review_id, data)
    return {"success": True, "message": "Review updated successfully", "data": rev}

@router.delete("/{review_id}")
async def delete(
    review_id: str,
    current_user=Depends(get_current_user),
    db=Depends(get_database)
):
    business_id = current_user.get("business_id")
    if not business_id:
        business_id = current_user["id"]
    business_id = str(business_id)
    return await delete_review(db, business_id, review_id)

@router.post("/{review_id}/generate-reply")
async def generate_reply(
    review_id: str,
    current_user=Depends(get_current_user),
    db=Depends(get_database)
):
    from app.services.review_service import generate_ai_reply
    business_id = current_user.get("business_id")
    if not business_id:
        business_id = current_user["id"]
    business_id = str(business_id)
    reply = await generate_ai_reply(db, business_id, review_id)
    return {"success": True, "data": reply}
