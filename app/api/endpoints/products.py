from fastapi import APIRouter, Depends, status, File, UploadFile, HTTPException

from app.schemas.product import (
    ProductCreate,
    ProductUpdate
)

from app.services.product_service import (
    create_product,
    get_products,
    get_product,
    update_product,
    delete_product
)

from app.core.security import get_current_user
from app.core.database import get_database
from app.utils.upload import save_image


router = APIRouter(
    tags=["Products"]
)


@router.post(
    "",
    status_code=status.HTTP_200_OK
)
async def create(
    data: ProductCreate,
    current_user=Depends(get_current_user),
    db=Depends(get_database)
):
    business_id = str(current_user.get("business_id", ""))
    if not business_id or business_id == "None":
        business_id = str(current_user.get("_id", current_user.get("id", "")))

    product = await create_product(
        db,
        business_id,
        data
    )

    return {
        "success": True,
        "message": "Product created successfully",
        "data": product
    }


@router.get("")
async def list_products(
    current_user=Depends(get_current_user),
    db=Depends(get_database)
):
    business_id = str(current_user.get("business_id", ""))
    if not business_id or business_id == "None":
        business_id = str(current_user.get("_id", current_user.get("id", "")))

    products = await get_products(
        db,
        str(business_id)
    )

    return {
        "success": True,
        "message": "Products fetched successfully",
        "data": products
    }


@router.get("/{product_id}")
async def get_single_product(
    product_id: str,
    current_user=Depends(get_current_user),
    db=Depends(get_database)
):
    business_id = str(current_user.get("business_id", ""))
    if not business_id or business_id == "None":
        business_id = str(current_user.get("_id", current_user.get("id", "")))

    product = await get_product(
        db,
        business_id,
        product_id
    )

    return {
        "success": True,
        "message": "Product fetched successfully",
        "data": product
    }


@router.put("/{product_id}")
async def update(
    product_id: str,
    data: ProductUpdate,
    current_user=Depends(get_current_user),
    db=Depends(get_database)
):
    business_id = str(current_user.get("business_id", ""))
    if not business_id or business_id == "None":
        business_id = str(current_user.get("_id", current_user.get("id", "")))

    product = await update_product(
        db,
        business_id,
        product_id,
        data
    )

    return {
        "success": True,
        "message": "Product updated successfully",
        "data": product
    }


@router.delete("/{product_id}")
async def delete(
    product_id: str,
    current_user=Depends(get_current_user),
    db=Depends(get_database)
):
    business_id = str(current_user.get("business_id", ""))
    if not business_id or business_id == "None":
        business_id = str(current_user.get("_id", current_user.get("id", "")))

    return await delete_product(
        db,
        business_id,
        product_id
    )


@router.post("/upload-image")
async def upload_product_image(
    file: UploadFile = File(...),
    current_user=Depends(get_current_user)
):
    image_url = await save_image(
        file,
        "products"
    )

    return {
        "success": True,
        "message": "Product image uploaded successfully",
        "data": {
            "image_url": image_url
        }
    }
