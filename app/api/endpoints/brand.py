from fastapi import APIRouter, Depends, status, File, UploadFile

from app.schemas.brand import (
    BrandCreate,
    BrandUpdate
)

from app.services.brand_service import (
    create_brand_kit,
    get_brand_kit,
    update_brand_kit
)

from app.core.security import get_current_user
from app.core.database import get_database
from app.utils.upload import save_image


router = APIRouter(
    tags=["Brand Kit"]
)


@router.post(
    "",
    status_code=status.HTTP_200_OK
)
async def create_brand(
    data: BrandCreate,
    current_user=Depends(get_current_user),
    db=Depends(get_database)
):
    business_id = str(current_user.get("business_id"))
    if business_id == "None" or not business_id:
        # Developer mode fallback: use user's ID as the business ID to prevent 400 Bad Request
        business_id = str(current_user.get("_id", current_user.get("id", "")))

    brand = await create_brand_kit(
        db,
        business_id,
        data
    )

    return {
        "success": True,
        "message": "Brand Kit created successfully",
        "data": brand
    }


@router.get("")
async def get_brand(
    current_user=Depends(get_current_user),
    db=Depends(get_database)
):
    business_id = str(current_user.get("business_id"))
    if business_id == "None" or not business_id:
        business_id = str(current_user.get("_id", current_user.get("id", "")))

    brand = await get_brand_kit(
        db,
        business_id
    )

    return {
        "success": True,
        "message": "Brand Kit fetched successfully",
        "data": brand
    }


@router.put("")
async def update_brand(
    data: BrandUpdate,
    current_user=Depends(get_current_user),
    db=Depends(get_database)
):
    business_id = str(current_user.get("business_id"))
    if business_id == "None" or not business_id:
        business_id = str(current_user.get("_id", current_user.get("id", "")))

    brand = await update_brand_kit(
        db,
        business_id,
        data
    )

    return {
        "success": True,
        "message": "Brand Kit updated successfully",
        "data": brand
    }


@router.post("/upload-logo")
async def upload_brand_logo(
    file: UploadFile = File(...),
    current_user=Depends(get_current_user)
):
    logo_url = await save_image(
        file,
        "brand"
    )

    return {
        "success": True,
        "message": "Brand logo uploaded successfully",
        "data": {
            "logo_url": logo_url
        }
    }
