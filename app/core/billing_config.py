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
        "name": "Free",
        "plan_tier": "PLAN 1",
        "price": 0,
        "currency": "INR",
        "billing_cycle": "monthly",
        "credits": 5,
        "credits_badge": "5 Credits",
        "post_limit": 5,
        "reel_limit": 1,
        "team_members": 1,
        "description": "For students, beginners and first timers.",
        "period_label": "/ forever",
        "highlights": [
            "5 AI social media posts/month",
            "1 AI reel/month",
            "5 AI credits/month"
        ],
        "features": ["ai_assistant"],
        "gst_applicable": False,
        "gst_rate": 0.0,
        "gst_amount": 0.0,
        "total_price": 0.0,
        "watermark": True,
        "multiple_businesses": False,
        "api_access": False,
        "white_label": False,
        "billing_cycles": {
            "monthly": {
                "price": 0,
                "formatted_price": "₹0",
                "period_label": "/ forever",
                "duration_days": 30
            },
            "quarterly": {
                "price": 0,
                "formatted_price": "₹0",
                "period_label": "/ forever",
                "duration_days": 90
            },
            "yearly": {
                "price": 0,
                "formatted_price": "₹0",
                "period_label": "/ forever",
                "duration_days": 365
            }
        }
    },
    "STARTER": {
        "name": "Starter",
        "plan_tier": "PLAN 2",
        "price": 799,
        "currency": "INR",
        "billing_cycle": "monthly",
        "credits": 100,
        "credits_badge": "100 Credits",
        "post_limit": 30,
        "reel_limit": 10,
        "team_members": 1,
        "description": "For shopkeepers, freelancers and small businesses.",
        "period_label": "/ month + GST",
        "highlights": [
            "100 monthly credits",
            "30 AI posts/month",
            "10 AI reels/month"
        ],
        "features": ["ai_caption", "ai_post", "ai_photoshoot", "content_calendar"],
        "gst_applicable": False,
        "gst_rate": 0.0,
        "gst_amount": 0.0,
        "total_price": 799.0,
        "watermark": False,
        "multiple_businesses": False,
        "api_access": False,
        "white_label": False,
        "billing_cycles": {
            "monthly": {
                "price": 799,
                "formatted_price": "₹799",
                "period_label": "/ month + GST",
                "duration_days": 30
            },
            "quarterly": {
                "price": 2157,
                "formatted_price": "₹2,157",
                "period_label": "/ quarter + GST",
                "duration_days": 90
            },
            "yearly": {
                "price": 7670,
                "formatted_price": "₹7,670",
                "period_label": "/ year + GST",
                "duration_days": 365
            }
        }
    },
    "GROWTH": {
        "name": "Growth",
        "plan_tier": "PLAN 3",
        "price": 2999,
        "currency": "INR",
        "billing_cycle": "monthly",
        "credits": 400,
        "credits_badge": "400 Credits",
        "post_limit": 100,
        "reel_limit": 30,
        "team_members": 1,
        "description": "For creator, D2C brands and growing businesses.",
        "period_label": "/ month + GST",
        "highlights": [
            "400 monthly credits",
            "100 AI posts/month",
            "30 AI reels/month"
        ],
        "features": [
            "ai_caption", "ai_post", "ai_avatar", "ai_actor", "ai_photoshoot",
            "ads", "website_builder", "instagram_ai", "analytics"
        ],
        "gst_applicable": False,
        "gst_rate": 0.0,
        "gst_amount": 0.0,
        "total_price": 2999.0,
        "watermark": False,
        "multiple_businesses": False,
        "api_access": False,
        "white_label": False,
        "billing_cycles": {
            "monthly": {
                "price": 2999,
                "formatted_price": "₹2,999",
                "period_label": "/ month + GST",
                "duration_days": 30
            },
            "quarterly": {
                "price": 8097,
                "formatted_price": "₹8,097",
                "period_label": "/ quarter + GST",
                "duration_days": 90
            },
            "yearly": {
                "price": 28790,
                "formatted_price": "₹28,790",
                "period_label": "/ year + GST",
                "duration_days": 365
            }
        }
    },
    "BUSINESS": {
        "name": "Business",
        "plan_tier": "PLAN 4",
        "price": 4999,
        "currency": "INR",
        "billing_cycle": "monthly",
        "credits": 1000,
        "credits_badge": "1000 Credits",
        "post_limit": 200,
        "reel_limit": 60,
        "team_members": 5,
        "description": "For established businesses",
        "period_label": "/ month + GST",
        "highlights": [
            "1000 monthly credits",
            "200 AI posts/month",
            "60 AI reels/month"
        ],
        "features": [
            "ai_caption", "ai_post", "ai_avatar", "ai_actor", "ai_photoshoot",
            "ads", "website_builder", "instagram_ai", "analytics",
            "advanced_analytics", "crm", "competitor_analysis"
        ],
        "gst_applicable": False,
        "gst_rate": 0.0,
        "gst_amount": 0.0,
        "total_price": 4999.0,
        "watermark": False,
        "multiple_businesses": True,
        "api_access": True,
        "white_label": True,
        "billing_cycles": {
            "monthly": {
                "price": 4999,
                "formatted_price": "₹4,999",
                "period_label": "/ month + GST",
                "duration_days": 30
            },
            "quarterly": {
                "price": 13497,
                "formatted_price": "₹13,497",
                "period_label": "/ quarter + GST",
                "duration_days": 90
            },
            "yearly": {
                "price": 47990,
                "formatted_price": "₹47,990",
                "period_label": "/ year + GST",
                "duration_days": 365
            }
        }
    },
    "INFLUENCER": {
        "name": "Influencer",
        "plan_tier": "PLAN 5",
        "price": 9999,
        "currency": "INR",
        "billing_cycle": "monthly",
        "credits": 2500,
        "credits_badge": "Influencer...",
        "post_limit": -1,
        "reel_limit": -1,
        "team_members": 10,
        "description": "For brands that want creator partnerships",
        "period_label": "/ month + GST",
        "highlights": [
            "Influencer discovery & shortlisting",
            "Creator audience",
            "Brand collaboration"
        ],
        "features": [
            "influencer_discovery", "creator_audience", "brand_collaboration",
            "ai_caption", "ai_post", "ai_avatar", "ai_actor", "ai_photoshoot",
            "ads", "website_builder", "instagram_ai", "analytics",
            "advanced_analytics", "crm", "competitor_analysis"
        ],
        "gst_applicable": False,
        "gst_rate": 0.0,
        "gst_amount": 0.0,
        "total_price": 9999.0,
        "watermark": False,
        "multiple_businesses": True,
        "api_access": True,
        "white_label": True,
        "billing_cycles": {
            "monthly": {
                "price": 9999,
                "formatted_price": "₹9,999",
                "period_label": "/ month + GST",
                "duration_days": 30
            },
            "quarterly": {
                "price": 26997,
                "formatted_price": "₹26,997",
                "period_label": "/ quarter + GST",
                "duration_days": 90
            },
            "yearly": {
                "price": 95990,
                "formatted_price": "₹95,990",
                "period_label": "/ year + GST",
                "duration_days": 365
            }
        }
    }
}

# Maintain "PRO" as backward-compatible alias for "GROWTH" and "BASIC" for "STARTER"
PLANS["TEST_PLAN"] = {
    "name": "Test Plan (₹1)",
    "plan_tier": "TEST",
    "price": 1,
    "currency": "INR",
    "billing_cycle": "monthly",
    "credits": 20,
    "credits_badge": "20 Credits",
    "post_limit": 10,
    "reel_limit": 5,
    "team_members": 1,
    "description": "Dummy ₹1 test plan for testing payment gateway. Safe to delete.",
    "period_label": "/ test",
    "highlights": [
        "₹1 live gateway test",
        "20 test credits",
        "Instant activation test"
    ],
    "features": ["ai_caption", "ai_post", "ai_reel", "ai_photoshoot"],
    "gst_applicable": False,
    "gst_rate": 0.0,
    "gst_amount": 0.0,
    "total_price": 1.0,
    "watermark": False,
    "multiple_businesses": False,
    "api_access": False,
    "white_label": False,
    "billing_cycles": {
        "monthly": {
            "price": 1,
            "formatted_price": "₹1",
            "period_label": "/ test",
            "duration_days": 30
        },
        "quarterly": {
            "price": 1,
            "formatted_price": "₹1",
            "period_label": "/ test",
            "duration_days": 90
        },
        "yearly": {
            "price": 1,
            "formatted_price": "₹1",
            "period_label": "/ test",
            "duration_days": 365
        }
    }
}

PLANS["PRO"] = PLANS["GROWTH"]
PLANS["BASIC"] = PLANS["STARTER"]
PLANS["TEST"] = PLANS["TEST_PLAN"]

BILLING_CYCLES = ["monthly", "quarterly", "yearly"]

DISPLAY_PLAN_ORDER = ["FREE", "STARTER", "GROWTH", "BUSINESS", "INFLUENCER", "TEST_PLAN"]


def get_formatted_plans(active_plan_id: str | None = None) -> list:
    """Returns a list of structured plan dictionaries ordered for frontend display."""
    result = []
    normalized_active = (active_plan_id or "").upper().strip()
    if normalized_active == "PRO":
        normalized_active = "GROWTH"

    for key in DISPLAY_PLAN_ORDER:
        plan_data = PLANS[key]
        item = {
            "id": key,
            "name": plan_data["name"],
            "plan_tier": plan_data.get("plan_tier", f"PLAN {len(result)+1}"),
            "price": plan_data["price"],
            "base_price": plan_data["price"],
            "currency": plan_data.get("currency", "INR"),
            "gst_applicable": plan_data.get("gst_applicable", False),
            "gst_rate": plan_data.get("gst_rate", 0.0),
            "gst_amount": plan_data.get("gst_amount", 0.0),
            "total_price": plan_data.get("total_price", plan_data["price"]),
            "display_price": plan_data.get("billing_cycles", {}).get("monthly", {}).get("formatted_price", f"₹{plan_data['price']:,}"),
            "period_label": plan_data.get("period_label", "/ month + GST"),
            "credits": plan_data.get("credits", 0),
            "credits_badge": plan_data.get("credits_badge", f"{plan_data.get('credits', 0)} Credits"),
            "description": plan_data.get("description", ""),
            "post_limit": plan_data.get("post_limit", -1),
            "reel_limit": plan_data.get("reel_limit", -1),
            "team_members": plan_data.get("team_members", 1),
            "highlights": plan_data.get("highlights", []),
            "features": plan_data.get("features", []),
            "billing_cycles": plan_data.get("billing_cycles", {}),
            "watermark": plan_data.get("watermark", False),
            "multiple_businesses": plan_data.get("multiple_businesses", False),
            "api_access": plan_data.get("api_access", False),
            "white_label": plan_data.get("white_label", False),
            "is_current": (key == normalized_active)
        }
        result.append(item)
    return result

