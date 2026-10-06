from typing import Dict, Any
from app.services.business_service import BusinessService
from app.services.brand_service import get_brand_kit
from app.services.product_service import get_products
from app.core.database import get_database


class BusinessContextService:
    @staticmethod
    async def get_business_context(business_id: str) -> Dict[str, Any]:
        """
        Gathers business, brand, and product data to create a structured context.
        """
        business = await BusinessService.get_business(business_id)
        
        # Developer mode fallback: if business doesn't exist, provide a mock base context
        if not business:
            business_name = "Mock Business"
            business_category = "General"
            business_location = "Global"
            business_target_customer = "Everyone"
            business_language = "en"
        else:
            business_name = business.name
            business_category = business.category
            business_location = business.location
            business_target_customer = business.target_customer
            business_language = business.preferred_language

        db = get_database()

        context = {
            "business": {
                "name": business_name,
                "category": business_category,
                "location": business_location,
                "target_customer": business_target_customer,
                "language": business_language
            },
            "brand": {},
            "products": []
        }

        # Get brand kit (returns None if not found, suppress 404)
        try:
            brand_kit = await get_brand_kit(db, business_id)
            context["brand"] = {
                "tone": brand_kit.get("tone"),
                "target_audience": brand_kit.get("target_audience"),
                "primary_color": brand_kit.get("primary_color"),
                "secondary_color": brand_kit.get("secondary_color"),
                "font": brand_kit.get("font"),
                "social_style": brand_kit.get("social_style"),
            }
        except Exception:
            pass

        # Get products
        try:
            products = await get_products(db, business_id)
            for product in products:
                context["products"].append({
                    "id": product.get("id"),
                    "name": product.get("name"),
                    "description": product.get("description"),
                    "price": product.get("price"),
                    "sale_price": product.get("sale_price"),
                    "sizes": product.get("sizes", []),
                    "colors": product.get("colors", []),
                    "stock": product.get("stock"),
                    "image_url": product.get("image_url"),
                })
        except Exception:
            pass

        return context
