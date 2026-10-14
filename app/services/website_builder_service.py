from bson import ObjectId
from datetime import datetime, timezone
import json
import uuid
from fastapi import HTTPException

from app.core.database import get_database
from app.models.website_builder import WebsiteProject, WebsiteBuilderSession
from app.schemas.website_builder import FrontendMessageResponse, FrontendSessionResponse
from app.services.business_service import BusinessService
from app.services.brand_service import get_brand_kit
from app.services.product_service import get_products
from app.ai.factory import AIProviderFactory

class WebsiteBuilderService:
    @staticmethod
    def resolve_curated_image(category: str = "", prompt: str = "", index: int = 0, is_hero: bool = False) -> str:
        text = f"{category} {prompt}".lower()
        
        GALLERIES = [
            (
                ["coffee", "cafe", "latte", "cappuccino", "espresso", "barista", "bakery", "bistro", "tea", "roast", "brew"],
                "https://images.unsplash.com/photo-1501339847302-ac426a4a7cbb?auto=format&fit=crop&w=1920&q=80",
                [
                    "https://images.unsplash.com/photo-1514432324607-a09d9b4aefdd?auto=format&fit=crop&w=800&q=80",
                    "https://images.unsplash.com/photo-1495474472287-4d71bcdd2085?auto=format&fit=crop&w=800&q=80",
                    "https://images.unsplash.com/photo-1517248135467-4c7edcad34c4?auto=format&fit=crop&w=800&q=80",
                    "https://images.unsplash.com/photo-1554118811-1e0d58224f24?auto=format&fit=crop&w=800&q=80",
                    "https://images.unsplash.com/photo-1447933601403-0c6688de566e?auto=format&fit=crop&w=800&q=80",
                    "https://images.unsplash.com/photo-1511920170033-f8396924c348?auto=format&fit=crop&w=800&q=80"
                ]
            ),
            (
                ["fashion", "cloth", "wear", "apparel", "boutique", "dress", "lehenga", "saree", "suit", "shirt", "outfit", "style"],
                "https://images.unsplash.com/photo-1441986300917-64674bd600d8?auto=format&fit=crop&w=1920&q=80",
                [
                    "https://images.unsplash.com/photo-1490481651871-ab68de25d43d?auto=format&fit=crop&w=800&q=80",
                    "https://images.unsplash.com/photo-1445205170230-053b83016050?auto=format&fit=crop&w=800&q=80",
                    "https://images.unsplash.com/photo-1469334031218-e382a71b716b?auto=format&fit=crop&w=800&q=80",
                    "https://images.unsplash.com/photo-1558769132-cb1aea458c5e?auto=format&fit=crop&w=800&q=80",
                    "https://images.unsplash.com/photo-1489987707025-afc232f7ea0f?auto=format&fit=crop&w=800&q=80"
                ]
            ),
            (
                ["restaurant", "food", "dining", "pizza", "burger", "meal", "chef", "culinary", "kitchen", "snack"],
                "https://images.unsplash.com/photo-1517248135467-4c7edcad34c4?auto=format&fit=crop&w=1920&q=80",
                [
                    "https://images.unsplash.com/photo-1555396273-367ea4eb4db5?auto=format&fit=crop&w=800&q=80",
                    "https://images.unsplash.com/photo-1504674900247-0877df9cc836?auto=format&fit=crop&w=800&q=80",
                    "https://images.unsplash.com/photo-1550547660-d9450f859349?auto=format&fit=crop&w=800&q=80",
                    "https://images.unsplash.com/photo-1565299624946-b28f40a0ae38?auto=format&fit=crop&w=800&q=80"
                ]
            ),
            (
                ["tech", "software", "app", "digital", "developer", "it", "code", "ai", "platform", "agency"],
                "https://images.unsplash.com/photo-1519389950473-47ba0277781c?auto=format&fit=crop&w=1920&q=80",
                [
                    "https://images.unsplash.com/photo-1460925895917-afdab827c52f?auto=format&fit=crop&w=800&q=80",
                    "https://images.unsplash.com/photo-1522071820081-009f0129c71c?auto=format&fit=crop&w=800&q=80",
                    "https://images.unsplash.com/photo-1551288049-bebda4e38f71?auto=format&fit=crop&w=800&q=80",
                    "https://images.unsplash.com/photo-1531403009284-440f080d1e12?auto=format&fit=crop&w=800&q=80"
                ]
            ),
            (
                ["salon", "beauty", "spa", "makeup", "hair", "skincare", "cosmetic", "massage"],
                "https://images.unsplash.com/photo-1560066984-138dadb4c035?auto=format&fit=crop&w=1920&q=80",
                [
                    "https://images.unsplash.com/photo-1522337360788-8b13dee7a37e?auto=format&fit=crop&w=800&q=80",
                    "https://images.unsplash.com/photo-1570172619644-dfd03ed5d881?auto=format&fit=crop&w=800&q=80",
                    "https://images.unsplash.com/photo-1512290900672-1f41334e2c99?auto=format&fit=crop&w=800&q=80",
                    "https://images.unsplash.com/photo-1527799820374-dcf8d9d4a388?auto=format&fit=crop&w=800&q=80"
                ]
            ),
            (
                ["gym", "fitness", "workout", "crossfit", "yoga", "trainer", "training", "exercise", "sport"],
                "https://images.unsplash.com/photo-1534438327276-14e5300c3a48?auto=format&fit=crop&w=1920&q=80",
                [
                    "https://images.unsplash.com/photo-1517838277536-f5f99be501cd?auto=format&fit=crop&w=800&q=80",
                    "https://images.unsplash.com/photo-1518611012118-696072aa579a?auto=format&fit=crop&w=800&q=80",
                    "https://images.unsplash.com/photo-1506126613408-eca07ce68773?auto=format&fit=crop&w=800&q=80"
                ]
            ),
            (
                ["real estate", "property", "home", "house", "interior", "architect", "villa", "apartment", "realty"],
                "https://images.unsplash.com/photo-1600585154340-be6161a56a0c?auto=format&fit=crop&w=1920&q=80",
                [
                    "https://images.unsplash.com/photo-1600596542815-ffad4c1539a9?auto=format&fit=crop&w=800&q=80",
                    "https://images.unsplash.com/photo-1600607687939-ce8a6c25118c?auto=format&fit=crop&w=800&q=80",
                    "https://images.unsplash.com/photo-1600566753376-12c8ab7fb75b?auto=format&fit=crop&w=800&q=80"
                ]
            ),
            (
                ["jewelry", "jewellery", "gold", "diamond", "ring", "necklace", "luxury", "watch"],
                "https://images.unsplash.com/photo-1515562141207-7a88fb7ce338?auto=format&fit=crop&w=1920&q=80",
                [
                    "https://images.unsplash.com/photo-1535632066927-ab7c9ab60908?auto=format&fit=crop&w=800&q=80",
                    "https://images.unsplash.com/photo-1599643478518-a784e5dc4c8f?auto=format&fit=crop&w=800&q=80",
                    "https://images.unsplash.com/photo-1522335789203-aabd1fc54bc9?auto=format&fit=crop&w=800&q=80"
                ]
            ),
            (
                ["health", "clinic", "doctor", "medical", "hospital", "dental", "dentist", "care", "wellness"],
                "https://images.unsplash.com/photo-1538108149393-fbbd81895907?auto=format&fit=crop&w=1920&q=80",
                [
                    "https://images.unsplash.com/photo-1579684385127-1ef15d508118?auto=format&fit=crop&w=800&q=80",
                    "https://images.unsplash.com/photo-1584515979956-d9f6e5d09982?auto=format&fit=crop&w=800&q=80",
                    "https://images.unsplash.com/photo-1505751172876-fa1923c5c528?auto=format&fit=crop&w=800&q=80"
                ]
            )
        ]
        
        default_hero = "https://images.unsplash.com/photo-1497366216548-37526070297c?auto=format&fit=crop&w=1920&q=80"
        default_items = [
            "https://images.unsplash.com/photo-1497215728101-856f4ea42174?auto=format&fit=crop&w=800&q=80",
            "https://images.unsplash.com/photo-1573496359142-b8d87734a5a2?auto=format&fit=crop&w=800&q=80",
            "https://images.unsplash.com/photo-1556761175-5973dc0f32e7?auto=format&fit=crop&w=800&q=80",
            "https://images.unsplash.com/photo-1521737711867-e3b97375f902?auto=format&fit=crop&w=800&q=80"
        ]
        
        for keywords, hero_img, item_imgs in GALLERIES:
            if any(k in text for k in keywords):
                if is_hero:
                    return hero_img
                return item_imgs[index % len(item_imgs)]
                
        if is_hero:
            return default_hero
        return default_items[index % len(default_items)]

    @staticmethod
    def resolve_palette(text: str = "", category: str = "", brand_guidelines: dict = None) -> dict:
        if brand_guidelines and isinstance(brand_guidelines, dict):
            p = brand_guidelines.get("primary_color")
            s = brand_guidelines.get("secondary_color")
            if p and str(p).startswith("#"):
                return {
                    "primary": str(p),
                    "secondary": str(s) if s and str(s).startswith("#") else str(p),
                    "accent": "#F59E0B",
                    "font": brand_guidelines.get("font") or "outfit"
                }

        combined = f"{text} {category}".lower()

        COLOR_KEYWORDS = [
            (["green", "emerald", "forest", "nature", "organic", "plant", "botanical"], "#059669", "#047857", "#10B981"),
            (["blue", "navy", "ocean", "royal", "sky"], "#1D4ED8", "#1E40AF", "#3B82F6"),
            (["red", "crimson", "ruby", "scarlet"], "#DC2626", "#B91C1C", "#EF4444"),
            (["purple", "violet", "lavender", "indigo"], "#7C3AED", "#6D28D9", "#8B5CF6"),
            (["pink", "rose", "blush", "pastel"], "#E11D48", "#BE123C", "#FB7185"),
            (["orange", "amber", "sunset", "peach"], "#EA580C", "#C2410C", "#F97316"),
            (["yellow", "gold", "golden"], "#D97706", "#B45309", "#FBBF24"),
            (["dark", "black", "charcoal", "luxury", "minimalist"], "#0F172A", "#1E293B", "#94A3B8"),
            (["brown", "coffee", "roast", "mocha", "terracotta"], "#78350F", "#92400E", "#D97706"),
            (["teal", "cyan", "turquoise"], "#0D9488", "#0F766E", "#14B8A6")
        ]
        for keywords, prim, sec, acc in COLOR_KEYWORDS:
            if any(k in combined for k in keywords):
                return {"primary": prim, "secondary": sec, "accent": acc, "font": "outfit"}

        if any(w in combined for w in ["coffee", "cafe", "espresso", "latte", "tea", "roast", "brew", "bistro"]):
            return {"primary": "#78350F", "secondary": "#92400E", "accent": "#D97706", "font": "outfit"}
        elif any(w in combined for w in ["fashion", "cloth", "wear", "apparel", "boutique", "dress", "lehenga", "saree"]):
            return {"primary": "#0F172A", "secondary": "#334155", "accent": "#BE185D", "font": "outfit"}
        elif any(w in combined for w in ["restaurant", "food", "dining", "pizza", "burger", "meal", "chef"]):
            return {"primary": "#DC2626", "secondary": "#B91C1C", "accent": "#F59E0B", "font": "outfit"}
        elif any(w in combined for w in ["tech", "software", "app", "digital", "developer", "it", "code", "ai"]):
            return {"primary": "#2563EB", "secondary": "#1D4ED8", "accent": "#06B6D4", "font": "outfit"}
        elif any(w in combined for w in ["salon", "beauty", "spa", "makeup", "hair", "skincare", "cosmetic"]):
            return {"primary": "#DB2777", "secondary": "#BE185D", "accent": "#F472B6", "font": "outfit"}
        elif any(w in combined for w in ["gym", "fitness", "workout", "crossfit", "yoga", "trainer"]):
            return {"primary": "#EA580C", "secondary": "#C2410C", "accent": "#10B981", "font": "outfit"}
        elif any(w in combined for w in ["real estate", "property", "home", "house", "interior", "architect"]):
            return {"primary": "#0D9488", "secondary": "#0F766E", "accent": "#0284C7", "font": "outfit"}
        elif any(w in combined for w in ["jewelry", "jewellery", "gold", "diamond", "ring", "luxury"]):
            return {"primary": "#B45309", "secondary": "#78350F", "accent": "#FBBF24", "font": "outfit"}
        elif any(w in combined for w in ["health", "clinic", "doctor", "medical", "hospital", "dental"]):
            return {"primary": "#0284C7", "secondary": "#0369A1", "accent": "#10B981", "font": "outfit"}
            
        return {"primary": "#4F46E5", "secondary": "#4338CA", "accent": "#F59E0B", "font": "outfit"}

    @staticmethod
    def resolve_brand_logo(b_name: str, primary_color: str, brand_guidelines: dict = None) -> str:
        if brand_guidelines and isinstance(brand_guidelines, dict) and brand_guidelines.get("logo_url"):
            return brand_guidelines["logo_url"]
            
        initial = (b_name[0] if b_name else "B").upper()
        clean_name = b_name[:20].strip()
        import urllib.parse
        svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 240 50" width="240" height="50">
  <defs>
    <linearGradient id="g" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="{primary_color}" />
      <stop offset="100%" stop-color="{primary_color}" stop-opacity="0.85" />
    </linearGradient>
  </defs>
  <rect x="2" y="5" width="40" height="40" rx="12" fill="url(#g)"/>
  <text x="22" y="32" font-family="'Outfit', sans-serif" font-size="22" font-weight="900" fill="#ffffff" text-anchor="middle">{initial}</text>
  <text x="52" y="32" font-family="'Outfit', sans-serif" font-size="20" font-weight="800" fill="{primary_color}">{clean_name}</text>
</svg>"""
        return f"data:image/svg+xml;utf8,{urllib.parse.quote(svg)}"

    @staticmethod
    async def get_session_collection():
        db = get_database()
        return db["website_builder_sessions"]

    @staticmethod
    async def get_project_collection():
        db = get_database()
        return db["website_projects"]

    @staticmethod
    async def get_website(project_id: str, user_id: str):
        collection = await WebsiteBuilderService.get_project_collection()
        if not ObjectId.is_valid(project_id):
            return None
        doc = await collection.find_one({"_id": ObjectId(project_id), "user_id": user_id})
        if doc:
            return WebsiteProject(**doc)
        return None

    @staticmethod
    async def save_session(session: WebsiteBuilderSession):
        collection = await WebsiteBuilderService.get_session_collection()
        update_data = session.model_dump(by_alias=True, exclude={"id", "created_at"})
        update_data["updated_at"] = datetime.now(timezone.utc)
        await collection.update_one({"_id": ObjectId(session.id)}, {"$set": update_data})

    @staticmethod
    async def create_session(user_id: str) -> WebsiteBuilderSession:
        collection = await WebsiteBuilderService.get_session_collection()
        await collection.update_many({"user_id": user_id, "status": "active"}, {"$set": {"status": "archived"}})

        session = WebsiteBuilderSession(
            user_id=user_id,
            messages=[
                {
                    "id": str(uuid.uuid4()),
                    "role": "ai",
                    "content": "Hi! I can build your custom website. Tell me what kind of website you want to create (e.g. online clothing website, coffee shop, real estate)!",
                    "type": "text"
                }
            ]
        )
        doc = session.model_dump(by_alias=True, exclude={"id"})
        result = await collection.insert_one(doc)
        session.id = str(result.inserted_id)
        return session

    @staticmethod
    async def get_session(session_id: str, user_id: str) -> WebsiteBuilderSession | None:
        collection = await WebsiteBuilderService.get_session_collection()
        if not ObjectId.is_valid(session_id):
            return None
        doc = await collection.find_one({"_id": ObjectId(session_id), "user_id": user_id})
        if doc:
            return WebsiteBuilderSession(**doc)
        return None

    @staticmethod
    async def load_existing_user_data(user_id: str, session: WebsiteBuilderSession):
        business = await BusinessService.get_business_by_owner(user_id)
        if business:
            session.collected_data["Business Name"] = business.business_name
            session.collected_data["Business Category"] = business.business_category
            session.collected_data["business_id"] = str(business.id)
            
            db = get_database()
            brand = await get_brand_kit(db, str(business.id))
            if brand:
                if isinstance(brand, dict):
                    brand.pop("id", None)
                    brand.pop("_id", None)
                    session.collected_data["Brand Guidelines"] = brand
                else:
                    session.collected_data["Brand Guidelines"] = brand.model_dump(by_alias=True, exclude={"id"})
                
            products = await get_products(db, str(business.id))
            if products:
                prod_list = []
                for p in products:
                    if isinstance(p, dict):
                        p.pop("id", None)
                        p.pop("_id", None)
                        prod_list.append(p)
                    else:
                        prod_list.append(p.model_dump(by_alias=True, exclude={"id"}))
                session.collected_data["Products"] = prod_list
            
        await WebsiteBuilderService.save_session(session)

    @staticmethod
    async def process_chat(session_id: str, user_id: str, message: str, language: str = None):
        session = await WebsiteBuilderService.get_session(session_id, user_id)
        if not session:
            raise Exception("Session not found")
            
        session.messages.append({
            "id": str(uuid.uuid4()),
            "role": "user",
            "content": message
        })
        
        lower_msg = message.lower()
        if any(x in lower_msg for x in ["you decide", "recommend", "i don't know", "anything is fine"]):
            return await WebsiteBuilderService.generate_recommendations(session)
            
        if any(x in lower_msg for x in ["build my website", "built my website", "generate my website", "create my website", "make my website"]):
            return await WebsiteBuilderService.generate_website(session)
            
        if session.current_step == 7 and any(x in lower_msg for x in ["yes", "ready", "sure", "ok", "okay", "build", "built", "generate"]):
            return await WebsiteBuilderService.generate_website(session)
            
        ai = AIProviderFactory.get_provider(preferred="gemini")
        extract_prompt = f"Extract structured fields from user message: '{message}'. Current collected data: {json.dumps(session.collected_data, default=str)}. Do NOT invent fake data. Return JSON with extracted fields using exactly these keys: 'Business Name', 'Business Category', 'Location', 'Phone', 'Products'."
        extracted = await ai.generate_json(extract_prompt, system_prompt="Extract business details from user messages using strict keys.")
        if extracted and not extracted.get("error"):
            for k, v in extracted.items():
                if v and str(v).strip() not in ["None", "null", ""]:
                    session.collected_data[k] = str(v).strip()
                    
        b_name = session.collected_data.get("Business Name")
        if not b_name or str(b_name).strip() in ["None", "null", "Your Brand", "the business", "A", "An", "The"]:
            b_cat = session.collected_data.get("Business Category")
            if b_cat and str(b_cat).strip() not in ["None", "null", "A", "An", "The"]:
                session.collected_data["Business Name"] = str(b_cat).strip().title()
            else:
                clean_msg = message.replace("website", "").replace("build", "").replace("create", "").replace("my", "").replace("want", "").replace("for", "").strip().title()
                if clean_msg and clean_msg not in ["A", "An", "The"]:
                    session.collected_data["Business Name"] = clean_msg
                    session.collected_data["Business Category"] = clean_msg

        chat_prompt = f"User prompt: '{message}'. Collected details: {json.dumps(session.collected_data, default=str)}. Respond in {session.language or 'English'}. Acknowledge their website request, summarize what brand/topic will be built, and ask if they would like to 'Recommend' templates or 'Build My Website'."
        chat_result = await ai.generate_text(chat_prompt, system_prompt="You are an expert AI website builder assistant. Keep it short, friendly, and enthusiastic.")
        reply_msg = chat_result.get("text", f"Awesome! I will create your {session.collected_data.get('Business Name', 'website')}. Would you like me to recommend templates or build your website directly?")
        
        actions = [{"label": "Recommend Templates", "action": "recommend"}, {"label": "Build My Website", "action": "generate"}]
             
        msg_obj = {
            "id": str(uuid.uuid4()),
            "role": "ai",
            "content": reply_msg,
            "type": "confirmation",
            "options": actions
        }
            
        session.messages.append(msg_obj)
        await WebsiteBuilderService.save_session(session)
        
        return type('obj', (object,), {'message': reply_msg, 'quick_actions': actions, 'session': session})

    @staticmethod
    async def generate_recommendations(session: WebsiteBuilderSession):
        ai = AIProviderFactory.get_provider(preferred="gemini")
        prompt = f"Generate exactly THREE website design recommendations for a business with data: {session.collected_data}. Return JSON with 'recommendations' array containing: id, name, description, reason, palette, style."
        result = await ai.generate_json(prompt, system_prompt="You are an expert web designer AI.")
        
        recs = result.get("recommendations", [])
        if len(recs) != 3:
            recs = [
                {"id": "rec1", "name": "Modern Fashion", "description": "Sleek and stylish layout", "reason": "Fits your online brand", "palette": "Purple/Black", "style": "Modern"},
                {"id": "rec2", "name": "Clean Minimal", "description": "Minimalist grid showcase", "reason": "Focus on products", "palette": "Blue/White", "style": "Minimal"},
                {"id": "rec3", "name": "Vibrant Store", "description": "Energetic and bold", "reason": "Attracts customer engagement", "palette": "Pink/Gold", "style": "Bold"}
            ]
        
        session.recommendations = recs
        session.current_step = 5
        reply_msg = "Here are 3 website style recommendations tailored for your prompt. Please select one to proceed!"
        
        msg_obj = {
            "id": str(uuid.uuid4()),
            "role": "ai",
            "content": reply_msg,
            "type": "recommendation",
            "options": recs
        }
        session.messages.append(msg_obj)
        await WebsiteBuilderService.save_session(session)
        return type('obj', (object,), {'message': reply_msg, 'quick_actions': [], 'session': session})

    @staticmethod
    async def select_template(session_id: str, user_id: str, template_id: str) -> WebsiteBuilderSession:
        session = await WebsiteBuilderService.get_session(session_id, user_id)
        if not session:
            raise Exception("Session not found")
            
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
        logo_url = WebsiteBuilderService.resolve_brand_logo(b_name, theme_data["primary"], brand_guidelines)

        # Dynamic topic-aligned schema example with rich multi-sections
        schema_example = json.dumps({
            "theme": theme_data,
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
        ai = AIProviderFactory.get_provider(preferred="gemini")
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
        )
        
        try:
            result = await ai.generate_json(
                prompt,
                system_prompt=f"You are an expert AI website generator for {b_cat}. Return JSON strictly matching the requested structure. Be creative, attractive, and fast.",
                temperature=0.2,
                max_tokens=8192
            )
        except Exception as e:
            import logging
            logging.error(f"AI generation failed: {e}")
            result = {"error": str(e)}
        
        if not result or result.get("error") or not result.get("pages"):
             result = json.loads(schema_example)
        
        # Merge validated theme
        g_theme = result.get("theme", {})
        if isinstance(g_theme, dict):
            p_col = g_theme.get("primary")
            s_col = g_theme.get("secondary")
            if p_col and str(p_col).startswith("#"):
                theme_data["primary"] = str(p_col)
            if s_col and str(s_col).startswith("#"):
                theme_data["secondary"] = str(s_col)

        logo_url = WebsiteBuilderService.resolve_brand_logo(b_name, theme_data["primary"], brand_guidelines)
        result["theme"] = theme_data
        result["logo"] = logo_url
        result["business_name"] = b_name

        raw_pages = result.get("pages", [])
        if not isinstance(raw_pages, list) or len(raw_pages) == 0:
             raw_pages = json.loads(schema_example)["pages"]
             
        for page in raw_pages:
            for s_idx, section in enumerate(page.get("sections", [])):
                if section.get("type") == "hero":
                    if not section.get("image_url") or "image.pollinations.ai" in section.get("image_url", ""):
                        section["image_url"] = WebsiteBuilderService.resolve_curated_image(
                            category=b_cat,
                            prompt=section.get("image_prompt", "") or section.get("title", ""),
                            index=s_idx,
                            is_hero=True
                        )
                for i_idx, item in enumerate(section.get("items", [])):
                    if not item.get("image_url") or "image.pollinations.ai" in item.get("image_url", ""):
                        item["image_url"] = WebsiteBuilderService.resolve_curated_image(
                            category=b_cat,
                            prompt=item.get("image_prompt", "") or item.get("title", ""),
                            index=i_idx + s_idx,
                            is_hero=False
                        )

        project = WebsiteProject(
            user_id=session.user_id,
            business_id=session.collected_data.get("business_id"),
            business_name=b_name,
            session_id=str(session.id),
            template_id=str(session.selected_template) if session.selected_template is not None else "default",
            language=session.language or "English",
            pages=raw_pages,
            theme=theme_data,
            status="published",
            website_data=result
        )
        
        collection = await WebsiteBuilderService.get_project_collection()
        doc = project.model_dump(by_alias=True, exclude={"id"})
        doc["logo"] = logo_url
        doc["theme"] = theme_data
        doc["business_name"] = b_name
        res = await collection.insert_one(doc)
        project.id = str(res.inserted_id)
        
        session.website_project_id = project.id
        session.current_step = 8
        session.messages.append({
            "id": str(uuid.uuid4()),
            "role": "ai",
            "content": f"Website for '{b_name}' generated successfully! You can preview it on the right sidebar or click 'Preview Website'.",
            "type": "text"
        })
        await WebsiteBuilderService.save_session(session)
        return type('obj', (object,), {'message': "Generated", 'quick_actions': [], 'session': session, 'site_id': project.id, 'generated_site_data': doc})

    @staticmethod
    async def revise_website(project_id: str, user_id: str, instructions: str) -> WebsiteProject:
        site = await WebsiteBuilderService.get_website(project_id, user_id)
        if not site:
            raise HTTPException(status_code=404, detail="Website not found")
            
        ai = AIProviderFactory.get_provider(preferred="gemini")
        prompt = f"Here is a website JSON: {json.dumps(site.pages)}\n\nThe user wants these revisions: '{instructions}'. Modify the JSON to apply the revisions. CRITICAL: Return ONLY valid JSON for the 'pages' array in the exact same schema. Do not add markdown fences."
        result = await ai.generate_text(prompt, system_prompt="You are an expert web designer. Return ONLY the JSON array representing the revised pages.")
        
        raw_text = result.get("text", "[]").strip()
        import re
        raw_text = re.sub(r'<think>.*?</think>', '', raw_text, flags=re.DOTALL).strip()
        
        if "```" in raw_text:
            parts = raw_text.split("```")
            for part in parts:
                cleaned = part.strip()
                if cleaned.startswith("json"):
                    cleaned = cleaned[4:].strip()
                if cleaned.startswith("[") or cleaned.startswith("{"):
                    raw_text = cleaned
                    break
                    
        first_bracket = raw_text.find("[")
        last_bracket = raw_text.rfind("]")
        if first_bracket != -1 and last_bracket != -1:
            raw_text = raw_text[first_bracket:last_bracket+1]
            
        try:
            revised_pages = json.loads(raw_text)
            if isinstance(revised_pages, dict) and "pages" in revised_pages:
                revised_pages = revised_pages["pages"]
        except:
            raise Exception("Failed to parse AI revision")
            
        for page in revised_pages:
            for s_idx, section in enumerate(page.get("sections", [])):
                if section.get("type") == "hero":
                    if not section.get("image_url") or "image.pollinations.ai" in section.get("image_url", ""):
                        section["image_url"] = WebsiteBuilderService.resolve_curated_image(
                            category=site.business_name or "business",
                            prompt=section.get("image_prompt", "") or section.get("title", ""),
                            index=s_idx,
                            is_hero=True
                        )
                for i_idx, item in enumerate(section.get("items", [])):
                    if not item.get("image_url") or "image.pollinations.ai" in item.get("image_url", ""):
                        item["image_url"] = WebsiteBuilderService.resolve_curated_image(
                            category=site.business_name or "business",
                            prompt=item.get("image_prompt", "") or item.get("title", ""),
                            index=i_idx + s_idx,
                            is_hero=False
                        )
                        
        site.pages = revised_pages
        collection = await WebsiteBuilderService.get_project_collection()
        await collection.update_one({"_id": ObjectId(project_id)}, {"$set": {"pages": revised_pages}})
        
        return site

    @staticmethod
    async def apply_website_edit(user_id: str, session_id: str, instruction: str, current_state: dict):
        """
        Executes the AI logic for Phase 2: Natural Language to Structured JSON Edit.
        """
        from app.ai.factory import AIProviderFactory
        import json
        import re

        # Grab Business Profile
        # db = get_database()
        # In a full implementation we'd inject the business context, brand kit, etc.
        
        system_prompt = """You are an AI Website Editor for SevenUnique AI.
Your job is to modify an existing website based on the user's natural-language instructions.
You are NOT generating a completely new website unless explicitly requested.
You must preserve all existing website content and structure unless the user asks you to change it.
Identify the exact page, section, component, property or style that the user wants to modify.
Make the smallest safe change necessary.

Allowed actions:
update_theme, update_text, update_style, add_section, remove_section, replace_image, add_logo, update_navigation.

Return structured JSON ONLY matching this exact format:
{
  "action": "...",
  "target": "...",
  "changes": {},
  "message": "Human-readable confirmation message."
}"""

        prompt = f"""User Instruction: {instruction}
Current Website State:
{json.dumps(current_state, indent=2)[:2000]} # Truncated for token limit in stub

Return ONLY valid JSON with the modification."""

        ai_provider = AIProviderFactory.get_provider(preferred="gemini")
        try:
            res = await ai_provider.generate_text(
                prompt=prompt,
                system_prompt=system_prompt,
                max_tokens=2048
            )
            raw = res.get("text", "{}").strip()
            raw = re.sub(r'<think>.*?</think>', '', raw, flags=re.DOTALL).strip()
            
            if "`" in raw:
                parts = raw.split("`")
                for part in parts:
                    cleaned = part.strip()
                    if cleaned.startswith("json"):
                        cleaned = cleaned[4:].strip()
                    if cleaned.startswith("{"):
                        raw = cleaned
                        break
                        
            first_brace = raw.find("{")
            last_brace = raw.rfind("}")
            if first_brace != -1 and last_brace != -1:
                raw = raw[first_brace:last_brace + 1]
                
            data = json.loads(raw)
            return data
            
        except Exception as e:
            return {"action": "error", "message": f"AI Edit Failed: {str(e)}"}

    @staticmethod
    async def generate_pdf_snapshot(website_id: str) -> str:
        """
        Phase 4: Generates a PDF snapshot of the finalized website.
        In a production environment, this would spin up Pyppeteer/Playwright
        to render the JSON state to HTML and capture a PDF.
        """
        # Mock PDF generation
        pdf_filename = f"website_{website_id}_snapshot.pdf"
        # ... logic to render and save to S3 or local ...
        return f"/downloads/pdfs/{pdf_filename}"

    @staticmethod
    async def generate_zip_archive(website_state: dict, website_id: str) -> str:
        """
        Phase 4: Generates a downloadable ZIP of the website.
        Packages the structured JSON into an HTML/React boilerplate.
        """
        import zipfile
        import io
        
        # Mock ZIP generation
        zip_filename = f"website_{website_id}_source.zip"
        # In production:
        # 1. Iterate over website_state['pages']
        # 2. Convert each section JSON to HTML templates
        # 3. Create style.css from website_state['theme']
        # 4. Write to zip archive
        return f"/downloads/archives/{zip_filename}"
