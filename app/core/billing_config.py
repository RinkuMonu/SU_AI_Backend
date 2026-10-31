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

from decimal import Decimal, ROUND_HALF_UP

GST_RATE = Decimal("0.18")
GST_PERCENTAGE = 18.0

def calculate_plan_gst(base_price: float | int | Decimal | str) -> dict:
    """
    Dynamically computes 18% GST and total payable amount for any base price
    using decimal-safe currency arithmetic rounded to 2 decimal places.
    Formula:
        gst_amount = base_price * 0.18
        total_amount = base_price + gst_amount
    """
    try:
        price_dec = Decimal(str(base_price or 0))
    except Exception:
        price_dec = Decimal("0")

    if price_dec <= Decimal("0"):
        return {
            "base_price": 0.0,
            "currency": "INR",
            "gst_applicable": False,
            "gst_rate": 0.0,
            "gst_percentage": 0.0,
            "gst_amount": 0.0,
            "total_payable": 0.0,
            "total_price": 0.0,
        }

    gst_dec = (price_dec * GST_RATE).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    total_dec = (price_dec + gst_dec).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    return {
        "base_price": float(price_dec),
        "currency": "INR",
        "gst_applicable": True,
        "gst_rate": float(GST_RATE),
        "gst_percentage": GST_PERCENTAGE,
        "gst_amount": float(gst_dec),
        "total_payable": float(total_dec),
        "total_price": float(total_dec),
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
    """Returns a list of structured plan dictionaries with dynamic 18% GST breakdown ordered for frontend display."""
    result = []
    normalized_active = (active_plan_id or "").upper().strip()
    if normalized_active == "PRO":
        normalized_active = "GROWTH"
    elif normalized_active == "BASIC":
        normalized_active = "STARTER"

    for key in DISPLAY_PLAN_ORDER:
        plan_data = PLANS[key]
        base_price = float(plan_data["price"])
        gst_info = calculate_plan_gst(base_price)

        formatted_cycles = {}
        for cycle_name, cycle_info in plan_data.get("billing_cycles", {}).items():
            cycle_base = float(cycle_info.get("price", 0))
            cycle_gst = calculate_plan_gst(cycle_base)
            formatted_cycles[cycle_name] = {
                "price": cycle_base,
                "base_price": cycle_base,
                "currency": plan_data.get("currency", "INR"),
                "gst_applicable": cycle_gst["gst_applicable"],
                "gst_rate": cycle_gst["gst_rate"],
                "gst_percentage": cycle_gst["gst_percentage"],
                "gst_amount": cycle_gst["gst_amount"],
                "total_payable": cycle_gst["total_payable"],
                "total_price": cycle_gst["total_payable"],
                "formatted_price": cycle_info.get("formatted_price", f"₹{cycle_base:,.0f}"),
                "period_label": cycle_info.get("period_label", "/ month + GST"),
                "duration_days": cycle_info.get("duration_days", 30)
            }

        item = {
            "id": key,
            "name": plan_data["name"],
            "plan_tier": plan_data.get("plan_tier", f"PLAN {len(result)+1}"),
            "price": base_price,
            "base_price": base_price,
            "currency": plan_data.get("currency", "INR"),
            "gst_applicable": gst_info["gst_applicable"],
            "gst_rate": gst_info["gst_rate"],
            "gst_percentage": gst_info["gst_percentage"],
            "gst_amount": gst_info["gst_amount"],
            "total_payable": gst_info["total_payable"],
            "total_price": gst_info["total_payable"],
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
            "billing_cycles": formatted_cycles,
            "watermark": plan_data.get("watermark", False),
            "multiple_businesses": plan_data.get("multiple_businesses", False),
            "api_access": plan_data.get("api_access", False),
            "white_label": plan_data.get("white_label", False),
            "is_current": (key == normalized_active)
        }
        result.append(item)
    return result

# Automatically enrich all entries in PLANS with dynamic decimal-safe GST
for _pk, _pdata in PLANS.items():
    _pbase = float(_pdata.get("price", 0))
    _pgst = calculate_plan_gst(_pbase)
    _pdata["base_price"] = _pbase
    _pdata["gst_applicable"] = _pgst["gst_applicable"]
    _pdata["gst_rate"] = _pgst["gst_rate"]
    _pdata["gst_percentage"] = _pgst["gst_percentage"]
    _pdata["gst_amount"] = _pgst["gst_amount"]
    _pdata["total_payable"] = _pgst["total_payable"]
    _pdata["total_price"] = _pgst["total_payable"]
    if "billing_cycles" in _pdata:
        for _cname, _cinfo in _pdata["billing_cycles"].items():
            _cbase = float(_cinfo.get("price", 0))
            _cgst = calculate_plan_gst(_cbase)
            _cinfo["base_price"] = _cbase
            _cinfo["gst_applicable"] = _cgst["gst_applicable"]
            _cinfo["gst_rate"] = _cgst["gst_rate"]
            _cinfo["gst_percentage"] = _cgst["gst_percentage"]
            _cinfo["gst_amount"] = _cgst["gst_amount"]
            _cinfo["total_payable"] = _cgst["total_payable"]
            _cinfo["total_price"] = _cgst["total_payable"]
