import json
import logging
import re
from typing import Dict, Any, Optional

from app.core.config import settings
from app.ai.factory import AIProviderFactory
from app.services.business_service import BusinessService
from app.services.brand_service import get_brand_kit
from app.ai.services.post_generation import PostGenerationService

logger = logging.getLogger(__name__)


class AgentService:
    """
    UNI AI Agent Service: Parses natural language inputs (Hindi/Hinglish/English)
    powered directly by Google Gemini API and routes them to appropriate tools
    or returns conversational marketing advice and generation.
    """

    def _get_gemini_client(self):
        if not settings.GEMINI_API_KEY:
            return None
        try:
            import google.genai as genai
            return genai.Client(api_key=settings.GEMINI_API_KEY)
        except Exception as e:
            logger.warning(f"Could not initialize google.genai Client: {e}")
            return None

    async def _parse_intent_and_respond(self, command: str, business_info: dict, language: str) -> Dict[str, Any]:
        prompt = f"""You are 'UNI AI Assistant', an intelligent, conversational, and energetic AI marketing co-pilot designed specifically for Indian businesses, entrepreneurs, and creators.
You natively speak Hindi, Hinglish, and English naturally, politely, and effectively.

Business Context:
- Brand Name: {business_info.get('name', 'My Brand')}
- Industry: {business_info.get('category', 'Retail & Lifestyle')}
- Details: {business_info.get('description', '')}
- Preferred Language: {language}

User Message / Request:
"{command}"

Analyze the user's intent:
1. "create_post": If the user wants to generate/create a social media post, image, banner, graphic, flyer, poster, or photo.
2. "create_reel": If the user wants to generate/create a reel, short video, TikTok, or video script.
3. "generate_festival_campaign": If the user specifically asks for a festival marketing campaign (e.g. Diwali, Holi, Eid, Navratri).
4. "competitor_analysis": If the user asks for competitor analysis, rival comparison, market positioning, or SWOT analysis.
5. "website_analysis": If the user asks for a website audit, landing page review, SEO analysis, or conversion optimization.
6. "trend_analysis": If the user asks for social media trends, viral hooks, hashtag strategy, or trend forecasting.
7. "product_marketing": If the user asks for product marketing copy, buyer personas, USPs, or launch angles.
8. "brand_strategy": If the user asks for brand guidelines, brand voice, color psychology, or content pillars.
9. "chat": For ALL other requests — including general marketing advice, brainstorming, questions, greetings, or feedback.

Return ONLY a valid, parseable JSON object without markdown code blocks, following this exact schema:
{{
  "action": "create_post" | "create_reel" | "generate_festival_campaign" | "competitor_analysis" | "website_analysis" | "trend_analysis" | "product_marketing" | "brand_strategy" | "chat",
  "topic": "Extracted topic, product, or theme",
  "tone": "Extracted tone (e.g., energetic, festive, luxury, modern, professional)",
  "platform": "instagram" | "facebook" | "linkedin",
  "conversational_response": "A warm, natural, and highly engaging response written in {language} (Hindi/Hinglish). If generating an asset or intelligence report, introduce what was prepared enthusiastically. If chat, provide insightful advice."
}}
"""
        client = self._get_gemini_client()
        models_to_try = [
            getattr(settings, "GEMINI_FAST_MODEL", None) or getattr(settings, "GEMINI_MODEL", "gemini-3.8-flash"),
            getattr(settings, "GEMINI_MODEL", "gemini-3.8-flash"),
            "gemini-3.8-flash",
            "gemini-flash-latest",
            getattr(settings, "GEMINI_REASONING_MODEL", "gemini-3.8-pro"),
            "gemini-3.8-pro",
            "gemini-pro-latest",
            "gemini-2.5-flash",
            "gemini-2.5-pro",
        ]

        raw_text = ""
        if client:
            for model_name in models_to_try:
                try:
                    logger.info(f"Calling Gemini ({model_name}) for UNI AI intent and response...")
                    res = client.models.generate_content(
                        model=model_name,
                        contents=prompt,
                    )
                    if res and res.text:
                        raw_text = res.text.strip()
                        logger.info(f"Gemini UNI AI generation succeeded with {model_name}")
                        break
                except Exception as e:
                    logger.warning(f"Gemini intent parsing failed with {model_name}: {e}")
                    continue

        if not raw_text:
            try:
                provider = AIProviderFactory.get_provider()
                res = await provider.generate_text(prompt=prompt)
                raw_text = res.get("text", "") if isinstance(res, dict) else str(res)
            except Exception as e:
                logger.error(f"Fallback intent parsing failed: {e}")

        cleaned = raw_text.strip()
        if "```json" in cleaned:
            cleaned = cleaned.split("```json")[-1].split("```")[0].strip()
        elif "```" in cleaned:
            cleaned = cleaned.split("```")[1].strip()

        parsed = {}
        try:
            parsed = json.loads(cleaned)
        except Exception:
            match = re.search(r'\{.*\}', cleaned, re.DOTALL)
            if match:
                try:
                    parsed = json.loads(match.group(0))
                except Exception:
                    pass

        if not parsed or not isinstance(parsed, dict):
            parsed = {
                "action": "chat",
                "topic": command,
                "tone": "conversational",
                "platform": "instagram",
                "conversational_response": raw_text or "Namaste! Main UNI AI Assistant hoon. Main aapki marketing, posts, reels aur festival campaigns mein madad kar sakta hoon. Aapko kya banwana hai? ✨"
            }

        return parsed

    async def parse_and_execute(self, db, user_id: str, command: str) -> Dict[str, Any]:
        """
        1. Fetch business context (with graceful fallback if not set up)
        2. Parse intent and get conversational response via Gemini
        3. Execute the right tool
        4. Return the standard result format with Gemini's response
        """
        # Fetch business context
        business = await BusinessService.get_business_by_owner(user_id)
        if business:
            business_id = str(business.id)
            business_dict = business.model_dump()
            business_dict["_id"] = str(business.id)
            brand = await get_brand_kit(db, business_id) or {}
            language = getattr(business, "preferred_language", "Hinglish") or "Hinglish"
        else:
            business_id = "default"
            brand = {}
            language = "Hinglish"
            business_dict = {
                "name": "My Brand",
                "category": "Retail & E-commerce",
                "description": "General business and marketing",
                "_id": "default"
            }

        # 1. Parse Intent & Get Conversational Response from Gemini
        intent_data = await self._parse_intent_and_respond(command, business_dict, language)
        action = intent_data.get("action", "chat")
        topic = intent_data.get("topic", command)
        tone = intent_data.get("tone", "conversational")
        platform = intent_data.get("platform", "instagram")
        conversational_response = intent_data.get("conversational_response", "")

        instruction = f"User Request: '{command}'. Topic: {topic}. Tone: {tone}. Preferred Language: {language}."

        try:
            if action == "create_post":
                product = {
                    "name": topic or business_dict.get("name", "Exclusive Creative"),
                    "description": command
                }
                post_svc = PostGenerationService()
                result = await post_svc.generate_post(
                    business=business_dict,
                    brand=brand,
                    product=product,
                    platform=platform,
                    objective="engagement",
                    language=language,
                    additional_instruction=instruction
                )
                response_msg = conversational_response or f"Ji zaroor! Maine aapke liye ek nayi post design kar di hai. Check kijiye kaisa laga! ✨"
                return {
                    "success": True,
                    "action": "create_post",
                    "message": response_msg,
                    "data": result
                }

            elif action == "create_reel":
                from app.services.reel_script_service import ReelScriptService
                script_svc = ReelScriptService()
                product = {"name": topic or "Viral Reel", "description": command}
                script = await script_svc.generate_script(
                    product=product,
                    brand=brand,
                    objective="engagement",
                    platform=platform,
                    language=language,
                    duration=30,
                    tone=tone,
                    additional_instruction=instruction
                )
                script_dict = script.model_dump()
                response_msg = conversational_response or f"Ji bilkul! Maine aapke liye ek engaging reel script taiyaar kar di hai. Check kijiye! 🎬"
                return {
                    "success": True,
                    "action": "create_reel",
                    "message": response_msg,
                    "data": {
                        "title": script_dict.get("title", ""),
                        "hook": script_dict.get("hook", ""),
                        "cta": script_dict.get("cta", ""),
                        "caption": script_dict.get("caption", ""),
                        "hashtags": script_dict.get("hashtags", []),
                        "scenes": script_dict.get("scenes", []),
                        "voiceover": " ".join(
                            s.get("voiceover", "") for s in script_dict.get("scenes", [])
                        ),
                        "script": "\n\n".join(
                            f"Scene {s.get('scene_number','')}: {s.get('visual','')} | {s.get('voiceover','')}"
                            for s in script_dict.get("scenes", [])
                        ),
                    }
                }

            elif action == "generate_festival_campaign":
                from app.services.festival_service import get_upcoming_festivals, generate_festival_campaign
                upcoming = get_upcoming_festivals(days_ahead=60)
                target_fest = next((f for f in upcoming if f["name"].lower() in topic.lower() or f["name"].lower() in command.lower()), None)
                if not target_fest and upcoming:
                    target_fest = upcoming[0]

                if target_fest and business_id != "default":
                    campaign = await generate_festival_campaign(db, business_id, target_fest)
                    if campaign:
                        response_msg = conversational_response or f"Maine aapke liye {target_fest.get('name', 'Festival')} campaign taiyaar kar di hai! 🎉"
                        return {
                            "success": True,
                            "action": "generate_festival_campaign",
                            "message": response_msg,
                            "data": campaign
                        }

                response_msg = conversational_response or f"Maine {topic} ke liye marketing suggestions taiyaar kar diye hain! Check kijiye."
                return {
                    "success": True,
                    "action": "chat",
                    "message": response_msg,
                    "data": response_msg
                }

            elif action == "competitor_analysis":
                from app.services.marketing_intelligence_service import MarketingIntelligenceService
                from app.schemas.ai import CompetitorAnalysisRequest
                comp_req = CompetitorAnalysisRequest(
                    industry=business_dict.get("category"),
                    competitors=[topic] if topic and topic.lower() != command.lower() else []
                )
                comp_result = await MarketingIntelligenceService.analyze_competitors(db, user_id, comp_req)
                response_msg = conversational_response or f"Maine aapke business ke liye comprehensive Competitor Analysis report taiyaar kar di hai! 📊"
                return {
                    "success": True,
                    "action": "competitor_analysis",
                    "message": response_msg,
                    "data": comp_result.model_dump()
                }

            elif action == "website_analysis":
                from app.services.marketing_intelligence_service import MarketingIntelligenceService
                from app.schemas.ai import WebsiteAnalysisRequest
                web_req = WebsiteAnalysisRequest(
                    website_url=business_dict.get("location") or "yourbusiness.com"
                )
                web_result = await MarketingIntelligenceService.analyze_website(db, user_id, web_req)
                response_msg = conversational_response or f"Maine aapke website aur landing page ka conversion audit complete kar liya hai! 🌐"
                return {
                    "success": True,
                    "action": "website_analysis",
                    "message": response_msg,
                    "data": web_result.model_dump()
                }

            elif action == "trend_analysis":
                from app.services.marketing_intelligence_service import MarketingIntelligenceService
                from app.schemas.ai import SocialTrendAnalysisRequest
                trend_req = SocialTrendAnalysisRequest(
                    platform=platform,
                    industry=business_dict.get("category")
                )
                trend_result = await MarketingIntelligenceService.analyze_social_trends(db, user_id, trend_req)
                response_msg = conversational_response or f"Maine {platform.title()} ke latest viral trends aur content hooks analyze kar liye hain! 🔥"
                return {
                    "success": True,
                    "action": "trend_analysis",
                    "message": response_msg,
                    "data": trend_result.model_dump()
                }

            elif action == "product_marketing":
                from app.services.marketing_intelligence_service import MarketingIntelligenceService
                from app.schemas.ai import ProductMarketingRequest
                prod_req = ProductMarketingRequest(
                    product_name=topic or "Core Product",
                    product_category=business_dict.get("category")
                )
                prod_result = await MarketingIntelligenceService.generate_product_marketing(db, user_id, prod_req)
                response_msg = conversational_response or f"Maine {topic or 'product'} ke liye USPs aur high-converting copy generate kar di hai! 🛍️"
                return {
                    "success": True,
                    "action": "product_marketing",
                    "message": response_msg,
                    "data": prod_result.model_dump()
                }

            elif action == "brand_strategy":
                from app.services.marketing_intelligence_service import MarketingIntelligenceService
                from app.schemas.ai import BrandStrategyRequest
                brand_req = BrandStrategyRequest(business_id=business_id)
                brand_result = await MarketingIntelligenceService.generate_brand_strategy(db, user_id, brand_req)
                response_msg = conversational_response or f"Maine aapke brand ke liye complete voice guidelines aur content pillars create kar diye hain! 🎯"
                return {
                    "success": True,
                    "action": "brand_strategy",
                    "message": response_msg,
                    "data": brand_result.model_dump()
                }

            else:  # "chat", advice, consultation, greetings, strategy
                response_msg = conversational_response or "Main aapki marketing mein kaise madad kar sakta hoon? Aap mujhse post, reel, ad copy, competitor analysis ya marketing strategy banwa sakte hain! 🚀"
                return {
                    "success": True,
                    "action": "chat",
                    "message": response_msg,
                    "data": response_msg
                }

        except Exception as e:
            logger.error(f"Error executing agent action {action}: {str(e)}")
            return {
                "success": True,
                "action": "chat",
                "message": conversational_response or f"Maine aapka request samajh liya hai, lekin generate karne mein thodi dikkat aayi. Kripya phir se try karein! (Error: {str(e)[:100]})",
                "data": conversational_response or str(e)
            }
