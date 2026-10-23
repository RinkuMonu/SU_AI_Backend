import json
import logging
from datetime import date, datetime, timedelta, timezone
from typing import List, Optional
from bson import ObjectId

logger = logging.getLogger(__name__)

# --- Static Indian Festival Calendar ---
# Dates that follow the Gregorian calendar are hardcoded per year.
# Lunar-based festivals (Diwali, Holi, Eid, etc.) are listed for 2025-2027.
INDIAN_FESTIVALS = [
    # 2025
    {"name": "Makar Sankranti",   "date": "2025-01-14", "emoji": "🪁"},
    {"name": "Republic Day",       "date": "2025-01-26", "emoji": "🇮🇳"},
    {"name": "Holi",               "date": "2025-03-14", "emoji": "🎨"},
    {"name": "Ram Navami",         "date": "2025-04-06", "emoji": "🪷"},
    {"name": "Akshaya Tritiya",    "date": "2025-04-30", "emoji": "✨"},
    {"name": "Eid ul-Fitr",        "date": "2025-03-30", "emoji": "🌙"},
    {"name": "Independence Day",   "date": "2025-08-15", "emoji": "🇮🇳"},
    {"name": "Raksha Bandhan",     "date": "2025-08-09", "emoji": "🎁"},
    {"name": "Janmashtami",        "date": "2025-08-16", "emoji": "🪭"},
    {"name": "Onam",               "date": "2025-09-05", "emoji": "🌸"},
    {"name": "Gandhi Jayanti",     "date": "2025-10-02", "emoji": "🕊️"},
    {"name": "Navratri",           "date": "2025-10-02", "emoji": "🎉"},
    {"name": "Dussehra",           "date": "2025-10-12", "emoji": "🪷"},
    {"name": "Dhanteras",          "date": "2025-10-20", "emoji": "💰"},
    {"name": "Diwali",             "date": "2025-10-20", "emoji": "🪔"},
    {"name": "Bhai Dooj",          "date": "2025-10-23", "emoji": "🎊"},
    {"name": "Christmas",          "date": "2025-12-25", "emoji": "🎄"},
    {"name": "New Year",           "date": "2025-12-31", "emoji": "🎊"},
    # 2026
    {"name": "Makar Sankranti",   "date": "2026-01-14", "emoji": "🪁"},
    {"name": "Republic Day",       "date": "2026-01-26", "emoji": "🇮🇳"},
    {"name": "Holi",               "date": "2026-03-03", "emoji": "🎨"},
    {"name": "Eid ul-Fitr",        "date": "2026-03-20", "emoji": "🌙"},
    {"name": "Ram Navami",         "date": "2026-03-26", "emoji": "🪷"},
    {"name": "Akshaya Tritiya",    "date": "2026-04-19", "emoji": "✨"},
    {"name": "Independence Day",   "date": "2026-08-15", "emoji": "🇮🇳"},
    {"name": "Raksha Bandhan",     "date": "2026-08-28", "emoji": "🎁"},
    {"name": "Janmashtami",        "date": "2026-09-05", "emoji": "🪭"},
    {"name": "Gandhi Jayanti",     "date": "2026-10-02", "emoji": "🕊️"},
    {"name": "Navratri",           "date": "2026-09-21", "emoji": "🎉"},
    {"name": "Dussehra",           "date": "2026-10-01", "emoji": "🪷"},
    {"name": "Dhanteras",          "date": "2026-10-08", "emoji": "💰"},
    {"name": "Diwali",             "date": "2026-10-09", "emoji": "🪔"},
    {"name": "Christmas",          "date": "2026-12-25", "emoji": "🎄"},
    {"name": "New Year",           "date": "2026-12-31", "emoji": "🎊"},
    # 2027
    {"name": "Makar Sankranti",   "date": "2027-01-14", "emoji": "🪁"},
    {"name": "Republic Day",       "date": "2027-01-26", "emoji": "🇮🇳"},
    {"name": "Holi",               "date": "2027-03-22", "emoji": "🎨"},
    {"name": "Eid ul-Fitr",        "date": "2027-03-09", "emoji": "🌙"},
    {"name": "Independence Day",   "date": "2027-08-15", "emoji": "🇮🇳"},
    {"name": "Raksha Bandhan",     "date": "2027-08-17", "emoji": "🎁"},
    {"name": "Diwali",             "date": "2027-10-29", "emoji": "🪔"},
    {"name": "Christmas",          "date": "2027-12-25", "emoji": "🎄"},
    {"name": "New Year",           "date": "2027-12-31", "emoji": "🎊"},
]


FESTIVAL_REALISTIC_IMAGES = {
    "makar sankranti": "/images/festivals/makar_sankranti.png",
    "republic day": "/images/festivals/republic_day.png",
    "holi": "/images/festivals/holi.png",
    "eid ul-fitr": "/images/festivals/eid.png",
    "eid": "/images/festivals/eid.png",
    "ram navami": "/images/festivals/navratri.png",
    "akshaya tritiya": "/images/festivals/dhanteras.png",
    "independence day": "/images/festivals/republic_day.png",
    "raksha bandhan": "/images/festivals/rakhi.png",
    "janmashtami": "/images/festivals/navratri.png",
    "onam": "/images/festivals/onam.png",
    "gandhi jayanti": "/images/festivals/gandhi_ji.png",
    "navratri": "/images/festivals/navratri.png",
    "dussehra": "/images/festivals/navratri.png",
    "dhanteras": "/images/festivals/dhanteras.png",
    "diwali": "/images/festivals/diwali.png",
    "bhai dooj": "/images/festivals/rakhi.png",
    "christmas": "/images/festivals/christmas.png",
    "new year": "/images/festivals/new_year.png",
}


def get_festival_image_url(fest_name: str) -> str:
    name_lower = (fest_name or "").lower().strip()
    for k, v in FESTIVAL_REALISTIC_IMAGES.items():
        if k in name_lower:
            return v
    return "/images/festivals/diwali.png"


def get_upcoming_festivals(days_ahead: int = 30) -> List[dict]:
    """Returns festivals coming up within `days_ahead` days from today."""
    today = date.today()
    future = today + timedelta(days=days_ahead)
    upcoming = []
    for f in INDIAN_FESTIVALS:
        fest_date = date.fromisoformat(f["date"])
        if today <= fest_date <= future:
            days_left = (fest_date - today).days
            upcoming.append({**f, "days_left": days_left})
    return sorted(upcoming, key=lambda x: x["days_left"])


async def generate_festival_campaign(db, business_id: str, festival: dict) -> Optional[dict]:
    """
    Fetches business context and prompts the AI to generate a full
    festival marketing campaign (5 Posts + 3 Reels + 2 Ads + Stories + Offer).
    Returns the campaign dict ready to be saved in MongoDB.
    """
    from app.ai.factory import AIProviderFactory

    # 1. Fetch business context
    business = await db["businesses"].find_one({"_id": ObjectId(business_id)})
    if not business:
        return None

    business_name = business.get("name", "Our Business")
    category = business.get("category", "General")
    target_audience = business.get("target_audience", "All customers")
    tone = business.get("brand_tone", "Friendly and professional")
    language = business.get("language", "Hinglish")

    # Fetch top products
    products_cursor = db["products"].find({"business_id": business_id}).limit(5)
    products = await products_cursor.to_list(length=5)
    product_names = [p.get("name", "") for p in products]
    products_str = ", ".join(product_names) if product_names else "general products"

    fest_name = festival["name"]
    fest_emoji = festival.get("emoji", "🎉")
    fest_date = festival["date"]

    prompt = f"""You are a top Indian marketing expert creating a {fest_name} campaign for a business.

Business Details:
- Name: {business_name}
- Category: {category}
- Target Audience: {target_audience}
- Tone: {tone}
- Language: {language}
- Top Products: {products_str}
- Festival: {fest_name} {fest_emoji} on {fest_date}

Generate exactly ONE Instagram Reel and ONE Instagram Post specifically for {fest_name}.

Output ONLY valid JSON, no markdown.

{{
  "assets": [
    {{
      "id": "reel_1",
      "type": "reel",
      "platform": "instagram",
      "content": {{
        "concept": "Reel concept",
        "title": "Reel title",
        "script": "Short video script",
        "scenes": ["Scene 1 description", "Scene 2 description", "Scene 3 description"],
        "visual_suggestions": "Visual suggestions",
        "image_prompt": "A highly detailed, photorealistic image prompt describing the cover image for this reel, visually stunning, festival theme",
        "on_screen_text": "On-screen text",
        "voiceover": "Voiceover/dialogue if required",
        "caption": "Instagram Caption",
        "description": "Description",
        "hashtags": "#Hashtag1 #Hashtag2",
        "cta": "Call-to-action (CTA)"
      }}
    }},
    {{
      "id": "post_1",
      "type": "post",
      "platform": "instagram",
      "content": {{
        "concept": "Post concept",
        "title": "Post title",
        "post_copy": "Post copy",
        "visual_suggestion": "Visual/design suggestion",
        "image_prompt": "A highly detailed, photorealistic image prompt describing the final image for this post, no text in image, beautiful lighting, festival theme",
        "caption": "Instagram Caption",
        "description": "Description",
        "hashtags": "#Hashtag1 #Hashtag2",
        "cta": "Call-to-action (CTA)"
      }}
    }}
  ]
}}"""

    ai_provider = AIProviderFactory.get_provider("gemini")
    try:
        res = await ai_provider.generate_text(
            prompt=prompt,
            system_prompt="You are an elite Indian creative marketing director. Output only raw JSON with no markdown. Do not include any thinking or explanation. Ensure 100% culturally authentic Indian celebrations.",
            max_tokens=4096
        )
        raw = res.get("text", "{}").strip()
        
        # Strip <think>...</think> tags (Qwen3 models)
        import re
        raw = re.sub(r'<think>.*?</think>', '', raw, flags=re.DOTALL).strip()
        
        # Strip markdown code fences
        if "```" in raw:
            parts = raw.split("```")
            for part in parts:
                cleaned = part.strip()
                if cleaned.startswith("json"):
                    cleaned = cleaned[4:].strip()
                if cleaned.startswith("{"):
                    raw = cleaned
                    break
        
        # Find the JSON object in the text
        first_brace = raw.find("{")
        last_brace = raw.rfind("}")
        if first_brace != -1 and last_brace != -1:
            raw = raw[first_brace:last_brace + 1]
        
        logger.info(f"Festival AI raw response length: {len(raw)} chars")
        data = json.loads(raw)

        # Compute actual scheduled dates from days_left
        fest_date_obj = date.fromisoformat(festival["date"])
        campaign_start = fest_date_obj - timedelta(days=10)
        fest_img_url = get_festival_image_url(fest_name)

        for asset in data.get("assets", []):
            sched = campaign_start + timedelta(days=asset.get("day", 1) - 1)
            asset["scheduled_date"] = sched.isoformat()
            if "content" in asset and isinstance(asset["content"], dict):
                asset["content"]["image_url"] = fest_img_url

        campaign_doc = {
            "business_id": business_id,
            "festival_name": fest_name,
            "festival_emoji": fest_emoji,
            "festival_date": festival["date"],
            "days_left": festival["days_left"],
            "status": "draft",
            "offer_strategy": data.get("offer_strategy", f"Special {fest_name} offer!"),
            "assets": data.get("assets", []),
            "created_at": datetime.now(timezone.utc),
        }
        return campaign_doc

    except Exception as e:
        logger.error(f"Failed to generate festival campaign for {fest_name}: {e}")
        return None


async def generate_all_upcoming_campaigns(db) -> int:
    """
    Weekly background job: For all businesses, check upcoming festivals
    and generate draft campaigns if they don't already exist.
    Returns the number of campaigns created.
    """
    count = 0
    upcoming = get_upcoming_festivals(days_ahead=21)
    if not upcoming:
        return 0

    businesses_cursor = db["businesses"].find({})
    businesses = await businesses_cursor.to_list(length=None)

    for business in businesses:
        business_id = str(business["_id"])
        for festival in upcoming:
            # Check if campaign already exists for this festival + business
            existing = await db["festival_campaigns"].find_one({
                "business_id": business_id,
                "festival_name": festival["name"],
                "festival_date": festival["date"],
            })
            if existing:
                continue

            campaign = await generate_festival_campaign(db, business_id, festival)
            if campaign:
                await db["festival_campaigns"].insert_one(campaign)
                count += 1
                logger.info(f"Generated {festival['name']} campaign for business {business_id}")

    return count

async def generate_festival_content(db, business_id: str, festival: dict, content_type: str) -> dict:
    from app.ai.factory import AIProviderFactory
    import json
    import re
    from bson import ObjectId

    business = await db["businesses"].find_one({"_id": ObjectId(business_id)})
    if not business:
        return None

    business_name = business.get("name", "Our Business")
    category = business.get("category", "General")
    target_audience = business.get("target_audience", "All customers")
    tone = business.get("brand_tone", "Friendly, culturally authentic, celebratory, and professional")

    fest_name = festival["name"]
    fest_date = festival["date"]
    fest_emoji = festival.get("emoji", "🎉")

    if content_type == "reel":
        prompt = f"""You are an elite Indian creative marketing director and social media expert.
Generate an authentic, highly engaging, and realistic Instagram Reel concept for the festival "{fest_name}" {fest_emoji}.
Business Name: {business_name} ({category})
Brand Tone: {tone}
Target Audience: {target_audience}

Guidelines:
- Cultural Authenticity: Capture real Indian festival traditions, family warmth, authentic emotions, and festive joy for {fest_name}.
- Realistic & Relatable: Use natural Indian Hinglish or engaging Indian English. Avoid generic robotic cliches.
- Practical Storyboard: Include realistic camera movements, warm lighting, real Indian wardrobe (traditional wear, kurta, saree, festive colors), and relatable Indian setting.
- Visual Description: Detailed realistic scene breakdown.

Output ONLY valid JSON matching this schema exactly (no markdown code fences, no extra text):
{{
  "reel": {{
    "title": "Festive Reel Title",
    "concept": "Creative concept connecting {fest_name} with {business_name}",
    "hook": "First 3-second visual and audio hook that stops scrolling",
    "duration": "30 seconds",
    "music": "Recommended trending Indian festive track or traditional festive fusion",
    "caption": "Full Instagram caption with natural Indian festive enthusiasm and emojis",
    "hashtags": ["#{fest_name.replace(' ', '')}", "#IndianFestivals", "#TrendingReels"],
    "cta": "Clear call to action for the business",
    "thumbnail_text": "Bold text for the reel cover",
    "scenes": [
      {{
        "scene_number": 1,
        "duration": "0-5 sec",
        "visual": "Cinematic shot of real Indian festive morning preparation, warm ambient golden lighting",
        "on_screen_text": "Engaging hook text",
        "voiceover": "Natural friendly voiceover in Hinglish",
        "image_prompt": "Cinematic 8k realistic photo of Indian family celebrating {fest_name}, authentic Indian attire, warm festival lighting, photorealistic"
      }},
      {{
        "scene_number": 2,
        "duration": "5-15 sec",
        "visual": "Dynamic shot showcasing the festival celebration and brand connection",
        "on_screen_text": "Key festive message",
        "voiceover": "Storytelling narrative",
        "image_prompt": "Realistic Indian festive scene for {fest_name}, vibrant traditional decorations, authentic emotions"
      }},
      {{
        "scene_number": 3,
        "duration": "15-25 sec",
        "visual": "Customer joy and festive product/service experience",
        "on_screen_text": "Special {fest_name} offer",
        "voiceover": "Exclusive festival offer details",
        "image_prompt": "High end Indian lifestyle photography celebrating {fest_name}, realistic warm tones"
      }},
      {{
        "scene_number": 4,
        "duration": "25-30 sec",
        "visual": "Heartwarming festive greeting and celebratory finale",
        "on_screen_text": "Brand wishes and CTA",
        "voiceover": "Warm festive greeting and call to action",
        "image_prompt": "Heartwarming realistic Indian festive portrait with {fest_name} celebration, golden hour lighting"
      }}
    ]
  }}
}}"""
    elif content_type == "post":
        prompt = f"""You are an elite Indian creative marketing director and social media copywriter.
Generate an authentic, highly engaging, and realistic Social Media Post for the festival "{fest_name}" {fest_emoji}.
Business Name: {business_name} ({category})
Brand Tone: {tone}
Target Audience: {target_audience}

Guidelines:
- Cultural Depth: Truly reflect how Indians celebrate {fest_name} with reverence, joy, togetherness, and authentic rituals.
- Compelling Copy: Write a heartwarming yet high-converting caption in modern Indian style (friendly Hinglish / warm English).
- Visual Aesthetics: Describe a realistic photo shoot (no cartoons, no anime, genuine Indian models, authentic ethnic attire, festive ambience like diyas, rangoli, kites, or flowers depending on the festival).

Output ONLY valid JSON matching this schema exactly (no markdown code fences, no extra text):
{{
  "post": {{
    "title": "Festive Post Title",
    "headline": "Catchy headline for the post",
    "caption": "Full Instagram & Facebook caption with greetings, story, business festive offer, and emojis",
    "body": "Post main body copy highlighting the festival spirit and brand message",
    "cta": "Direct call to action (e.g., Visit store, Order online, DM us)",
    "hashtags": ["#{fest_name.replace(' ', '')}", "#IndianFestivals", "#{business_name.replace(' ', '')}"],
    "visual_concept": "Detailed creative direction for the graphic or photo",
    "image_prompt": "A photorealistic, 8k award-winning commercial photo of an Indian setting celebrating {fest_name}. Genuine Indian faces, traditional festive garments, natural joyful expressions, warm ambient lighting, beautiful authentic decorations, highly detailed, realistic texture, no cartoon, no anime, no AI distortion"
  }}
}}"""
    else:
        prompt = f"""You are an elite Indian creative marketing director and brand strategist.
Create a complete, realistic, and culturally rich 360-degree marketing campaign for "{fest_name}" {fest_emoji}.
Business Name: {business_name} ({category})
Brand Tone: {tone}
Target Audience: {target_audience}

Output ONLY valid JSON matching this schema exactly (no markdown code fences, no extra text):
{{
  "campaign": {{
    "name": "{fest_name} Celebration Campaign",
    "objective": "Brand awareness and festive sales growth",
    "target_audience": "{target_audience}",
    "offer": "Special {fest_name} festive discount or exclusive bundle",
    "duration": "10-day festive countdown"
  }},
  "reel": {{
    "title": "Festive Reel Title",
    "concept": "Creative Instagram reel concept celebrating {fest_name}",
    "hook": "Strong 3-second hook",
    "duration": "30 seconds",
    "music": "Trending Indian festive track or festive fusion",
    "caption": "Complete engaging reel caption with emojis",
    "hashtags": ["#{fest_name.replace(' ', '')}", "#FestiveVibes"],
    "cta": "Call to action",
    "thumbnail_text": "Cover text",
    "scenes": [
      {{"scene_number": 1, "duration": "0-7 sec", "visual": "Authentic Indian festive morning preparation", "on_screen_text": "Festive greeting hook", "voiceover": "Warm welcoming voiceover"}},
      {{"scene_number": 2, "duration": "7-18 sec", "visual": "Family and friends celebrating {fest_name} together", "on_screen_text": "Story moment", "voiceover": "Connecting emotion with brand"}},
      {{"scene_number": 3, "duration": "18-30 sec", "visual": "Celebratory conclusion and brand festive greeting", "on_screen_text": "Special Offer & CTA", "voiceover": "Festive wishes and CTA"}}
    ]
  }},
  "post": {{
    "title": "Festive Post Title",
    "headline": "Eye-catching Festive Headline",
    "caption": "Complete heartwarming social media caption for {fest_name}",
    "body": "Inspiring brand message connecting with customer festive sentiments",
    "cta": "Festive Offer CTA",
    "hashtags": ["#{fest_name.replace(' ', '')}", "#IndianTraditions"],
    "visual_concept": "Editorial quality Indian festive photo direction",
    "image_prompt": "Photorealistic 8k editorial photo celebrating {fest_name}, beautiful authentic Indian atmosphere, festive attire, warm cinematic lighting"
  }}
}}"""

    ai_provider = AIProviderFactory.get_provider("gemini")
    try:
        res = await ai_provider.generate_text(
            prompt=prompt,
            system_prompt="You are an elite Indian creative marketing director and social media expert. Output only raw JSON with no markdown fences, no thinking, no explanation. Ensure 100% culturally authentic, realistic Indian celebrations.",
            max_tokens=4096
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

        fest_img_url = get_festival_image_url(fest_name)
        assets = []
        if "reel" in data and isinstance(data["reel"], dict):
            data["reel"]["image_url"] = fest_img_url
            assets.append({
                "id": "reel_1",
                "type": "reel",
                "platform": "instagram",
                "content": data["reel"]
            })
        if "post" in data and isinstance(data["post"], dict):
            data["post"]["image_url"] = fest_img_url
            assets.append({
                "id": "post_1",
                "type": "post",
                "platform": "instagram",
                "content": data["post"]
            })

        # Prepare document
        campaign_doc = {
            "business_id": business_id,
            "festival_name": fest_name,
            "festival_emoji": fest_emoji,
            "festival_date": fest_date,
            "content_type": content_type,
            "generated_content": data,
            "assets": assets,
            "offer_strategy": data.get("campaign", {}).get("offer") or f"Special {fest_name} Celebration Offer",
            "status": "generated"
        }
        return campaign_doc
    except Exception as e:
        logger.error(f"Error generating festival content for {fest_name}: {e}")
        return None
