import json
import logging
import re
from datetime import datetime, timezone
from bson import ObjectId

from app.core.config import settings

logger = logging.getLogger(__name__)


class CampaignService:
    def __init__(self, db):
        self.db = db

    def _get_gemini_client(self):
        if not settings.GEMINI_API_KEY:
            return None
        try:
            import google.genai as genai
            return genai.Client(api_key=settings.GEMINI_API_KEY)
        except Exception as e:
            logger.warning(f"Could not initialize google.genai Client: {e}")
            return None

    async def generate_campaign_data(
        self,
        payload: dict,
        business_info: str = "",
        product_info: str = "",
    ) -> dict:
        name = payload.get("name", "Marketing Campaign")
        goal = payload.get("goal", "Brand Awareness & Growth")
        target_audience = payload.get("targetAudience", "Target Audience")
        budget = payload.get("budget", "Flexible Budget")
        duration = payload.get("duration", "1 Month")
        objective = payload.get("objective", "Boost audience reach and conversions")
        platforms = payload.get("platforms", ["Instagram", "Facebook"])
        platforms_str = ", ".join(platforms) if isinstance(platforms, list) else str(platforms)

        prompt = f"""You are an elite Chief Marketing Officer (CMO) and digital growth strategist.
Generate a comprehensive, highly realistic, actionable, and commercially proven marketing campaign plan based on these details:

Campaign Name: {name}
Campaign Goal: {goal}
Target Audience: {target_audience}
Budget: {budget}
Duration: {duration}
Campaign Objective: {objective}
Marketing Platforms: {platforms_str}
{f"Business Context: {business_info}" if business_info else ""}
{f"Product Context: {product_info}" if product_info else ""}

Return ONLY a valid, parseable JSON object without markdown code blocks, with this exact schema:
{{
  "strategy": "A comprehensive strategic blueprint (2-4 detailed paragraphs or structured sections) detailing market positioning, key customer pain points, value proposition, emotional triggers, and full-funnel customer journey.",
  "contentStrategy": "Detailed content strategy framework covering 3-4 content pillars (Educational, Social Proof, Product In Action, Lifestyle), brand voice and tone, visual aesthetic direction, and engagement hooks.",
  "suggestedPosts": [
    "Post 1: [Hook & Angle] Clear visual concept, detailed caption draft with hashtags, and strong CTA",
    "Post 2: [Hook & Angle] Clear visual concept, detailed caption draft with hashtags, and strong CTA",
    "Post 3: [Hook & Angle] Clear visual concept, detailed caption draft with hashtags, and strong CTA",
    "Post 4: [Hook & Angle] Clear visual concept, detailed caption draft with hashtags, and strong CTA"
  ],
  "suggestedReels": [
    "Reel 1: [0-3s Visual Hook] Concept, audio/music recommendation, visual sequence breakdown, and punchy CTA",
    "Reel 2: [0-3s Visual Hook] Concept, audio/music recommendation, visual sequence breakdown, and punchy CTA",
    "Reel 3: [0-3s Visual Hook] Concept, audio/music recommendation, visual sequence breakdown, and punchy CTA"
  ],
  "adCopy": "High-converting, persuasive ad copy with strategic emojis, relatable hook, problem-solution narrative, and urgency tailored to the target audience.",
  "callToAction": "Direct, punchy, high-converting call to action tailored to the goal (e.g., 'Claim Your Exclusive 20% Offer Now')",
  "postingSchedule": "Detailed optimal posting schedule with peak engagement timings (e.g., 'Mon & Thu: 7:30 PM IST (Reels); Wed & Sat: 1:00 PM IST (Carousels); Daily: 8:00 PM IST (Interactive Stories)')"
}}
"""

        raw_text = ""
        client = self._get_gemini_client()

        models_to_try = [
            getattr(settings, "GEMINI_MODEL", "gemini-flash-lite-latest") or "gemini-flash-lite-latest",
            "gemini-flash-lite-latest",
            "gemini-3.8-flash",
            "gemini-flash-latest",
            "gemini-2.5-pro",
        ]

        if client:
            for model_name in models_to_try:
                try:
                    logger.info(f"Generating campaign data using Gemini model: {model_name}")
                    res = client.models.generate_content(
                        model=model_name,
                        contents=prompt,
                    )
                    if res and res.text:
                        raw_text = res.text.strip()
                        logger.info(f"Gemini campaign generation succeeded with {model_name}")
                        break
                except Exception as e:
                    logger.warning(f"Gemini campaign generation failed with {model_name}: {e}")
                    continue

        parsed = {}
        if raw_text:
            cleaned_json = raw_text
            if "```json" in cleaned_json:
                cleaned_json = cleaned_json.split("```json")[-1].split("```")[0].strip()
            elif "```" in cleaned_json:
                cleaned_json = cleaned_json.split("```")[1].strip()

            try:
                parsed = json.loads(cleaned_json)
            except Exception:
                json_match = re.search(r'\{.*\}', cleaned_json, re.DOTALL)
                if json_match:
                    try:
                        parsed = json.loads(json_match.group(0))
                    except Exception:
                        pass

        # Robust fallbacks in case of unexpected Gemini response structure
        if not parsed or not isinstance(parsed, dict):
            parsed = {
                "strategy": f"Comprehensive multi-channel strategy for {name} targeting {target_audience}. Focus on building brand resonance, highlighting unique value propositions, and driving measurable {goal}.",
                "contentStrategy": f"Content pillars: 1. Educational (problem-solution), 2. Product Spotlight & Craftsmanship, 3. User Testimonials & Social Proof. Tone: authoritative yet approachable.",
                "suggestedPosts": [
                    f"Launch Announcement: Introduce {name} with an exclusive first-look carousel highlighting key benefits.",
                    f"Customer Spotlight: Real stories and results from {target_audience} experiencing the difference.",
                    f"Behind The Scenes: The passion, design, and quality behind our latest release.",
                    f"Limited Opportunity: A special incentive designed to drive immediate engagement and action."
                ],
                "suggestedReels": [
                    f"Reel 1: 'Stop making this common mistake' -> Quick 3-second hook followed by our game-changing solution.",
                    f"Reel 2: Day-in-the-life aesthetic reel showcasing practical everyday usage for {target_audience}.",
                    f"Reel 3: Rapid-fire 3 reasons why {name} is trending right now with trending upbeat audio."
                ],
                "adCopy": f"Ready to experience the ultimate upgrade? ✨ Join thousands of {target_audience} who trust {name}. Discover exclusive perks and transform your experience today! 🚀",
                "callToAction": "Explore The Collection Today",
                "postingSchedule": "Mon, Wed & Fri: 7:00 PM IST (Reels); Tue & Sat: 1:30 PM IST (Posts); Daily Stories at 9:00 AM & 8:00 PM IST"
            }

        # Normalize suggestedPosts and suggestedReels to lists of strings
        if not isinstance(parsed.get("suggestedPosts"), list):
            parsed["suggestedPosts"] = [str(parsed.get("suggestedPosts", ""))]
        if not isinstance(parsed.get("suggestedReels"), list):
            parsed["suggestedReels"] = [str(parsed.get("suggestedReels", ""))]

        return parsed

    async def generate_ad_copy(
        self,
        campaign_id: str,
        business_id: str,
        context: dict = None,
    ) -> str:
        campaign = await self.get_campaign_by_id(campaign_id, business_id)
        name = (context or {}).get("name") or (campaign or {}).get("name") or "Marketing Campaign"
        goal = (context or {}).get("goal") or (campaign or {}).get("goal") or "Growth & Sales"
        audience = (context or {}).get("audience") or (campaign or {}).get("targetAudience") or "Target Audience"

        prompt = f"""Write an irresistible, high-converting ad copy for this digital campaign:
Campaign: {name}
Goal: {goal}
Audience: {audience}

Instructions:
- Write 2-3 punchy, persuasive sentences.
- Include strategically placed emojis.
- Highlight benefits, urgency, and a call to action.
- Return ONLY the ad copy text, without any markdown formatting, quotation marks, or surrounding labels."""

        client = self._get_gemini_client()
        ad_copy = None

        if client:
            models = [
                getattr(settings, "GEMINI_MODEL", "gemini-flash-lite-latest") or "gemini-flash-lite-latest",
                "gemini-flash-lite-latest",
                "gemini-3.8-flash",
                "gemini-flash-latest",
            ]
            for m in models:
                try:
                    res = client.models.generate_content(
                        model=m,
                        contents=prompt,
                    )
                    if res and res.text:
                        ad_copy = res.text.strip().strip('"').strip("'")
                        break
                except Exception as e:
                    logger.warning(f"Gemini ad copy failed with model {m}: {e}")
                    continue

        if not ad_copy:
            ad_copy = f"Transform your experience with {name}! ✨ Tailored exclusively for {audience} looking for real results. Don't wait — tap to explore our limited-time launch offer now! 🚀"

        # If campaign exists, persist the new ad copy in database
        if ObjectId.is_valid(campaign_id):
            try:
                await self.update_campaign(campaign_id, business_id, {"adCopy": ad_copy})
            except Exception as e:
                logger.warning(f"Could not persist new ad copy: {e}")

        return ad_copy

    async def create_campaign(
        self,
        user_id: str,
        business_id: str,
        payload: dict,
    ):
        document = payload.copy()
        document["userId"] = user_id
        document["businessId"] = business_id

        # Fetch business & product context if available
        business_info = ""
        try:
            if business_id and ObjectId.is_valid(business_id):
                b_doc = await self.db.businesses.find_one({"_id": ObjectId(business_id)})
                if b_doc:
                    business_info = f"Name: {b_doc.get('name', '')}, Category: {b_doc.get('category', '')}, Description: {b_doc.get('description', '')}"
            if not business_info and user_id:
                b_doc = await self.db.businesses.find_one({"ownerId": user_id})
                if b_doc:
                    business_info = f"Name: {b_doc.get('name', '')}, Category: {b_doc.get('category', '')}, Description: {b_doc.get('description', '')}"
        except Exception as e:
            logger.warning(f"Error fetching business context: {e}")

        product_info = ""
        try:
            p_id = payload.get("productId")
            if p_id and ObjectId.is_valid(p_id):
                p_doc = await self.db.products.find_one({"_id": ObjectId(p_id)})
                if p_doc:
                    product_info = f"Name: {p_doc.get('name', '')}, Price: {p_doc.get('price', '')}, Description: {p_doc.get('description', '')}"
        except Exception as e:
            logger.warning(f"Error fetching product context: {e}")

        # Generate realistic campaign strategy using Gemini API
        ai_data = await self.generate_campaign_data(
            payload=payload,
            business_info=business_info,
            product_info=product_info,
        )

        document["strategy"] = ai_data.get("strategy")
        document["contentStrategy"] = ai_data.get("contentStrategy")
        document["suggestedPosts"] = ai_data.get("suggestedPosts") or []
        document["suggestedReels"] = ai_data.get("suggestedReels") or []
        document["adCopy"] = ai_data.get("adCopy")
        document["callToAction"] = ai_data.get("callToAction")
        document["postingSchedule"] = ai_data.get("postingSchedule")

        document["createdAt"] = datetime.now(timezone.utc)
        document["updatedAt"] = datetime.now(timezone.utc)

        result = await self.db.campaigns.insert_one(document)
        document["id"] = str(result.inserted_id)

        # Ensure we return `id` and remove `_id` so Pydantic model can parse it cleanly
        if "_id" in document:
            del document["_id"]

        return document

    async def get_campaigns(self, business_id: str):
        cursor = self.db.campaigns.find({"businessId": business_id}).sort("createdAt", -1)
        campaigns = []
        async for item in cursor:
            item["id"] = str(item.pop("_id"))
            campaigns.append(item)
        return campaigns

    async def get_campaign_by_id(self, campaign_id: str, business_id: str):
        if not ObjectId.is_valid(campaign_id):
            return None
            
        doc = await self.db.campaigns.find_one({
            "_id": ObjectId(campaign_id),
            "businessId": business_id
        })
        if not doc:
            doc = await self.db.campaigns.find_one({"_id": ObjectId(campaign_id)})

        if doc:
            doc["id"] = str(doc.pop("_id"))
        return doc

    async def update_campaign(self, campaign_id: str, business_id: str, updates: dict):
        if not ObjectId.is_valid(campaign_id):
            return None

        updates["updatedAt"] = datetime.now(timezone.utc)
        
        result = await self.db.campaigns.update_one(
            {"_id": ObjectId(campaign_id), "businessId": business_id},
            {"$set": updates}
        )
        
        if result.matched_count == 0:
            return None
            
        return await self.get_campaign_by_id(campaign_id, business_id)

    async def delete_campaign(self, campaign_id: str, business_id: str) -> bool:
        if not ObjectId.is_valid(campaign_id):
            return False
            
        result = await self.db.campaigns.delete_one({
            "_id": ObjectId(campaign_id),
            "businessId": business_id
        })
        return result.deleted_count > 0
