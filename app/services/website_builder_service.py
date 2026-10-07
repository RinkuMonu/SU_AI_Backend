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
    async def process_chat(session_id: str, user_id: str, message: str, language: str = None, data: dict = None):
        session = await WebsiteBuilderService.get_session(session_id, user_id)
        if not session:
            raise Exception("Session not found")
            
        session.messages.append({
            "id": str(uuid.uuid4()),
            "role": "user",
            "content": message
        })
        
        lower_msg = message.lower()
        if any(x in lower_msg for x in ["build my website", "built my website", "generate my website", "create my website", "make my website"]):
            if session.collected_data.get("Business Name"):
                return await WebsiteBuilderService.generate_website(session)
            
        if session.current_step == 7 and any(x in lower_msg for x in ["yes", "ready", "sure", "ok", "okay", "build", "built", "generate"]):
            return await WebsiteBuilderService.generate_website(session)
            
        ai = AIProviderFactory.get_provider()
        
        # 1. Fetch Business Profile if not checked yet
        if not session.collected_data.get("profile_checked"):
            try:
                from app.core.database import get_database
                db = get_database()
                business_profile = await db.business.find_one({"owner_id": user_id})
                if business_profile:
                    session.collected_data["Business Name"] = business_profile.get("name")
                    session.collected_data["Business Category"] = business_profile.get("category")
                    session.collected_data["Location"] = business_profile.get("location")
                    session.collected_data["Description"] = business_profile.get("description")
                    session.collected_data["Website"] = business_profile.get("website")
                    session.collected_data["Target Audience"] = business_profile.get("target_customer")
                    session.collected_data["Email"] = business_profile.get("contact_email")
                    session.collected_data["Phone"] = business_profile.get("contact_phone")
                    session.collected_data["Instagram"] = business_profile.get("instagram")
                    session.collected_data["profile_found"] = True
            except:
                pass
            session.collected_data["profile_checked"] = True

        # 2. Extract fields
        extract_system = "Extract fields into JSON."
        extract_prompt = f"""Extract from: '{message}'.
Data: {json.dumps(session.collected_data, default=str)}
Keys: 'Language', 'Business Name', 'Business Category', 'Description', 'Location', 'Website', 'Website Goal', 'Website Type', 'Target Audience', 'Google Maps', 'Phone', 'Email', 'WhatsApp', 'Business Hours', 'Social Media'. Return JSON with NEW keys."""
        
        try:
            extracted = await ai.generate_json(extract_prompt, system_prompt=extract_system)
            if extracted and not extracted.get("error"):
                for k, v in extracted.items():
                    if v and str(v).strip() not in ["None", "null", ""]:
                        session.collected_data[k] = str(v).strip()
        except:
            pass

        if session.collected_data.get("Language"):
            session.language = session.collected_data.get("Language")
            

        # Logo Interception Flow
        import urllib.parse
        if data and data.get("action") == "upload_logo" and data.get("base64"):
            session.collected_data["Logo"] = data.get("base64")
            session.collected_data["logo_status"] = "finalized"
            session.collected_data["logo_source"] = "uploaded"
            reply_msg = "✅ Your logo has been uploaded. Is this logo okay, or would you like to modify it?"
            msg_obj = {
                "id": str(uuid.uuid4()),
                "role": "ai",
                "content": reply_msg,
                "type": "text",
                "data": {"logo_url": data.get("base64")},
                "options": [{"label": "Keep this logo", "action": "keep_logo"}, {"label": "Modify this logo", "action": "modify_logo"}]
            }
            session.messages.append(msg_obj)
            await WebsiteBuilderService.save_session(session)
            return type('obj', (object,), {'message': reply_msg, 'quick_actions': msg_obj["options"], 'session': session})

        elif data and data.get("action") == "create_logo":
            b_name = session.collected_data.get("Business Name", "Your Business")
            urls = []
            for style in ["modern", "elegant", "minimal"]:
                prompt_encoded = urllib.parse.quote(f"{style} logo for {b_name} high quality")
                urls.append(f"https://image.pollinations.ai/prompt/{prompt_encoded}?width=512&height=512&nologo=true&seed={uuid.uuid4().hex[:5]}")
            
            session.collected_data["generated_logos"] = urls
            reply_msg = "Here are 3 logo options based on your business. Which one would you like to use?"
            msg_obj = {
                "id": str(uuid.uuid4()),
                "role": "ai",
                "content": reply_msg,
                "type": "text",
                "data": {"images": urls},
                "options": [{"label": "Logo 1", "action": "select_logo_1"}, {"label": "Logo 2", "action": "select_logo_2"}, {"label": "Logo 3", "action": "select_logo_3"}]
            }
            session.messages.append(msg_obj)
            await WebsiteBuilderService.save_session(session)
            return type('obj', (object,), {'message': reply_msg, 'quick_actions': msg_obj["options"], 'session': session})

        elif data and data.get("action") in ["select_logo_1", "select_logo_2", "select_logo_3"]:
            idx = int(data.get("action")[-1]) - 1
            selected = session.collected_data.get("generated_logos", [])[idx]
            session.collected_data["Logo"] = selected
            session.collected_data["logo_source"] = "generated"
            reply_msg = "Great! You've selected this logo. Would you like to modify it?"
            msg_obj = {
                "id": str(uuid.uuid4()),
                "role": "ai",
                "content": reply_msg,
                "type": "text",
                "data": {"logo_url": selected},
                "options": [{"label": "Keep this logo", "action": "keep_logo"}, {"label": "Modify this logo", "action": "modify_logo"}]
            }
            session.messages.append(msg_obj)
            await WebsiteBuilderService.save_session(session)
            return type('obj', (object,), {'message': reply_msg, 'quick_actions': msg_obj["options"], 'session': session})

        elif data and data.get("action") == "use_existing_logo":
            session.collected_data["Logo"] = session.collected_data.get("Existing Logo")
            session.collected_data["logo_source"] = "existing"
            session.collected_data["logo_status"] = "finalized"
            reply_msg = "Perfect! I'll use this logo on your website."
            msg_obj = {
                "id": str(uuid.uuid4()),
                "role": "ai",
                "content": reply_msg,
                "type": "text",
                "data": {"logo_url": session.collected_data.get("Logo")},
            }
            session.messages.append(msg_obj)
            await WebsiteBuilderService.save_session(session)
            return type('obj', (object,), {'message': reply_msg, 'quick_actions': [], 'session': session})

        elif data and data.get("action") == "keep_logo":
            session.collected_data["logo_status"] = "finalized"
            reply_msg = "Perfect! I'll use this logo on your website."
            msg_obj = {
                "id": str(uuid.uuid4()),
                "role": "ai",
                "content": reply_msg,
                "type": "text",
                "data": {"logo_url": session.collected_data.get("Logo")},
            }
            session.messages.append(msg_obj)
            await WebsiteBuilderService.save_session(session)
            return type('obj', (object,), {'message': reply_msg, 'quick_actions': [], 'session': session})

        elif data and data.get("action") == "modify_logo":
            reply_msg = "What would you like to change in the logo? (e.g., 'Make it blue', 'Change the font')"
            session.collected_data["logo_status"] = "modifying"
            msg_obj = {
                "id": str(uuid.uuid4()),
                "role": "ai",
                "content": reply_msg,
                "type": "text",
            }
            session.messages.append(msg_obj)
            await WebsiteBuilderService.save_session(session)
            return type('obj', (object,), {'message': reply_msg, 'quick_actions': [], 'session': session})

        if session.collected_data.get("logo_status") == "modifying":
            try:
                prompt_encoded = urllib.parse.quote(f"{message} logo for {session.collected_data.get('Business Name', 'business')} high quality")
                new_url = f"https://image.pollinations.ai/prompt/{prompt_encoded}?width=512&height=512&nologo=true&seed={uuid.uuid4().hex[:5]}"
                session.collected_data["Logo"] = new_url
                reply_msg = "Here's the modified version. Is this okay?"
                msg_obj = {
                    "id": str(uuid.uuid4()),
                    "role": "ai",
                    "content": reply_msg,
                    "type": "text",
                    "data": {"logo_url": new_url},
                    "options": [{"label": "Yes, keep this logo", "action": "keep_logo"}, {"label": "Modify again", "action": "modify_logo"}]
                }
                session.messages.append(msg_obj)
                await WebsiteBuilderService.save_session(session)
                return type('obj', (object,), {'message': reply_msg, 'quick_actions': msg_obj["options"], 'session': session})
            except:
                pass
        # 3. Consultant Response
        consultant_system = """You are an AI Website Builder Consultant. 
Keep your response EXTREMELY short, punchy, and direct (max 1 or 2 short sentences). 
Ask EXACTLY ONE missing question based on the collected data. 
If all essential data is collected, ask if they want to 'Recommend templates' or 'Build My Website'. Do NOT write long paragraphs."""

        consultant_prompt = f"""Data: {json.dumps(session.collected_data, default=str)}
User Message: '{message}'
Language: {session.language or 'English'}
Respond very briefly."""

        try:
            chat_result = await ai.generate_text(consultant_prompt, system_prompt=consultant_system)
            reply_msg = chat_result.get("text", "Got it! What else would you like to add?")
        except:
            reply_msg = "Could you tell me more about your business?"

        # 4. Quick Actions
        actions = []
        lower_reply = reply_msg.lower()
        if "language" in lower_reply and not session.language:
            actions = [{"label": "English", "action": "lang_en"}, {"label": "Hindi", "action": "lang_hi"}, {"label": "Hinglish", "action": "lang_hin"}]
        elif "existing website" in lower_reply:
            actions = [{"label": "Yes", "action": "has_website"}, {"label": "No", "action": "no_website"}]
        elif "google maps" in lower_reply:
            actions = [{"label": "Yes", "action": "yes_maps"}, {"label": "No", "action": "no_maps"}]
        elif "recommend" in lower_reply and "build" in lower_reply:
            actions = [{"label": "Recommend Templates", "action": "recommend"}, {"label": "Build My Website", "action": "generate"}]
        elif session.collected_data.get("profile_found") and "correct" in lower_reply:
            actions = [{"label": "Yes, continue", "action": "yes_continue"}, {"label": "Edit information", "action": "edit_info"}]
            session.collected_data["profile_found"] = False

        if any(x in lower_msg for x in ["you decide", "recommend"]) and ("template" in lower_msg or "recommend" in lower_msg):
            return await WebsiteBuilderService.generate_recommendations(session)

        msg_obj = {
            "id": str(uuid.uuid4()),
            "role": "ai",
            "content": reply_msg,
            "type": "confirmation" if actions else "text",
        }
        if actions:
            msg_obj["options"] = actions
            
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
            "logo": {"source": "uploaded", "url": "https://example.com/logo.png"},
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
