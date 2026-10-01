# Centralized configuration for SaaS Pricing Plans, Features, and Credit Costs

FEATURE_PRICING = {
    "ai_caption": 1,
    "ai_post": 1,
    "ai_photoshoot": 5,
    "ai_reel": 10,
    "ai_avatar": 15,
    "ai_actor": 20,
    "ai_ad": 5,
    "website_builder": 10,
}

PLANS = {
    "FREE": {
        "name": "FREE",
        "price": 0,
        "currency": "INR",
        "billing_cycle": "monthly",
        "credits": 5,
        "post_limit": 3,
        "reel_limit": 1,
        "team_members": 1,
        "features": ["ai_assistant"],
        "watermark": True,
        "multiple_businesses": False,
        "api_access": False,
        "white_label": False
    },
    "STARTER": {
        "name": "STARTER",
        "price": 499,
        "currency": "INR",
        "billing_cycle": "monthly",
        "credits": 50,
        "post_limit": 15,
        "reel_limit": 5,
        "team_members": 1,
        "features": ["ai_caption", "ai_photoshoot", "content_calendar"],
        "watermark": False,
        "multiple_businesses": False,
        "api_access": False,
        "white_label": False
    },
    "PRO": {
        "name": "PRO",
        "price": 1999,
        "currency": "INR",
        "billing_cycle": "monthly",
        "credits": 400,
        "post_limit": -1,
        "reel_limit": -1,
        "team_members": 1,
        "features": ["ai_avatar", "ai_actor", "ai_photoshoot", "ads", "website_builder", "whatsapp_ai", "instagram_ai", "analytics"],
        "watermark": False,
        "multiple_businesses": False,
        "api_access": False,
        "white_label": False
    },
    "BUSINESS": {
        "name": "BUSINESS",
        "price": 4999,
        "currency": "INR",
        "billing_cycle": "monthly",
        "credits": 1000,
        "post_limit": -1,
        "reel_limit": -1,
        "team_members": 5,
        "features": ["ai_avatar", "ai_actor", "ai_photoshoot", "ads", "website_builder", "whatsapp_ai", "instagram_ai", "advanced_analytics", "crm"],
        "watermark": False,
        "multiple_businesses": True,
        "api_access": True,
        "white_label": True
    }
}
