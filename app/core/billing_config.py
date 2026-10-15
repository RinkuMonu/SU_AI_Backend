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


# 18% GST Rate applied to paid subscriptions
GST_RATE = 0.18

def calculate_plan_pricing(base_price: int):
    if base_price <= 0:
        return {
            "price": 0,
            "base_price": 0,
            "gst_rate": 0.0,
            "gst_percent": 18,
            "gst_amount": 0.0,
            "total_price": 0.0,
            "gst_applicable": False,
        }
    gst_amount = round(base_price * GST_RATE, 2)
    total_price = round(base_price + gst_amount, 2)
    return {
        "price": base_price,
        "base_price": base_price,
        "gst_rate": GST_RATE,
        "gst_percent": 18,
        "gst_amount": gst_amount,
        "total_price": total_price,
        "gst_applicable": True,
    }

PLANS = {
    "FREE": {
        "name": "FREE",
        "tagline": "Explore AI",
        "description": "For students, beginners and first-time users.",
        **calculate_plan_pricing(0),
        "currency": "INR",
        "billing_cycle": "monthly",
        "credits": 500,
        "post_limit": -1,
        "reel_limit": -1,
        "team_members": 1,
        "brand_profiles": 1,
        "bullet_points": [
            "500 AI credits/month",
            "Unlimited AI social media posts",
            "Unlimited AI reels",
            "Basic caption generation",
            "1 brand profile",
            "Explore AI tools before upgrading"
        ],
        "features": [
            "ai_assistant", "ai_reel", "ai_caption", "website_builder", 
            "ai_post", "ai_photoshoot", "ai_avatar", "ai_actor", 
            "ads", "whatsapp_ai", "instagram_ai", "analytics", 
            "brand_profile", "explore_tools"
        ],
        "watermark": True,
        "multiple_businesses": False,
        "api_access": False,
        "white_label": False
    },
    "BASIC": {
        "name": "BASIC",
        "tagline": "Create",
        "description": "For shopkeepers, freelancers and small businesses starting online marketing.",
        **calculate_plan_pricing(799),
        "currency": "INR",
        "billing_cycle": "monthly",
        "credits": 100,
        "post_limit": 30,
        "reel_limit": 10,
        "team_members": 1,
        "brand_profiles": 1,
        "bullet_points": [
            "100 monthly credits",
            "30 AI posts/month",
            "10 AI reels/month",
            "30 AI captions/month",
            "Basic hashtag suggestions",
            "1 brand and 1 user",
            "Brand-ready social media creatives"
        ],
        "features": ["ai_caption", "ai_photoshoot", "content_calendar", "ai_reel", "ai_post", "website_builder", "hashtags", "brand_profile", "brand_ready_creatives"],
        "watermark": False,
        "multiple_businesses": False,
        "api_access": False,
        "white_label": False
    },
    "STARTER": {
        "name": "STARTER",
        "tagline": "Create",
        "description": "For shopkeepers, freelancers and small businesses starting online marketing.",
        **calculate_plan_pricing(799),
        "currency": "INR",
        "billing_cycle": "monthly",
        "credits": 100,
        "post_limit": 30,
        "reel_limit": 10,
        "team_members": 1,
        "brand_profiles": 1,
        "bullet_points": [
            "100 monthly credits",
            "30 AI posts/month",
            "10 AI reels/month",
            "30 AI captions/month",
            "Basic hashtag suggestions",
            "1 brand and 1 user",
            "Brand-ready social media creatives"
        ],
        "features": ["ai_caption", "ai_photoshoot", "content_calendar", "ai_reel", "ai_post", "website_builder", "hashtags", "brand_profile", "brand_ready_creatives"],
        "watermark": False,
        "multiple_businesses": False,
        "api_access": False,
        "white_label": False
    },
    "GROWTH": {
        "name": "GROWTH",
        "tagline": "Market",
        "description": "For creators, D2C brands and growing businesses that want consistent marketing.",
        **calculate_plan_pricing(2999),
        "currency": "INR",
        "billing_cycle": "monthly",
        "credits": 400,
        "post_limit": 100,
        "reel_limit": 30,
        "team_members": 2,
        "brand_profiles": 1,
        "bullet_points": [
            "400 monthly credits",
            "100 AI posts/month",
            "30 AI reels/month",
            "100 AI captions/month",
            "AI Photoshoot, Fashion AI and Avatar tools",
            "Advanced brand customization",
            "Social media content calendar",
            "Post scheduling tools",
            "2 users"
        ],
        "features": [
            "ai_avatar", "ai_actor", "ai_photoshoot", "ads", "website_builder", 
            "whatsapp_ai", "instagram_ai", "analytics", "ai_reel", "ai_caption", 
            "ai_post", "fashion_ai", "brand_customization", "content_calendar", "post_scheduling"
        ],
        "watermark": False,
        "multiple_businesses": False,
        "api_access": False,
        "white_label": False
    },
    "BUSINESS": {
        "name": "BUSINESS",
        "tagline": "Automate",
        "description": "For established businesses, marketing teams and agencies.",
        **calculate_plan_pricing(4999),
        "currency": "INR",
        "billing_cycle": "monthly",
        "credits": 1000,
        "post_limit": 200,
        "reel_limit": 60,
        "team_members": 5,
        "brand_profiles": 5,
        "bullet_points": [
            "1,000 monthly credits",
            "200 AI posts/month",
            "60 AI reels/month",
            "200 AI captions/month",
            "5 team members",
            "Multiple brand profiles",
            "Advanced scheduling and campaign management",
            "Business analytics",
            "AI Marketing Agent",
            "WhatsApp AI and Instagram DM AI, where integrations are supported",
            "Leads CRM and product catalogue tools"
        ],
        "features": [
            "ai_avatar", "ai_actor", "ai_photoshoot", "ads", "website_builder", 
            "whatsapp_ai", "instagram_ai", "advanced_analytics", "crm", "ai_reel", 
            "ai_caption", "ai_post", "fashion_ai", "brand_customization", 
            "content_calendar", "post_scheduling", "campaign_management", 
            "business_analytics", "marketing_agent", "leads_crm", "product_catalogue"
        ],
        "watermark": False,
        "multiple_businesses": True,
        "api_access": True,
        "white_label": True
    },
    "INFLUENCER": {
        "name": "INFLUENCER",
        "tagline": "Collaborate",
        "description": "For brands that want creator partnerships and influencer-led campaigns.",
        **calculate_plan_pricing(9999),
        "currency": "INR",
        "billing_cycle": "monthly",
        "credits": 2000,
        "post_limit": -1,
        "reel_limit": -1,
        "team_members": 10,
        "brand_profiles": 10,
        "bullet_points": [
            "Influencer discovery and shortlisting",
            "Creator audience and engagement review",
            "Brand-influencer collaboration coordination",
            "Campaign briefs and content planning",
            "Influencer outreach assistance",
            "Campaign tracking and reporting",
            "AI-generated promotional creatives and captions",
            "Performance analytics, where data is available",
            "Custom campaign packages for larger brands"
        ],
        "features": [
            "influencer_discovery", "creator_review", "collaboration_coordination",
            "campaign_briefs", "outreach_assistance", "campaign_tracking",
            "ai_promotional_creatives", "performance_analytics", "custom_packages",
            "ai_avatar", "ai_actor", "ai_photoshoot", "ads", "website_builder", 
            "whatsapp_ai", "instagram_ai", "advanced_analytics", "crm", "ai_reel", 
            "ai_caption", "ai_post", "fashion_ai", "brand_customization", 
            "content_calendar", "post_scheduling", "campaign_management", 
            "business_analytics", "marketing_agent", "leads_crm", "product_catalogue"
        ],
        "watermark": False,
        "multiple_businesses": True,
        "api_access": True,
        "white_label": True
    },

    # Backwards-compatibility alias for legacy PRO users
    "PRO": {
        "name": "PRO",
        "tagline": "Market",
        "description": "For creators, D2C brands and growing businesses that want consistent marketing.",
        **calculate_plan_pricing(2999),
        "currency": "INR",
        "billing_cycle": "monthly",
        "credits": 400,
        "post_limit": 100,
        "reel_limit": 30,
        "team_members": 2,
        "brand_profiles": 1,
        "bullet_points": [
            "400 monthly credits",
            "100 AI posts/month",
            "30 AI reels/month",
            "100 AI captions/month",
            "AI Photoshoot, Fashion AI and Avatar tools",
            "Advanced brand customization",
            "Social media content calendar",
            "Post scheduling tools",
            "2 users"
        ],
        "features": [
            "ai_avatar", "ai_actor", "ai_photoshoot", "ads", "website_builder", 
            "whatsapp_ai", "instagram_ai", "analytics", "ai_reel", "ai_caption", 
            "ai_post", "fashion_ai", "brand_customization", "content_calendar", "post_scheduling"
        ],
        "watermark": False,
        "multiple_businesses": False,
        "api_access": False,
        "white_label": False,
        "is_legacy": True
    },
    "HIRE_INFLUENCER": {
        "name": "Hire Influencer",
        "price": 100,
        "base_price": 100,
        "gst_rate": 0.0,
        "gst_percent": 0,
        "gst_amount": 0.0,
        "total_price": 100.0,
        "currency": "INR",
        "billing_cycle": "one-time",
        "credits": 0,
        "post_limit": 0,
        "reel_limit": 0,
        "team_members": 0,
        "features": [],
        "bullet_points": [],
        "watermark": False,
        "multiple_businesses": False,
        "api_access": False,
        "white_label": False,
        "gst_applicable": False,
        "is_legacy": True
    }
}
