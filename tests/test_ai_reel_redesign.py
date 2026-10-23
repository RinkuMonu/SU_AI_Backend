"""
Comprehensive Test Suite for Redesigned AI Product Reel Generation Backend.
Tests categories, uploads, enhancement, creation modes, audio, video rendering, and API resilience.
"""
import pytest
import os
import io
import asyncio
from bson import ObjectId
from PIL import Image

from app.core.categories import (
    get_all_categories,
    get_subcategories,
    search_categories,
    get_preset_products
)
from app.services.image_enhancement_service import ImageEnhancementService
from app.schemas.reel import GenerateReelRequest, ReelJobStatus
from app.services.reel_service import ReelService
from app.services.reel_script_service import ReelScriptService
from app.ai.video.composer import VideoComposer


# ============================================================================
# 1. CATEGORY & PRODUCT TAXONOMY TESTS
# ============================================================================

def test_category_taxonomy_structure():
    """Verifies complete category taxonomy with all required major industries."""
    categories = get_all_categories()
    assert len(categories) >= 7

    cat_ids = [c["id"] for c in categories]
    assert "fashion_clothing" in cat_ids
    assert "furniture_home" in cat_ids
    assert "electronics" in cat_ids
    assert "beauty_personal_care" in cat_ids
    assert "food_beverages" in cat_ids

    # Verify subcategories presence
    fashion = next(c for c in categories if c["id"] == "fashion_clothing")
    sub_names = [s["name"] for s in fashion["subcategories"]]
    assert "Men's Fashion" in sub_names
    assert "Women's Fashion" in sub_names
    assert "Footwear" in sub_names


def test_subcategory_filtering():
    """Verifies subcategory retrieval by category ID."""
    electronics_subs = get_subcategories("electronics")
    assert len(electronics_subs) >= 3
    sub_ids = [s["subcategory_id"] for s in electronics_subs]
    assert "laptops_computers" in sub_ids
    assert "mobile_phones" in sub_ids

    all_subs = get_subcategories()
    assert len(all_subs) > len(electronics_subs)


def test_category_keyword_search():
    """Tests keyword search across categories and items."""
    matches = search_categories("sofa")
    assert len(matches) > 0
    furniture = matches[0]
    assert furniture["id"] == "furniture_home"

    saree_matches = search_categories("saree")
    assert any(m["id"] == "fashion_clothing" for m in saree_matches)


def test_preset_products_lookup():
    """Tests curated reference products retrieval by category and search."""
    presets = get_preset_products(category_id="electronics")
    assert any("MacBook" in p["name"] for p in presets)

    searched = get_preset_products(query="sofa")
    assert any("Sofa" in p["name"] for p in searched)


# ============================================================================
# 2. IMAGE ENHANCEMENT SERVICE TESTS
# ============================================================================

@pytest.mark.asyncio
async def test_image_enhancement_preserves_product():
    """Verifies image enhancement improves lighting while preserving original file & identity."""
    enhancer = ImageEnhancementService()

    # Create dummy test image
    test_dir = os.path.join("uploads", "test")
    os.makedirs(test_dir, exist_ok=True)
    test_img_path = os.path.join(test_dir, "test_prod.jpg")
    
    img = Image.new("RGB", (600, 600), color=(180, 120, 70))
    img.save(test_img_path, format="JPEG")

    # 1. Test enhancement
    res = await enhancer.enhance_image(
        image_url_or_path=test_img_path,
        prompt="Make lighting cinematic and luxurious",
        product_name="Test Product",
        category="Furniture",
        skip_enhancement=False
    )

    assert res["success"] is True
    assert res["enhanced"] is True
    assert res["enhanced_image_url"] is not None
    assert "enh_" in res["enhanced_image_url"]
    assert res["metadata"]["product_identity_preserved"] is True
    assert os.path.exists(test_img_path), "Original image must be preserved!"

    # 2. Test skip enhancement
    skip_res = await enhancer.enhance_image(
        image_url_or_path=test_img_path,
        skip_enhancement=True
    )
    assert skip_res["success"] is True
    assert skip_res["enhanced"] is False
    assert skip_res["metadata"]["action"] == "skip"

    # Cleanup
    if os.path.exists(test_img_path):
        os.remove(test_img_path)


# ============================================================================
# 3. SCHEMA VALIDATION & HARMONIZATION TESTS
# ============================================================================

def test_generate_reel_request_harmonization():
    """Verifies request model harmonizes creation_mode, duration, aliases, and offers."""
    req_data = {
        "creation_mode": "product_image",
        "product_name": "Ergonomic Office Chair",
        "category": "Furniture & Home",
        "duration_seconds": 30,
        "language": "english",
        "platform": "instagram_reels",
        "voiceover_mode": "ai",
        "voice_tone": "premium",
        "music_style": "cinematic",
        "captions_enabled": True,
        "campaign_objective": "flash_sale",
        "discount_type": "percentage",
        "discount_value": "25%",
        "promo_code": "CHAIR25",
        "additional_instructions": "Highlight lumbar support"
    }

    req = GenerateReelRequest(**req_data)
    assert req.creation_mode == "product_image"
    assert req.duration == 30
    assert req.language == "English"
    assert req.campaign_objective == "flash_sale"
    assert req.objective == "flash_sale"
    assert req.voice_tone == "premium"
    assert req.tone == "premium"
    assert req.promo_code == "CHAIR25"


def test_text_prompt_mode_schema():
    """Verifies text prompt mode without required image."""
    req = GenerateReelRequest(
        creation_mode="text_prompt",
        product_name="Wireless Noise Cancelling Headphones",
        category="Electronics",
        product_description="High-fidelity 40mm drivers with active noise cancellation and 40h battery.",
        duration=15,
        voiceover_mode="none",
        music_style="upbeat"
    )
    assert req.creation_mode == "text_prompt"
    assert req.product_image_url is None
    assert req.voiceover_mode == "none"
    assert req.music_style == "upbeat"


# ============================================================================
# 4. VIDEO COMPOSER & AUDIO MIXING TESTS
# ============================================================================

def test_video_composer_bgm_selection():
    """Verifies dynamic background music styling and fallback resolution."""
    composer = VideoComposer()

    # Style "none" returns None
    assert composer._get_bgm_for_style("none") is None
    assert composer._get_bgm_for_style("off") is None

    # Style resolution handles strings safely
    bgm = composer._get_bgm_for_style("cinematic")
    # Returns candidate or fallback or None if no file exists
    assert bgm is None or isinstance(bgm, str)


# ============================================================================
# 5. REEL SCRIPT SERVICE LOCKING
# ============================================================================

@pytest.mark.asyncio
async def test_script_service_product_locking():
    """Verifies ReelScriptService generates scripts locked to the specific product."""
    service = ReelScriptService()
    product = {
        "name": "Sony WH-1000XM5 Headphones",
        "category": "Electronics & Audio",
        "description": "Industry leading noise cancellation, crystal clear hands-free calling."
    }
    brand = {"name": "AudioStore", "tone": "tech"}

    script = await service.generate_script(
        product=product,
        brand=brand,
        objective="product_showcase",
        platform="instagram_reels",
        duration=15,
        language="English",
        tone="professional",
        additional_instruction="Focus on ANC and travel convenience"
    )

    assert script.primary_product == product["name"]
    assert len(script.scenes) >= 2
    # Verify no category contamination
    for sc in script.scenes:
        text = f"{sc.visual} {sc.voiceover}".lower()
        assert "lehenga" not in text
        assert "saree" not in text
        assert "biryani" not in text
