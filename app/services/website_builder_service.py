import json
import re
import uuid
<<<<<<< Updated upstream
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from bson import ObjectId
from fastapi import HTTPException
=======
from fastapi import HTTPException, status
>>>>>>> Stashed changes

from app.core.database import get_database
from app.models.website_builder import WebsiteProject, WebsiteBuilderSession
from app.services.business_service import BusinessService
from app.services.brand_service import get_brand_kit
from app.ai.factory import AIProviderFactory

logger = logging.getLogger(__name__)


class WebsiteBuilderService:

    # ---------------------------------------------------------
    # BUSINESS CATEGORY DETECTION
    # ---------------------------------------------------------

    CATEGORY_KEYWORDS = {
        "Indian Sweet Shop": [
            "sweet shop", "indian sweet", "mithai", "mithai shop",
            "sweets", "ladoo", "laddu", "barfi", "jalebi",
            "gulab jamun", "rasgulla", "kaju katli"
        ],
        "Flower Shop": [
            "flower shop", "florist", "flowers", "bouquets",
            "roses", "tulips", "floral arrangements"
        ],
        "Gym & Fitness": [
            "gym", "fitness center", "fitness centre",
            "workout", "personal training", "fitness studio"
        ],
        "Restaurant": [
            "restaurant", "cafe", "food shop", "eatery",
            "diner", "bakery", "pizza", "burger"
        ],
        "Clothing Store": [
            "clothing store", "fashion store", "boutique",
            "clothes", "apparel", "garments", "saree", "lehenga"
        ],
        "Beauty Salon": [
            "salon", "beauty parlour", "beauty parlor",
            "hair salon", "spa", "makeup studio"
        ],
        "Jewellery Store": [
            "jewellery", "jewelry", "gold shop", "diamond store"
        ],
        "Real Estate": [
            "real estate", "property dealer", "property business",
            "realty", "construction"
        ],
        "Technology Business": [
            "software company", "IT company", "technology company",
            "web development", "digital agency", "software agency"
        ],
    }

    @staticmethod
    def detect_business_category(message: str) -> Optional[str]:
        text = message.lower().strip()

        for category, keywords in WebsiteBuilderService.CATEGORY_KEYWORDS.items():
            if any(keyword in text for keyword in keywords):
                return category

        return None

    @staticmethod
    def extract_business_details(message: str, existing: dict) -> dict:
        """
        Deterministic extraction for common business details.
        Never treats the entire website request as the business name.
        """

        result = {}

        category = WebsiteBuilderService.detect_business_category(message)

        if category and not existing.get("Business Category"):
            result["Business Category"] = category

        text = message.strip()

        # Extract products/services from explicit phrases.
        patterns = [
            r"(?:i sell|we sell|selling|products are|we offer|i offer)\s+(.+)",
            r"(?:services include|we provide|i provide)\s+(.+)"
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                result["Products/Services"] = match.group(1).strip(" .")
                break

        # Extract shop name only when user explicitly provides it.
        name_patterns = [
            r"(?:my business name is|business name is|shop name is|store name is)\s+(.+)",
            r"(?:my shop is called|my store is called|called)\s+(.+)"
        ]

        for pattern in name_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                result["Business Name"] = match.group(1).strip(" .")
                break

        return result

    @staticmethod
    def normalize_text(value: Any) -> str:
        if value is None:
            return ""
        return str(value).strip()

    # ---------------------------------------------------------
    # IMAGE RESOLUTION
    # ---------------------------------------------------------

    @staticmethod
    def resolve_curated_image(
        category: str = "",
        prompt: str = "",
        index: int = 0,
        is_hero: bool = False
    ) -> str:

        text = f"{category} {prompt}".lower()

        galleries = {
            "Indian Sweet Shop": [
                "https://images.unsplash.com/photo-1605197161470-5d4cc2c4c9d7?auto=format&fit=crop&w=1200&q=85",
                "https://images.unsplash.com/photo-1601050690597-df0568f70950?auto=format&fit=crop&w=900&q=85",
                "https://images.unsplash.com/photo-1576618148400-f54bed99fcfd?auto=format&fit=crop&w=900&q=85",
                "https://images.unsplash.com/photo-1606491956689-2ea866880c84?auto=format&fit=crop&w=900&q=85",
            ],
            "Flower Shop": [
                "https://images.unsplash.com/photo-1490750967868-88aa4486c946?auto=format&fit=crop&w=1200&q=85",
                "https://images.unsplash.com/photo-1520763185298-1b434c919102?auto=format&fit=crop&w=900&q=85",
                "https://images.unsplash.com/photo-1494972308805-463bc619d34e?auto=format&fit=crop&w=900&q=85",
                "https://images.unsplash.com/photo-1525310072745-f49212b5ac6d?auto=format&fit=crop&w=900&q=85",
            ],
            "Gym & Fitness": [
                "https://images.unsplash.com/photo-1534438327276-14e5300c3a48?auto=format&fit=crop&w=1200&q=85",
                "https://images.unsplash.com/photo-1517836357463-d25dfeac3438?auto=format&fit=crop&w=900&q=85",
                "https://images.unsplash.com/photo-1534258936925-c58bed479fcb?auto=format&fit=crop&w=900&q=85",
                "https://images.unsplash.com/photo-1583454110551-21f2fa2afe61?auto=format&fit=crop&w=900&q=85",
            ],
            "Restaurant": [
                "https://images.unsplash.com/photo-1517248135467-4c7edcad34c4?auto=format&fit=crop&w=1200&q=85",
                "https://images.unsplash.com/photo-1504674900247-0877df9cc836?auto=format&fit=crop&w=900&q=85",
                "https://images.unsplash.com/photo-1555396273-367ea4eb4db5?auto=format&fit=crop&w=900&q=85",
                "https://images.unsplash.com/photo-1565299624946-b28f40a0ae38?auto=format&fit=crop&w=900&q=85",
            ],
            "Clothing Store": [
                "https://images.unsplash.com/photo-1441986300917-64674bd600d8?auto=format&fit=crop&w=1200&q=85",
                "https://images.unsplash.com/photo-1490481651871-ab68de25d43d?auto=format&fit=crop&w=900&q=85",
                "https://images.unsplash.com/photo-1445205170230-053b83016050?auto=format&fit=crop&w=900&q=85",
                "https://images.unsplash.com/photo-1489987707025-afc232f7ea0f?auto=format&fit=crop&w=900&q=85",
            ],
        }

        category_name = next(
            (
                key for key in galleries
                if key.lower() in text
            ),
            None
        )

        if category_name:
            images = galleries[category_name]
            return images[index % len(images)]

        # Unknown categories should not receive unrelated office images.
        # Use a neutral abstract background rather than pretending it
        # is a verified industry-specific photograph.
        return (
            "https://images.unsplash.com/photo-1497366754035-f200968a6e72"
            "?auto=format&fit=crop&w=1200&q=80"
        )

    # ---------------------------------------------------------
    # BRAND COLORS
    # ---------------------------------------------------------

    @staticmethod
    def resolve_palette(
        text: str = "",
        category: str = "",
        brand_guidelines: dict = None
    ) -> dict:

        brand = brand_guidelines or {}

        primary = brand.get("primary_color")
        secondary = brand.get("secondary_color")
        accent = brand.get("accent_color")

        if primary and str(primary).startswith("#"):
            return {
                "primary": primary,
                "secondary": secondary or primary,
                "accent": accent or "#F59E0B",
                "font": brand.get("font") or "outfit"
            }

        category = category.lower()

        palettes = {
            "indian sweet shop": ("#9A3412", "#7C2D12", "#F59E0B"),
            "flower shop": ("#BE185D", "#166534", "#F9A8D4"),
            "gym & fitness": ("#EA580C", "#111827", "#10B981"),
            "restaurant": ("#991B1B", "#451A03", "#F59E0B"),
            "clothing store": ("#1E293B", "#334155", "#DB2777"),
            "beauty salon": ("#BE185D", "#831843", "#F9A8D4"),
            "jewellery store": ("#92400E", "#451A03", "#FBBF24"),
            "real estate": ("#0F766E", "#134E4A", "#38BDF8"),
            "technology business": ("#1D4ED8", "#111827", "#06B6D4"),
        }

        primary, secondary, accent = palettes.get(
            category,
            ("#4F46E5", "#312E81", "#F59E0B")
        )

        return {
            "primary": primary,
            "secondary": secondary,
            "accent": accent,
            "font": "outfit"
        }

    # ---------------------------------------------------------
    # DATABASE
    # ---------------------------------------------------------

    @staticmethod
    async def get_session_collection():
        return get_database()["website_builder_sessions"]

    @staticmethod
    async def get_project_collection():
        return get_database()["website_projects"]

    @staticmethod
    async def get_website(project_id: str, user_id: str):
        if not ObjectId.is_valid(project_id):
            return None

        collection = await WebsiteBuilderService.get_project_collection()

        doc = await collection.find_one({
            "_id": ObjectId(project_id),
            "user_id": user_id
        })

        if doc:
            return WebsiteProject(**doc)

        return None

    @staticmethod
    async def save_session(session: WebsiteBuilderSession):
        collection = await WebsiteBuilderService.get_session_collection()

        update_data = session.model_dump(
            by_alias=True,
            exclude={"id", "created_at"}
        )

        update_data["updated_at"] = datetime.now(timezone.utc)

        await collection.update_one(
            {"_id": ObjectId(session.id)},
            {"$set": update_data}
        )

    @staticmethod
    async def create_session(user_id: str):
        collection = await WebsiteBuilderService.get_session_collection()

        await collection.update_many(
            {"user_id": user_id, "status": "active"},
            {"$set": {"status": "archived"}}
        )

        session = WebsiteBuilderSession(
            user_id=user_id,
            current_step=1,
            collected_data={
                "onboarding_step": "business_details"
            },
            messages=[{
                "id": str(uuid.uuid4()),
                "role": "ai",
                "content": (
                    "Hi! What type of business do you run, "
                    "and what products or services do you offer?"
                ),
                "type": "text"
            }]
        )

        doc = session.model_dump(by_alias=True, exclude={"id"})
        result = await collection.insert_one(doc)

        session.id = str(result.inserted_id)

        return session

    @staticmethod
    async def get_session(session_id: str, user_id: str):
        if not ObjectId.is_valid(session_id):
            return None

        collection = await WebsiteBuilderService.get_session_collection()

        doc = await collection.find_one({
            "_id": ObjectId(session_id),
            "user_id": user_id
        })

        return WebsiteBuilderSession(**doc) if doc else None

    # ---------------------------------------------------------
    # BRAND KIT
    # ---------------------------------------------------------

    @staticmethod
    async def get_saved_brand(user_id: str, session: WebsiteBuilderSession):
        """
        Retrieve the existing business and its saved Brand Kit.
        The Brand Kit logo is never fabricated here.
        """

        business_id = session.collected_data.get("business_id")

        if not business_id:
            try:
                business = await BusinessService.get_business_by_owner(user_id)

                if business:
                    business_id = str(business.id)
                    session.collected_data["business_id"] = business_id

                    if not session.collected_data.get("Business Name"):
                        session.collected_data["Business Name"] = business.business_name

                    if not session.collected_data.get("Business Category"):
                        session.collected_data["Business Category"] = business.business_category

            except Exception:
                logger.exception("Could not retrieve business profile")

        if not business_id:
            return None

        try:
            brand = await get_brand_kit(get_database(), str(business_id))

            if not brand:
                return None

            if isinstance(brand, dict):
                brand_data = dict(brand)
            else:
                brand_data = brand.model_dump(
                    by_alias=True,
                    exclude={"id"}
                )

            brand_data.pop("_id", None)
            brand_data.pop("id", None)

            session.collected_data["Brand Guidelines"] = brand_data

            if brand_data.get("logo_url"):
                session.collected_data["Logo"] = brand_data["logo_url"]
                session.collected_data["logo_status"] = "available"

            return brand_data

        except Exception:
            logger.exception("Brand Kit lookup failed")
            return None

    # ---------------------------------------------------------
    # CHAT MESSAGE HELPERS
    # ---------------------------------------------------------

    @staticmethod
<<<<<<< Updated upstream
    def add_ai_message(
        session,
        content: str,
        message_type: str = "text",
        options: list = None,
        data: dict = None
    ):
        message = {
            "id": str(uuid.uuid4()),
            "role": "ai",
            "content": content,
            "type": message_type
        }

        if options:
            message["options"] = options

        if data:
            message["data"] = data

        session.messages.append(message)

    @staticmethod
    def add_user_message(session, content: str):
=======
    async def process_chat(session_id: str, user_id: str, message: str, language: str = None, data: dict = None):
        session = await WebsiteBuilderService.get_session(session_id, user_id)
        if not session:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
            
>>>>>>> Stashed changes
        session.messages.append({
            "id": str(uuid.uuid4()),
            "role": "user",
            "content": content
        })

    # ---------------------------------------------------------
    # ONBOARDING FLOW
    # ---------------------------------------------------------

    @staticmethod
    async def process_chat(
        session_id: str,
        user_id: str,
        message: str,
        language: str = None,
        data: dict = None
    ):

<<<<<<< Updated upstream
        session = await WebsiteBuilderService.get_session(
            session_id,
            user_id
=======
    @staticmethod
    async def select_template(session_id: str, user_id: str, template_id: str) -> WebsiteBuilderSession:
        session = await WebsiteBuilderService.get_session(session_id, user_id)
        if not session:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
            
        session.selected_template = template_id
        session.current_step = 7
        session.messages.append({
            "id": str(uuid.uuid4()),
            "role": "ai",
            "content": f"You selected the {template_id} template! Click 'Build My Website' to generate your site.",
            "type": "summary",
            "data": {
                "business": session.collected_data.get("Business Name", "Your Business"),
                "theme": template_id,
                "language": session.language
            },
            "options": [{"label": "Build My Website", "action": "generate"}]
        })
        await WebsiteBuilderService.save_session(session)
        return session
        
    @staticmethod
    async def generate_website(session: WebsiteBuilderSession):
        session.messages.append({
            "id": str(uuid.uuid4()),
            "role": "ai",
            "content": "Generating your custom website based on your chatbot prompt...",
            "type": "generation_status",
            "data": { "progress": ["Business Information", "Brand Style", "Website Structure"] }
        })
        await WebsiteBuilderService.save_session(session)
        
        user_prompts = [m.get("content") for m in session.messages if m.get("role") == "user" and m.get("content")]
        full_user_intent = " | ".join(user_prompts) if user_prompts else "Website"
        
        b_name = session.collected_data.get("Business Name") or session.collected_data.get("Business Category")
        if not b_name or str(b_name).strip().upper() in ["A", "AN", "THE", "MYBUSINESS", "NONE", "NULL", ""]:
            clean_intent = full_user_intent.replace("build", "").replace("website", "").replace("create", "").replace("want", "").replace("for", "").strip()
            if clean_intent and len(clean_intent) > 2 and clean_intent.upper() not in ["A", "AN", "THE"]:
                b_name = clean_intent.title()
            elif session.collected_data.get("Business Category"):
                b_name = f"{session.collected_data['Business Category'].title()} Studio"
            else:
                b_name = "My Business"

        b_cat = session.collected_data.get("Business Category", full_user_intent)
        if str(b_cat).strip().upper() in ["A", "AN", "THE", ""]:
            b_cat = b_name

        brand_guidelines = session.collected_data.get("Brand Guidelines") or {}
        theme_data = WebsiteBuilderService.resolve_palette(full_user_intent, b_cat, brand_guidelines)
        logo_url = session.collected_data.get("Logo") or WebsiteBuilderService.resolve_brand_logo(b_name, theme_data["primary"], brand_guidelines)

        # Dynamic topic-aligned schema example with rich multi-sections
        schema_example = json.dumps({
            "theme": theme_data,
            "logo": logo_url,
            "pages": [
                {
                    "name": "Home",
                    "sections": [
                        {
                            "type": "hero", 
                            "title": f"Welcome to {b_name}", 
                            "subtitle": f"Experience handcrafted excellence and premium quality tailored for your lifestyle in {b_cat}.", 
                            "cta": f"Explore {b_cat}", 
                            "image_prompt": f"high quality beautiful {b_cat} background banner", 
                            "image_url": ""
                        },
                        {
                            "type": "features", 
                            "title": f"Featured {b_cat} Collections", 
                            "subtitle": f"Our most popular selections crafted with care",
                            "items": [
                                {"title": f"Signature {b_cat} Classic", "description": f"Exceptional quality and professional standards for all your {b_cat} needs.", "price": "$29.00", "image_prompt": f"hd professional photo of {b_name} {b_cat} showcase", "image_url": ""},
                                {"title": "Artisanal Specialty", "description": f"Customized features and tailored packages designed for {b_cat}.", "price": "$39.00", "image_prompt": f"high quality {b_cat} service feature banner", "image_url": ""},
                                {"title": "Premium Experience", "description": f"Delivering satisfaction and top performance in {b_cat}.", "price": "$49.00", "image_prompt": f"modern sleek design for {b_cat}", "image_url": ""}
                            ]
                        },
                        {
                            "type": "features",
                            "title": f"Why Choose {b_name}",
                            "subtitle": "Unmatched standards that set us apart",
                            "items": [
                                {"title": "Ethically Sourced & Crafted", "description": "We believe in sustainable, transparent practices in everything we produce.", "image_prompt": f"quality craftsmanship banner for {b_cat}"},
                                {"title": "Dedicated Specialists", "description": f"Decades of expertise poured into every single {b_cat} detail.", "image_prompt": f"expert team at work in {b_cat}"},
                                {"title": "Customer Satisfaction", "description": "Guaranteed quality and personalized support for every client.", "image_prompt": f"happy satisfied clients and 5 star service"}
                            ]
                        },
                        {
                            "type": "features",
                            "title": "Customer Favorites & Reviews",
                            "subtitle": "Loved by thousands in our community",
                            "items": [
                                {"title": "Top Rated Selection", "description": "Outstanding quality! Exceeded our expectations in every single way.", "price": "5.0 ★ Rating", "image_prompt": f"top customer choice {b_cat}"},
                                {"title": "Seasonal Special", "description": "A must-try favorite recommended by our loyal regulars.", "price": "$34.00", "image_prompt": f"popular trending {b_cat}"}
                            ]
                        }
                    ]
                },
                {
                    "name": "About",
                    "sections": [
                        {
                            "type": "features", 
                            "title": f"About {b_name}", 
                            "subtitle": f"Our mission and story in {b_cat}",
                            "items": [
                                {"title": "Our Heritage", "description": f"How {b_name} strives to deliver unmatched excellence in {b_cat}.", "image_prompt": f"professional team working on {b_cat}"},
                                {"title": "Our Quality Commitment", "description": f"Rigorous standards and dedication to perfection in every {b_cat} project.", "image_prompt": f"quality guarantee badge for {b_cat}"}
                            ]
                        }
                    ]
                },
                {
                    "name": "Products",
                    "sections": [
                        {
                            "type": "features", 
                            "title": f"Our Complete {b_cat} Catalog", 
                            "subtitle": f"Browse our full collection of products & packages",
                            "items": [
                                {"title": f"Flagship {b_cat} Tier", "description": f"Best-in-class products and gear for {b_cat}.", "price": "$59.00", "image_prompt": f"featured product showcase {b_cat}"},
                                {"title": f"Custom Packages", "description": f"Tailored options engineered specifically for your {b_cat} requirements.", "price": "$89.00", "image_prompt": f"custom designed {b_cat} item"},
                                {"title": f"Everyday Essentials", "description": f"Top trending items highly recommended in {b_cat}.", "price": "$24.00", "image_prompt": f"popular essential collection {b_cat}"}
                            ]
                        }
                    ]
                },
                {
                    "name": "Contact",
                    "sections": [
                        {
                            "type": "features", 
                            "title": "Get In Touch", 
                            "subtitle": "We'd love to hear from you",
                            "items": [
                                {"title": "Email Us", "description": f"contact@{b_name.lower().replace(' ', '')}.com", "image_prompt": "modern contact support desk email"},
                                {"title": "Phone Helpline", "description": "+1 (800) 555-0199", "image_prompt": "phone hotline customer support"},
                                {"title": "Showroom Location", "description": "742 Innovation Parkway, Suite 100", "image_prompt": f"modern showroom for {b_cat}"}
                            ]
                        }
                    ]
                }
            ]
        })
        ai = AIProviderFactory.get_provider(preferred="openai")
        prompt = (
            f"""Generate a custom structured website JSON based strictly on the user's business topic and prompt.

User Prompt / Intent: '{full_user_intent}'
Business Name: '{b_name}'
Business Topic / Category: '{b_cat}'
Language: {session.language or 'English'}.

CRITICAL REQUIREMENTS:
1. Heavily prioritize and implement ALL specific instructions, custom content, themes, and image concepts mentioned in the 'User Prompt / Intent'.
2. EVERYTHING (titles, descriptions, section headlines, prices, image_prompts) MUST be tailored to '{b_cat}', business name '{b_name}', AND the user's specific prompt.
3. Every item MUST include a detailed English 'image_prompt' that describes crisp visual photography relevant to '{b_cat}'.
4. Include rich content sections on Home: Hero, Featured Collections with prices, Why Choose Us, and Customer Favorites.
5. In 'theme', provide matching hex codes: {{"primary": "{theme_data['primary']}", "secondary": "{theme_data['secondary']}", "font": "outfit"}}.
6. Return ONLY valid JSON matching this structure: {schema_example}."""
>>>>>>> Stashed changes
        )

        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        data = data or {}
        action = data.get("action")

        # -----------------------------------------------------
        # TEMPLATE SELECTION
        # -----------------------------------------------------

        if action == "select_template":
            template_id = data.get("templateId") or data.get("template_id")

            if not template_id:
                raise HTTPException(400, "Template ID is required")

            session.selected_template = str(template_id)

            session.collected_data["selected_template_id"] = str(template_id)
            session.collected_data["selected_template_name"] = (
                data.get("templateName")
                or data.get("template_name")
                or str(template_id)
            )

            session.current_step = 5
            session.collected_data["onboarding_step"] = "industry_details"

            WebsiteBuilderService.add_user_message(
                session,
                data.get("templateName", str(template_id))
            )

            await WebsiteBuilderService.ask_industry_question(session)
            await WebsiteBuilderService.save_session(session)

            return type("Result", (), {
                "message": session.messages[-1]["content"],
                "quick_actions": [],
                "session": session
            })

        # -----------------------------------------------------
        # GENERATION ACTION
        # -----------------------------------------------------

        if action == "generate":
            WebsiteBuilderService.add_user_message(session, message)

            return await WebsiteBuilderService.generate_website(
                session,
                user_id
            )

        # -----------------------------------------------------
        # NORMAL MESSAGE
        # -----------------------------------------------------

        WebsiteBuilderService.add_user_message(session, message)

        extracted = WebsiteBuilderService.extract_business_details(
            message,
            session.collected_data
        )

        for key, value in extracted.items():
            if value:
                session.collected_data[key] = value

        if language:
            session.language = language

        step = session.collected_data.get(
            "onboarding_step",
            "business_details"
        )

        # -----------------------------------------------------
        # STEP 1: BUSINESS CATEGORY
        # -----------------------------------------------------

        if step == "business_details":

            sub_step = session.collected_data.get("sub_step", "category")

            # If we already asked for products/services in a previous turn:
            if sub_step == "products_services":
                candidate = message.strip()
                clean_prod = re.sub(
                    r"^(i sell|we sell|selling|i offer|we offer|services are|products are|we do|i do|everything related to|everything related)\s+",
                    "",
                    candidate,
                    flags=re.I
                ).strip(" .")
                products = clean_prod if clean_prod else candidate

                session.collected_data["Products/Services"] = products
                session.collected_data["onboarding_step"] = "business_name"
                session.current_step = 2

                await WebsiteBuilderService.reply(
                    session,
                    "Great! What is the name of your business or shop?"
                )

            else:
                category = (
                    session.collected_data.get("Business Category")
                    or WebsiteBuilderService.detect_business_category(message)
                )

                if not category:
                    await WebsiteBuilderService.reply(
                        session,
                        "Please tell me what type of business you run. "
                        "For example, a sweet shop, flower shop, gym or restaurant."
                    )

                else:
                    session.collected_data["Business Category"] = category
                    products = extracted.get("Products/Services")

                    if not products:
                        # Need to ask for products/services
                        session.collected_data["sub_step"] = "products_services"
                        await WebsiteBuilderService.reply(
                            session,
                            f"Got it! You run a {category}. "
                            "What products or services do you offer?"
                        )
                    else:
                        session.collected_data["Products/Services"] = products
                        session.collected_data["onboarding_step"] = "business_name"
                        session.current_step = 2

                        await WebsiteBuilderService.reply(
                            session,
                            "Great! What is the name of your business or shop?"
                        )

        # -----------------------------------------------------
        # STEP 2: BUSINESS NAME
        # -----------------------------------------------------

        elif step == "business_name":

            name = extracted.get("Business Name")

            if not name:
                candidate = message.strip()
                cleaned = re.sub(
                    r"^(my business name is|business name is|shop name is|store name is|it is called|it's called|it is|it's|called|name is)\s+",
                    "",
                    candidate,
                    flags=re.I
                ).strip(" .'")

                if (
                    len(cleaned) >= 2
                    and len(cleaned) <= 80
                    and cleaned.lower() not in [
                        "i need", "i want", "website", "shop", "business", "no", "yes", "ok"
                    ]
                ):
                    name = cleaned

            if not name:
                await WebsiteBuilderService.reply(
                    session,
                    "Please enter the name you want to display on your website."
                )
            else:
                session.collected_data["Business Name"] = name
                session.collected_data["onboarding_step"] = "design_choice"
                session.current_step = 3

                await WebsiteBuilderService.reply(
                    session,
                    f"Nice to meet you, {name}! Would you like me to "
                    "recommend three designs or build directly?",
                    options=[
                        {"label": "✨ Recommend Designs", "action": "recommend"},
                        {"label": "⚡ Build Directly", "action": "build_directly"}
                    ]
                )

        # -----------------------------------------------------
        # STEP 3: DESIGN CHOICE
        # -----------------------------------------------------

        elif step == "design_choice":

            if action == "recommend" or "recommend" in message.lower():
                return await WebsiteBuilderService.generate_recommendations(session)

            session.collected_data["selected_template_name"] = "Apex Modern Pro"
            session.collected_data["selected_template_id"] = "apex-modern-pro"
            session.selected_template = "apex-modern-pro"

            session.collected_data["onboarding_step"] = "industry_details"
            session.current_step = 5

            await WebsiteBuilderService.ask_industry_question(session)

        # -----------------------------------------------------
        # STEP 5: INDUSTRY DETAILS
        # -----------------------------------------------------

        elif step == "industry_details":

            session.collected_data["industry_details"] = message.strip()

            session.collected_data["onboarding_step"] = "logo_check"
            session.current_step = 6

            await WebsiteBuilderService.check_logo_and_continue(
                user_id,
                session,
                action=action,
                message=message
            )

        # -----------------------------------------------------
        # STEP 6: LOGO CHECK
        # -----------------------------------------------------

        elif step == "logo_check":

            if action == "open_brand_kit":
                await WebsiteBuilderService.reply(
                    session,
                    "Please create and save your logo in Brand Kit. "
                    "Return here once it is ready."
                )

            else:
                await WebsiteBuilderService.check_logo_and_continue(
                    user_id,
                    session
                )

        # -----------------------------------------------------
        # STEP 7: CONFIRMATION
        # -----------------------------------------------------

        elif step == "confirmation":

            if action == "generate" or message.lower().strip() in [
                "yes", "confirm", "build", "generate",
                "confirm & generate website"
            ]:
                return await WebsiteBuilderService.generate_website(
                    session,
                    user_id
                )

            if action == "edit_details":
                session.collected_data["onboarding_step"] = "industry_details"

                await WebsiteBuilderService.ask_industry_question(session)

            else:
                await WebsiteBuilderService.reply(
                    session,
                    "Would you like to generate the website or edit your details?",
                    options=[
                        {"label": "🚀 Confirm & Generate Website", "action": "generate"},
                        {"label": "Edit Details", "action": "edit_details"}
                    ]
                )

        # -----------------------------------------------------
        # GENERATED WEBSITE EDITING
        # -----------------------------------------------------

        elif step == "generated":

            await WebsiteBuilderService.reply(
                session,
                "Your website is ready. You can ask me to change its "
                "images, text, colors, layout or sections."
            )

        await WebsiteBuilderService.save_session(session)

        return type("Result", (), {
            "message": session.messages[-1]["content"],
            "quick_actions": session.messages[-1].get("options", []),
            "session": session
        })

    @staticmethod
    async def reply(session, message, options=None, data=None):
        WebsiteBuilderService.add_ai_message(
            session,
            message,
            options=options,
            data=data
        )

    # ---------------------------------------------------------
    # INDUSTRY QUESTIONS
    # ---------------------------------------------------------

    @staticmethod
    async def ask_industry_question(session):

        category = session.collected_data.get(
            "Business Category",
            ""
        ).lower()

        questions = {
            "indian sweet shop": (
                "What makes your sweet shop special? "
                "For example, traditional recipes, fresh mithai, "
                "gift boxes or festival collections?"
            ),
            "flower shop": (
                "Do you offer home delivery, event decoration, "
                "custom bouquets or all of these?"
            ),
            "gym & fitness": (
                "What facilities or programs do you offer? "
                "For example, strength training, cardio, yoga "
                "or personal training?"
            ),
            "restaurant": (
                "What type of cuisine do you serve, and "
                "do you offer dine-in, takeaway or delivery?"
            ),
            "clothing store": (
                "What clothing collections do you sell, "
                "and do you offer online ordering?"
            ),
            "beauty salon": (
                "Which services do you provide? "
                "For example, hair styling, skincare, makeup or spa?"
            ),
        }

        question = questions.get(
            category,
            "What are the most important products, services or "
            "features you want customers to see on your website?"
        )

        await WebsiteBuilderService.reply(session, question)

    # ---------------------------------------------------------
    # BRAND KIT VALIDATION
    # ---------------------------------------------------------

    @staticmethod
    async def check_logo_and_continue(user_id, session, action=None, message=""):

        brand = await WebsiteBuilderService.get_saved_brand(
            user_id,
            session
        )

        logo = (
            session.collected_data.get("Logo")
            or (brand or {}).get("logo_url")
        )

        if not logo:
            action_name = (action or "").lower()
            if action_name in ["skip_logo", "use_text_logo"] or any(
                w in (message or "").lower() for w in ["skip", "without logo", "text logo", "later", "no logo"]
            ):
                logo = ""
                session.collected_data["Logo"] = ""
                session.collected_data["logo_status"] = "skipped"
            else:
                session.collected_data["logo_status"] = "required"
                session.collected_data["onboarding_step"] = "logo_check"

                await WebsiteBuilderService.reply(
                    session,
                    "Your website needs your business logo. "
                    "You can create one in Brand Kit, or proceed with a text logo for now.",
                    options=[
                        {
                            "label": "Create Logo in Brand Kit",
                            "action": "open_brand_kit"
                        },
                        {
                            "label": "Proceed with Text Logo (Skip)",
                            "action": "skip_logo"
                        }
                    ],
                    data={
                        "brand_kit_required": True,
                        "redirect": "/brand-kit"
                    }
                )
                return

        session.collected_data["Logo"] = logo
        session.collected_data["logo_status"] = "available"

        session.collected_data["onboarding_step"] = "confirmation"
        session.current_step = 7

        summary = (
            "Here is your website information:\n\n"
            f"Business: {session.collected_data.get('Business Name')}\n"
            f"Category: {session.collected_data.get('Business Category')}\n"
            f"Products/Services: {session.collected_data.get('Products/Services', 'Not specified')}\n"
            f"Design: {session.collected_data.get('selected_template_name')}\n"
            f"Additional details: {session.collected_data.get('industry_details', 'Not specified')}\n\n"
            "Would you like me to generate your website now?"
        )

        await WebsiteBuilderService.reply(
            session,
            summary,
            options=[
                {
                    "label": "🚀 Confirm & Generate Website",
                    "action": "generate"
                },
                {
                    "label": "Edit Details",
                    "action": "edit_details"
                }
            ]
        )

    # ---------------------------------------------------------
    # TEMPLATE RECOMMENDATIONS
    # ---------------------------------------------------------

    @staticmethod
    async def generate_recommendations(session):

        category = session.collected_data.get(
            "Business Category",
            "Business"
        )

        templates = {
            "Indian Sweet Shop": [
                ("Royal Mithai", "Traditional Indian sweets with a premium royal design."),
                ("Sweet Heritage", "Warm traditional design with rich product galleries."),
                ("Modern Mithai", "Clean modern storefront for Indian sweets.")
            ],
            "Flower Shop": [
                ("Floral Elegance", "Elegant floral photography and soft colors."),
                ("Bloom & Blossom", "Modern bouquet-focused storefront."),
                ("Botanical Garden", "Natural botanical layout with green accents.")
            ],
            "Gym & Fitness": [
                ("Iron Forge Fitness", "Bold fitness-focused design."),
                ("Pulse Athletics", "Modern athletic website with strong CTAs."),
                ("Zenith Wellness", "Premium wellness and fitness layout.")
            ],
            "Restaurant": [
                ("Culinary Premium", "Elegant restaurant design."),
                ("Modern Bistro", "Modern food-focused layout."),
                ("Taste & Tradition", "Warm hospitality design.")
            ],
            "Clothing Store": [
                ("Style Avenue", "Premium fashion storefront."),
                ("Minimal Wardrobe", "Minimal product-led layout."),
                ("Urban Collection", "Bold modern fashion design.")
            ]
        }

        selected = templates.get(
            category,
            [
                ("Modern Professional", "Clean professional layout."),
                ("Minimal Business", "Simple and elegant layout."),
                ("Premium Showcase", "Premium business presentation.")
            ]
        )

        recommendations = []

        for index, (name, description) in enumerate(selected):
            recommendations.append({
                "id": f"{category.lower().replace(' ', '-')}-{index + 1}",
                "name": name,
                "description": description,
                "reason": f"Designed for {category}",
                "style": name
            })

        session.recommendations = recommendations
        session.collected_data["onboarding_step"] = "template_selection"
        session.current_step = 4

        await WebsiteBuilderService.reply(
            session,
            f"Here are three designs created for your {category}. "
            "Select one to continue.",
            options=recommendations
        )

        await WebsiteBuilderService.save_session(session)

        return type("Result", (), {
            "message": session.messages[-1]["content"],
            "quick_actions": recommendations,
            "session": session
        })

    # ---------------------------------------------------------
    # WEBSITE GENERATION
    # ---------------------------------------------------------

    @staticmethod
    async def generate_website(session, user_id=None):

        collected = session.collected_data

        business_name = collected.get("Business Name")
        category = collected.get("Business Category")

        if not business_name or not category:
            raise HTTPException(
                400,
                "Business name and category are required."
            )

        if not collected.get("Logo"):
            if not user_id:
                user_id = session.user_id

            await WebsiteBuilderService.check_logo_and_continue(
                user_id,
                session,
                action=action,
                message=message
            )

            await WebsiteBuilderService.save_session(session)

            return type("Result", (), {
                "message": session.messages[-1]["content"],
                "quick_actions": session.messages[-1].get("options", []),
                "session": session
            })

        WebsiteBuilderService.add_ai_message(
            session,
            "Creating your website. Preparing your layout, content and images...",
            message_type="generation_status"
        )

        await WebsiteBuilderService.save_session(session)

        brand = collected.get("Brand Guidelines") or {}

        theme = WebsiteBuilderService.resolve_palette(
            category=category,
            brand_guidelines=brand
        )

        logo = collected["Logo"]

        offerings = collected.get("Products/Services", "")
        details = collected.get("industry_details", "")

        ai = AIProviderFactory.get_provider(preferred="openai")

        prompt = f"""
Create a complete professional website for this business.

BUSINESS NAME: {business_name}
BUSINESS CATEGORY: {category}
PRODUCTS/SERVICES: {offerings}
ADDITIONAL DETAILS: {details}
SELECTED TEMPLATE: {collected.get('selected_template_name')}

Return ONLY valid JSON with this structure:

{{
  "business_name": "{business_name}",
  "logo": "{logo}",
  "theme": {{
    "primary": "{theme['primary']}",
    "secondary": "{theme['secondary']}",
    "accent": "{theme['accent']}",
    "font": "outfit"
  }},
  "pages": [
    {{
      "name": "Home",
      "sections": [
        {{
          "type": "navbar",
          "title": "{business_name}",
          "logo": "{logo}",
          "navigation": ["Home", "About", "Products", "Contact"]
        }},
        {{
          "type": "hero",
          "title": "Business-specific headline",
          "subtitle": "Business-specific description",
          "cta": "Explore Now",
          "image_prompt": "Relevant professional photograph for {category}",
          "image_url": ""
        }},
        {{
          "type": "features",
          "title": "Our Products and Services",
          "items": [
            {{
              "title": "Real product or service",
              "description": "Relevant description",
              "image_prompt": "Photograph of this exact product or service",
              "image_url": ""
            }}
          ]
        }},
        {{
          "type": "about",
          "title": "About {business_name}",
          "description": "Business introduction"
        }},
        {{
          "type": "gallery",
          "title": "Our Gallery",
          "items": []
        }},
        {{
          "type": "contact",
          "title": "Contact Us"
        }},
        {{
          "type": "footer",
          "title": "{business_name}",
          "logo": "{logo}"
        }}
      ]
    }}
  ]
}}

RULES:

1. Every section must match the business category.
2. Generate relevant products and services.
3. Use professional image prompts.
4. Never use unrelated office or corporate images.
5. Do not invent phone numbers, addresses, prices, ratings,
   testimonials or customer counts.
6. Do not invent business contact details.
7. Preserve the selected template's design direction.
8. Include navbar, hero, content sections and footer.
9. Return valid JSON only.
"""

        try:
            result = await ai.generate_json(
                prompt,
                system_prompt=(
                    "You are a professional website designer. "
                    "Generate complete, industry-specific website JSON. "
                    "Never invent factual business information."
                ),
                temperature=0.3,
                max_tokens=8192
            )

        except Exception:
            logger.exception("Website generation failed")
            raise HTTPException(
                502,
                "Website generation failed. Please try again."
            )

        if not isinstance(result, dict) or not result.get("pages"):
            raise HTTPException(
                502,
                "The AI returned an invalid website structure."
            )

        pages = result["pages"]

        for page in pages:
            for section_index, section in enumerate(
                page.get("sections", [])
            ):

                if not isinstance(section, dict):
                    continue

                section_type = section.get("type", "")

                if section_type == "navbar":
                    section["logo"] = logo

                if section_type == "footer":
                    section["logo"] = logo

                if section_type == "hero":
                    section["image_url"] = (
                        WebsiteBuilderService.resolve_curated_image(
                            category,
                            section.get("image_prompt", category),
                            section_index,
                            True
                        )
                    )

                for item_index, item in enumerate(
                    section.get("items", [])
                ):
                    if isinstance(item, dict) and item.get("image_prompt"):
                        item["image_url"] = (
                            WebsiteBuilderService.resolve_curated_image(
                                category,
                                item["image_prompt"],
                                item_index,
                                False
                            )
                        )

        result["business_name"] = business_name
        result["logo"] = logo
        result["theme"] = theme

        project = WebsiteProject(
            user_id=session.user_id,
            business_id=collected.get("business_id"),
            business_name=business_name,
            session_id=str(session.id),
            template_id=str(session.selected_template or "default"),
            language=session.language or "English",
            pages=pages,
            theme=theme,
            status="draft",
            website_data=result
        )

        collection = await WebsiteBuilderService.get_project_collection()

        doc = project.model_dump(
            by_alias=True,
            exclude={"id"}
        )

        doc["logo"] = logo

        inserted = await collection.insert_one(doc)

        project.id = str(inserted.inserted_id)

        session.website_project_id = project.id
        session.current_step = 8

        collected["onboarding_step"] = "generated"

        await WebsiteBuilderService.reply(
            session,
            (
                f"Your website for {business_name} has been generated! "
                "You can now preview and edit it."
            ),
            data={
                "siteId": project.id,
                "generatedSiteData": result
            }
        )

        await WebsiteBuilderService.save_session(session)

        return type("Result", (), {
            "message": "Website generated successfully.",
            "quick_actions": [],
            "session": session,
            "site_id": project.id,
            "generated_site_data": doc
        })

    # ---------------------------------------------------------
    # WEBSITE REVISION
    # ---------------------------------------------------------

    @staticmethod
    async def revise_website(
        project_id: str,
        user_id: str,
        instructions: str
    ):

        site = await WebsiteBuilderService.get_website(
            project_id,
            user_id
        )

        if not site:
            raise HTTPException(404, "Website not found")

        ai = AIProviderFactory.get_provider(preferred="openai")

        prompt = f"""
Modify this existing website.

Business: {site.business_name}

Instructions:
{instructions}

Existing pages:
{json.dumps(site.pages, default=str)}

Rules:
- Preserve the business category.
- Preserve all unrelated sections.
- Modify only what the user requests.
- Never introduce unrelated images.
- Never invent business information.
- Return the complete updated pages array as JSON.
"""

        result = await ai.generate_json(
            prompt,
            system_prompt=(
                "You are an expert website editor. "
                "Make minimal and safe changes."
            ),
            temperature=0.2,
            max_tokens=8192
        )

        pages = result.get("pages") if isinstance(result, dict) else None

        if not pages:
            raise HTTPException(
                502,
                "The AI could not produce a valid website revision."
            )

        collection = await WebsiteBuilderService.get_project_collection()

        await collection.update_one(
            {
                "_id": ObjectId(project_id),
                "user_id": user_id
            },
            {
                "$set": {
                    "pages": pages,
                    "website_data.pages": pages,
                    "updated_at": datetime.now(timezone.utc)
                },
                "$inc": {"version": 1}
            }
        )

        site.pages = pages

        return site

    # ---------------------------------------------------------
    # DIRECT EDIT
    # ---------------------------------------------------------

    @staticmethod
    async def apply_website_edit(
        user_id: str,
        session_id: str,
        instruction: str,
        current_state: dict
    ):

        session = await WebsiteBuilderService.get_session(
            session_id,
            user_id
        )

        if not session:
            return {
                "action": "error",
                "message": "Website session not found."
            }

        category = session.collected_data.get(
            "Business Category",
            ""
        )

        # Detect explicit category conflicts.
        category_conflicts = {
            "flower": ["gym", "workout", "fitness equipment"],
            "gym": ["bouquet", "flowers", "floral arrangement"],
            "indian sweet shop": ["gym equipment", "fitness training"]
        }

        lower_category = category.lower()
        lower_instruction = instruction.lower()

        for business, conflicting_terms in category_conflicts.items():
            if business in lower_category:
                if any(term in lower_instruction for term in conflicting_terms):
                    return {
                        "action": "clarification_required",
                        "message": (
                            f"Your website is for a {category}. "
                            "This request may conflict with your business category. "
                            "Would you like to change the business theme?"
                        ),
                        "updated_state": current_state
                    }

        ai = AIProviderFactory.get_provider(preferred="openai")

        prompt = f"""
Edit the existing website.

Business category: {category}
Business name: {session.collected_data.get('Business Name')}

User instruction:
{instruction}

Current website:
{json.dumps(current_state, default=str)}

Return JSON:
{{
  "action": "update_text",
  "message": "Description of the change",
  "updated_state": {{}}
}}

Rules:
- Preserve unrelated content.
- Make only requested changes.
- Keep all images business-relevant.
- Never regenerate the entire site unless explicitly requested.
"""

        try:
            result = await ai.generate_json(
                prompt,
                system_prompt="You are a precise website editor.",
                temperature=0.2,
                max_tokens=8192
            )

            if not isinstance(result, dict):
                raise ValueError("Invalid AI response")

            updated = result.get("updated_state")

            if not isinstance(updated, dict):
                raise ValueError("Missing updated_state")

            # Persist the changed state to the actual website project.
            if session.website_project_id:
                collection = await WebsiteBuilderService.get_project_collection()

                await collection.update_one(
                    {
                        "_id": ObjectId(session.website_project_id),
                        "user_id": user_id
                    },
                    {
                        "$set": {
                            "website_data": updated,
                            "pages": updated.get("pages", []),
                            "theme": updated.get("theme", {}),
                            "updated_at": datetime.now(timezone.utc)
                        },
                        "$inc": {"version": 1}
                    }
                )

            return result

        except Exception as exc:
            logger.exception("Website edit failed")

            return {
                "action": "error",
                "message": (
                    "I couldn't apply that change. "
                    "Your existing website has not been changed."
                ),
                "updated_state": current_state
            }