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
    festival marketing campaign (5 Posts + 3 Reels + 2 Ads + WhatsApp + Offer).
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

    ai_provider = AIProviderFactory.get_provider()
    try:
        res = await ai_provider.generate_text(
            prompt=prompt,
            system_prompt="You are an expert Indian marketing strategist. Output only raw JSON with no markdown. Do not include any thinking or explanation.",
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

        for asset in data.get("assets", []):
            sched = campaign_start + timedelta(days=asset.get("day", 1) - 1)
            asset["scheduled_date"] = sched.isoformat()

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
    from datetime import date, timedelta
    from bson import ObjectId

    business = await db["businesses"].find_one({"_id": ObjectId(business_id)})
    if not business:
        return None

    business_name = business.get("name", "Our Business")
    category = business.get("category", "General")
    target_audience = business.get("target_audience", "All customers")
    tone = business.get("brand_tone", "Friendly and professional")

    fest_name = festival["name"]
    fest_date = festival["date"]

    if content_type == "reel":
        prompt = f"""You are an AI marketing strategist for Indian businesses.
Create a Reel specifically for {fest_name}. Business: {business_name} ({category}). Tone: {tone}.

Output valid JSON only matching this schema:
{{
  "reel": {{
    "title": "", "concept": "", "hook": "", "duration": "30 seconds",
    "caption": "", "hashtags": [], "cta": "", "music": "", "thumbnail_text": "",
    "scenes": [
      {{"scene_number": 1, "duration": "0-5 sec", "visual": "", "on_screen_text": "", "voiceover": "", "image_prompt": ""}}
    ]
  }}
}}"""
    elif content_type == "post":
        prompt = f"""You are an AI marketing strategist for Indian businesses.
Create a Social Media Post specifically for {fest_name}. Business: {business_name} ({category}). Tone: {tone}.

Output valid JSON only matching this schema:
{{
  "post": {{
    "title": "", "headline": "", "caption": "", "body": "", "cta": "",
    "hashtags": [], "visual_concept": "", "image_prompt": ""
  }}
}}"""
    else:
        prompt = f"""You are an AI marketing strategist for Indian businesses.
Create a complete campaign specifically for {fest_name}. Business: {business_name} ({category}). Tone: {tone}.

Output valid JSON only matching this schema:
{{
  "campaign": {{"name": "", "objective": "", "target_audience": "", "offer": "", "duration": ""}},
  "reel": {{ "title": "...", "concept": "...", "caption": "..." }},
  "post": {{ "title": "...", "caption": "...", "image_prompt": "..." }}
}}"""

    ai_provider = AIProviderFactory.get_provider()
    try:
        res = await ai_provider.generate_text(
            prompt=prompt,
            system_prompt="You are an expert Indian marketing strategist. Output only raw JSON with no markdown.",
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
        
        # Prepare document
        campaign_doc = {
            "business_id": business_id,
            "festival_name": fest_name,
            "festival_date": fest_date,
            "content_type": content_type,
            "generated_content": data,
            "status": "generated"
        }
        return campaign_doc
    except Exception as e:
        print("Error generating festival content:", e)
        return None
