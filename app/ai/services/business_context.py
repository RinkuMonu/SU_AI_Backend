from typing import Dict, Any, Optional
from bson import ObjectId
from app.services.business_service import BusinessService
from app.services.brand_service import get_brand_kit
from app.services.product_service import get_products
from app.core.database import get_database


class BusinessContextService:
    @classmethod
    async def get_business_context(
        cls,
        business_id: str,
        user_id: Optional[str] = None,
        db: Optional[Any] = None
    ) -> Dict[str, Any]:
        """
        Gathers verified business, brand kit, and catalog product data to build
        a rich, factual context without inventing missing business information.
        """
        if db is None:
            try:
                db = get_database()
            except Exception:
                db = None

        business = None
        target_owner = user_id or (business_id if business_id != "default" else None)

        if db is not None:
            # 1. Look up business by business_id or owner_id
            if business_id and business_id != "default":
                try:
                    if ObjectId.is_valid(business_id):
                        biz_doc = await db["businesses"].find_one({"_id": ObjectId(business_id)})
                    else:
                        biz_doc = await db["businesses"].find_one({"_id": business_id})
                    if not biz_doc:
                        biz_doc = await db["businesses"].find_one({"id": business_id})
                    if biz_doc:
                        business = biz_doc
                except Exception:
                    business = None

            if not business and target_owner:
                try:
                    biz_doc = await db["businesses"].find_one({"owner_id": target_owner})
                    if not biz_doc:
                        biz_doc = await db["businesses"].find_one({
                            "$or": [
                                {"owner_id": target_owner},
                                {"ownerId": target_owner},
                                {"userId": target_owner},
                                {"user_id": target_owner}
                            ]
                        })
                    if biz_doc:
                        business = biz_doc
                except Exception:
                    business = None

        # Factual business fields — do NOT invent or hallucinate missing data
        if business:
            if isinstance(business, dict):
                business_name = business.get("name") or business.get("business_name")
                business_category = business.get("category") or business.get("industry")
                business_location = business.get("location")
                business_target_customer = business.get("target_customer") or business.get("targetCustomer")
                business_language = business.get("preferred_language") or "en"
                business_description = business.get("description")
                effective_biz_id = str(business.get("_id") or business.get("id") or target_owner)
            else:
                business_name = getattr(business, "name", None)
                business_category = getattr(business, "category", None)
                business_location = getattr(business, "location", None)
                business_target_customer = getattr(business, "target_customer", None)
                business_language = getattr(business, "preferred_language", None) or "en"
                business_description = getattr(business, "description", None)
                effective_biz_id = str(getattr(business, "id", target_owner))
        else:
            business_name = None
            business_category = None
            business_location = None
            business_target_customer = None
            business_language = "en"
            business_description = None
            effective_biz_id = business_id or (user_id if user_id else "default")

        context: Dict[str, Any] = {
            "business": {
                "id": effective_biz_id if effective_biz_id != "default" else None,
                "name": business_name,
                "category": business_category,
                "description": business_description,
                "location": business_location,
                "target_customer": business_target_customer,
                "language": business_language
            },
            "brand": {},
            "products": []
        }

        if db is not None:
            # 2. Retrieve authentic saved Brand Kit
            try:
                brand_kit = await get_brand_kit(db, effective_biz_id)
            except Exception:
                brand_kit = None

            if not brand_kit and target_owner:
                try:
                    brand_kit = await db["brand_kits"].find_one({"owner_id": target_owner})
                except Exception:
                    brand_kit = None

            if brand_kit:
                context["brand"] = {
                    "brand_name": brand_kit.get("brand_name") or brand_kit.get("business_name") or business_name,
                    "tone": brand_kit.get("tone") or brand_kit.get("brand_voice"),
                    "brand_voice": brand_kit.get("brand_voice") or brand_kit.get("tone"),
                    "target_audience": brand_kit.get("target_audience") or business_target_customer,
                    "primary_color": brand_kit.get("primary_color"),
                    "secondary_color": brand_kit.get("secondary_color"),
                    "brand_colors": brand_kit.get("brand_colors") or brand_kit.get("colors") or [],
                    "font": brand_kit.get("font") or brand_kit.get("primary_font"),
                    "social_style": brand_kit.get("social_style"),
                    "tagline": brand_kit.get("tagline"),
                    "brand_values": brand_kit.get("brand_values", []),
                    "sub_category": brand_kit.get("sub_category"),
                    "differentiators": brand_kit.get("differentiators") or [],
                    "products_services": brand_kit.get("products_services") or [],
                    "online_presence": brand_kit.get("online_presence"),
                    "logo_url": brand_kit.get("logo_url"),
                }

            # 3. Retrieve authentic catalog products
            prods = []
            if effective_biz_id and effective_biz_id != "default":
                try:
                    prods = await get_products(db, effective_biz_id)
                except Exception:
                    prods = []
            if not prods and target_owner:
                try:
                    cursor = db["products"].find({"$or": [{"owner_id": target_owner}, {"business_id": target_owner}]})
                    prods = await cursor.to_list(length=10)
                except Exception:
                    prods = []

            for product in (prods or []):
                context["products"].append({
                    "id": str(product.get("id") or product.get("_id", "")),
                    "name": product.get("name"),
                    "category": product.get("category"),
                    "description": product.get("description"),
                    "price": product.get("price"),
                    "sale_price": product.get("sale_price"),
                    "sizes": product.get("sizes", []),
                    "colors": product.get("colors", []),
                    "features": product.get("features", []),
                    "stock": product.get("stock"),
                    "image_url": product.get("image_url"),
                })

        return context

    @classmethod
    def format_context_for_prompt(cls, context: Dict[str, Any]) -> str:
        """Formats the context into a clean, concise markdown prompt snippet without hallucinations."""
        biz = context.get("business", {})
        brand = context.get("brand", {})
        prods = context.get("products", [])

        lines = []
        if biz.get("name"):
            lines.append(f"Business: {biz['name']}")
        if biz.get("category"):
            lines.append(f"Category: {biz['category']}")
        if biz.get("target_customer"):
            lines.append(f"Target Audience: {biz['target_customer']}")
        if brand.get("primary_color"):
            lines.append(f"Brand Primary Color: {brand['primary_color']}")
        if brand.get("brand_voice"):
            lines.append(f"Brand Voice: {brand['brand_voice']}")
        if prods:
            prod_names = [p["name"] for p in prods if p.get("name")]
            if prod_names:
                lines.append(f"Featured Products: {', '.join(prod_names)}")
        return "\n".join(lines)

    @classmethod
    async def get_context_summary(
        cls,
        db: Optional[Any] = None,
        user_id: Optional[str] = None,
        business_id: Optional[str] = None
    ) -> str:
        """Convenience method returning formatted prompt string from authenticated business context."""
        ctx = await cls.get_business_context(
            business_id=business_id or "default",
            user_id=user_id,
            db=db
        )
        return cls.format_context_for_prompt(ctx)
