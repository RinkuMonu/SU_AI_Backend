from datetime import datetime, timezone

from bson import ObjectId
from fastapi import HTTPException

from app.schemas.product import (
    ProductCreate,
    ProductUpdate
)


def serialize_product(product):
    return {
        "id": str(product.get("_id", product.get("id", ""))),
        "business_id": str(product.get("business_id", "")),
        "name": product.get("name", "Product"),
        "description": product.get("description"),
        "price": product["price"],
        "sale_price": product.get("sale_price"),
        "sizes": product.get("sizes", []),
        "colors": product.get("colors", []),
        "stock": product.get("stock", 0),
        "image_url": product.get("image_url"),
        "created_at": product.get("created_at"),
        "updated_at": product.get("updated_at"),
    }


async def create_product(
    db,
    business_id: str,
    data: ProductCreate
):
    collection = db["products"]

    product_data = data.model_dump(
        exclude_none=True
    )

    if (
        product_data.get("sale_price") is not None
        and product_data["sale_price"] > product_data["price"]
    ):
        raise HTTPException(
            status_code=400,
            detail="Sale price cannot be greater than price"
        )

    now = datetime.now(timezone.utc)

    product_data["business_id"] = ObjectId(
        business_id
    )

    product_data["created_at"] = now
    product_data["updated_at"] = now

    result = await collection.insert_one(
        product_data
    )

    product = await collection.find_one({
        "_id": result.inserted_id
    })

    return serialize_product(product)


async def get_products(
    db,
    business_id: str
):
    collection = db["products"]

    cursor = collection.find({
        "business_id": ObjectId(business_id)
    })

    products = []

    async for product in cursor:
        products.append(
            serialize_product(product)
        )

    return products


async def get_product(
    db,
    business_id: str,
    product_id: str
):
    if not ObjectId.is_valid(product_id):
        raise HTTPException(
            status_code=400,
            detail="Invalid product ID"
        )

    product = await db["products"].find_one({
        "_id": ObjectId(product_id),
        "business_id": ObjectId(business_id)
    })

    if not product:
        raise HTTPException(
            status_code=404,
            detail="Product not found"
        )

    return serialize_product(product)


async def update_product(
    db,
    business_id: str,
    product_id: str,
    data: ProductUpdate
):
    if not ObjectId.is_valid(product_id):
        raise HTTPException(
            status_code=400,
            detail="Invalid product ID"
        )

    update_data = data.model_dump(
        exclude_none=True
    )

    if (
        "price" in update_data
        and "sale_price" in update_data
        and update_data["sale_price"] > update_data["price"]
    ):
        raise HTTPException(
            status_code=400,
            detail="Sale price cannot be greater than price"
        )

    existing = await db["products"].find_one({
        "_id": ObjectId(product_id),
        "business_id": ObjectId(business_id)
    })

    if not existing:
        raise HTTPException(
            status_code=404,
            detail="Product not found"
        )

    if "sale_price" in update_data:
        price = update_data.get(
            "price",
            existing["price"]
        )

        if update_data["sale_price"] > price:
            raise HTTPException(
                status_code=400,
                detail="Sale price cannot be greater than price"
            )

    update_data["updated_at"] = (
        datetime.now(timezone.utc)
    )

    await db["products"].update_one(
        {
            "_id": ObjectId(product_id),
            "business_id": ObjectId(business_id)
        },
        {
            "$set": update_data
        }
    )

    updated = await db["products"].find_one({
        "_id": ObjectId(product_id),
        "business_id": ObjectId(business_id)
    })

    return serialize_product(updated)


async def delete_product(
    db,
    business_id: str,
    product_id: str
):
    if not ObjectId.is_valid(product_id):
        raise HTTPException(
            status_code=400,
            detail="Invalid product ID"
        )

    result = await db["products"].delete_one({
        "_id": ObjectId(product_id),
        "business_id": ObjectId(business_id)
    })

    if result.deleted_count == 0:
        raise HTTPException(
            status_code=404,
            detail="Product not found"
        )

    return {
        "success": True,
        "message": "Product deleted successfully"
    }
