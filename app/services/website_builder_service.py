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
            
        ai = AIProviderFactory.get_provider()
        extract_prompt = f"Extract structured fields from user message: '{message}'. Current collected data: {json.dumps(session.collected_data, default=str)}. Do NOT invent fake data. Return JSON with extracted fields using exactly these keys: 'Business Name', 'Business Category', 'Location', 'Phone', 'Products'."
        extracted = await ai.generate_json(extract_prompt, system_prompt="Extract business details from user messages using strict keys.")
        if extracted and not extracted.get("error"):
            for k, v in extracted.items():
                if v and str(v).strip() not in ["None", "null", ""]:
                    session.collected_data[k] = str(v).strip()
                    
        b_name = session.collected_data.get("Business Name")
        if not b_name or str(b_name).strip() in ["None", "null", "Your Brand", "the business"]:
            b_cat = session.collected_data.get("Business Category")
            if b_cat and str(b_cat).strip() not in ["None", "null"]:
                session.collected_data["Business Name"] = str(b_cat).strip().title()
            else:
                clean_msg = message.replace("website", "").replace("build", "").replace("create", "").replace("my", "").replace("want", "").replace("for", "").strip().title()
                if clean_msg:
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
        ai = AIProviderFactory.get_provider()
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
        
        b_name = session.collected_data.get("Business Name") or session.collected_data.get("Business Category") or full_user_intent.title()
        b_cat = session.collected_data.get("Business Category", full_user_intent)

        # Dynamic topic-aligned schema example & fallback
        schema_example = json.dumps({
            "theme": {"primary": "purple", "font": "inter"},
            "pages": [
                {
                    "name": "Home",
                    "sections": [
                        {"type": "hero", "title": f"Welcome to {b_name}", "subtitle": f"Your trusted destination for premium {b_cat} services & products.", "cta": f"Explore {b_cat}", "image_prompt": f"high quality beautiful {b_cat} background banner", "image_url": ""},
                        {
                            "type": "features", 
                            "title": f"Featured {b_cat} Highlights", 
                            "items": [
                                {"title": f"Top Quality {b_cat}", "description": f"Exceptional quality and professional standards for all your {b_cat} needs.", "image_prompt": f"hd professional photo of {b_name} {b_cat} showcase", "image_url": ""},
                                {"title": "Specialized Solutions", "description": f"Customized features and tailored packages designed for {b_cat}.", "image_prompt": f"high quality {b_cat} service feature banner", "image_url": ""},
                                {"title": "Premium Experience", "description": f"Delivering satisfaction and top performance in {b_cat}.", "image_prompt": f"modern sleek design for {b_cat}", "image_url": ""}
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
                            "items": [
                                {"title": "Our Mission", "description": f"How {b_name} strives to deliver unmatched excellence in {b_cat}.", "image_prompt": f"professional team working on {b_cat}"},
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
                            "title": f"Our {b_cat} Offerings", 
                            "items": [
                                {"title": f"Flagship {b_cat} Collection", "description": f"Best-in-class products and gear for {b_cat}.", "image_prompt": f"featured product showcase {b_cat}"},
                                {"title": f"Custom {b_cat} Packages", "description": f"Tailored options engineered specifically for your {b_cat} requirements.", "image_prompt": f"custom designed {b_cat} item"},
                                {"title": f"Popular Essentials", "description": f"Top trending items highly recommended in {b_cat}.", "image_prompt": f"popular essential collection {b_cat}"}
                            ]
                        }
                    ]
                },
                {
                    "name": "Services",
                    "sections": [
                        {
                            "type": "features", 
                            "title": f"Professional {b_cat} Services", 
                            "items": [
                                {"title": "Expert Consultation", "description": f"Professional advisory and strategic planning for {b_cat}.", "image_prompt": f"professional consultant working on {b_cat}"},
                                {"title": "Dedicated Support", "description": f"24/7 client service and complete care for all {b_cat} queries.", "image_prompt": f"customer care team supporting {b_cat}"}
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
                            "items": [
                                {"title": "Email Us", "description": f"contact@{b_name.lower().replace(' ', '')}.com", "image_prompt": "modern contact support desk email"},
                                {"title": "Phone Helpline", "description": "+1 (800) 555-0199", "image_prompt": "phone hotline customer support"}
                            ]
                        }
                    ]
                },
                {
                    "name": "WhatsApp",
                    "sections": [
                        {"type": "hero", "title": "WhatsApp Support", "subtitle": f"Connect directly with our {b_cat} specialists on WhatsApp 24/7.", "cta": "Chat on WhatsApp"}
                    ]
                },
                {
                    "name": "Google Map",
                    "sections": [
                        {
                            "type": "features", 
                            "title": "Location & Address", 
                            "items": [
                                {"title": "Main Office & Showroom", "description": f"742 Innovation Parkway, Suite 100", "image_prompt": f"modern building exterior facade for {b_cat}"}
                            ]
                        }
                    ]
                }
            ]
        })
        ai = AIProviderFactory.get_provider()
        prompt = (
            f"""Generate a custom structured website JSON based strictly on the user's business topic and prompt.

User Prompt / Intent: '{full_user_intent}'
Business Name: '{b_name}'
Business Topic / Category: '{b_cat}'
Language: {session.language or 'English'}.

CRITICAL REQUIREMENTS:
1. You MUST heavily prioritize and implement ALL specific instructions, custom content, themes, and image concepts mentioned in the 'User Prompt / Intent' above.
2. EVERYTHING (titles, descriptions, section headlines, image_prompts) MUST be tailored to the topic '{b_cat}', business name '{b_name}', AND the user's specific prompt.
3. Every item MUST include a detailed English 'image_prompt' that describes crisp visual photography relevant to '{b_cat}'.
4. Generate ALL 7 pages specified in the schema: Home, About, Products, Services, Contact, WhatsApp, and Google Map.
5. Return ONLY valid JSON matching this structure: {schema_example}."""
        )
        
        try:
            result = await ai.generate_json(prompt, system_prompt=f"You are an expert AI website generator for {b_cat}. Return JSON strictly matching the requested structure.")
        except Exception as e:
            import logging
            logging.error(f"AI generation failed: {e}")
            result = {"error": str(e)}
        
        if not result or result.get("error") or not result.get("pages"):
             result = json.loads(schema_example)
        
        raw_pages = result.get("pages", [])
        if not isinstance(raw_pages, list) or len(raw_pages) == 0:
             raw_pages = json.loads(schema_example)["pages"]
             
        import urllib.parse
        for page in raw_pages:
            for section in page.get("sections", []):
                # For hero sections with an image prompt
                if section.get("type") == "hero" and section.get("image_prompt"):
                    if not section.get("image_url"):
                        prompt_encoded = urllib.parse.quote(section["image_prompt"])
                        section["image_url"] = f"https://image.pollinations.ai/prompt/{prompt_encoded}?width=1920&height=1080&nologo=true"
                # For features sections with items
                for item in section.get("items", []):
                    if item.get("image_prompt") and not item.get("image_url"):
                        prompt_encoded = urllib.parse.quote(item["image_prompt"])
                        item["image_url"] = f"https://image.pollinations.ai/prompt/{prompt_encoded}?width=800&height=600&nologo=true"

        project = WebsiteProject(
            user_id=session.user_id,
            business_id=session.collected_data.get("business_id"),
            business_name=b_name,
            session_id=str(session.id),
            template_id=str(session.selected_template) if session.selected_template is not None else "default",
            language=session.language or "English",
            pages=raw_pages,
            theme=result.get("theme", {}),
            status="published",
            website_data=result
        )
        
        collection = await WebsiteBuilderService.get_project_collection()
        doc = project.model_dump(by_alias=True, exclude={"id"})
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
            
        ai = AIProviderFactory.get_provider()
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
            
        import urllib.parse
        for page in revised_pages:
            for section in page.get("sections", []):
                if section.get("type") == "hero" and section.get("image_prompt"):
                    if not section.get("image_url"):
                        prompt_encoded = urllib.parse.quote(section["image_prompt"])
                        section["image_url"] = f"https://image.pollinations.ai/prompt/{prompt_encoded}?width=1920&height=1080&nologo=true"
                for item in section.get("items", []):
                    if item.get("image_prompt") and not item.get("image_url"):
                        prompt_encoded = urllib.parse.quote(item["image_prompt"])
                        item["image_url"] = f"https://image.pollinations.ai/prompt/{prompt_encoded}?width=800&height=600&nologo=true"
                        
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

        ai_provider = AIProviderFactory.get_provider()
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
