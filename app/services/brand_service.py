from datetime import datetime, timezone

from fastapi import HTTPException, status
from bson import ObjectId

from app.schemas.brand import BrandCreate, BrandUpdate


def serialize_brand(brand: dict) -> dict:
    return {
        "id": str(brand["_id"]),
        "business_id": str(brand["business_id"]),
        "logo_url": brand.get("logo_url"),
        "primary_color": brand.get("primary_color"),
        "secondary_color": brand.get("secondary_color"),
        "font": brand.get("font"),
        "tone": brand.get("tone"),
        "brand_description": brand.get("brand_description"),
        "target_audience": brand.get("target_audience"),
        "website": brand.get("website"),
        "instagram": brand.get("instagram"),
        "contact": brand.get("contact"),
        "location": brand.get("location"),
        "social_style": brand.get("social_style"),
        "created_at": brand.get("created_at"),
        "updated_at": brand.get("updated_at"),
    }


async def create_brand_kit(db, business_id: str, data: BrandCreate):
    if not business_id or business_id == "None" or not ObjectId.is_valid(business_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You must create a business before creating a brand kit"
        )
        
    collection = db["brand_kits"]

    existing = await collection.find_one({
        "business_id": ObjectId(business_id)
    })

    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Brand Kit already exists for this business"
        )

    now = datetime.now(timezone.utc)

    brand_data = data.model_dump(mode="json", exclude_none=True)

    brand_data["business_id"] = ObjectId(business_id)
    brand_data["created_at"] = now
    brand_data["updated_at"] = now

    result = await collection.insert_one(brand_data)

    created = await collection.find_one({
        "_id": result.inserted_id
    })

    return serialize_brand(created)


async def get_brand_kit(db, business_id: str):
    if not business_id or business_id == "None" or not ObjectId.is_valid(business_id):
        return None

    collection = db["brand_kits"]

    brand = await collection.find_one({
        "business_id": ObjectId(business_id)
    })

    if not brand:
        return None

    return serialize_brand(brand)


async def update_brand_kit(
    db,
    business_id: str,
    data: BrandUpdate
):
    if not business_id or business_id == "None" or not ObjectId.is_valid(business_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Brand Kit not found"
        )
        
    collection = db["brand_kits"]

    update_data = data.model_dump(
        mode="json",
        exclude_none=True
    )

    if not update_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No fields provided for update"
        )

    update_data["updated_at"] = datetime.now(timezone.utc)

    # Use upsert=True so if a Brand Kit doesn't exist yet, it is automatically created!
    result = await collection.find_one_and_update(
        {
            "business_id": ObjectId(business_id)
        },
        {
            "$set": update_data,
            "$setOnInsert": {"created_at": datetime.now(timezone.utc)}
        },
        upsert=True,
        return_document=True
    )

    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Brand Kit not found"
        )

    return serialize_brand(result)
