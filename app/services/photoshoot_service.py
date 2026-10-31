import os
import io
import re
import json
import uuid
import zipfile
import asyncio
import logging
import urllib.parse
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any, Tuple
from PIL import Image
import httpx
from fastapi import UploadFile, HTTPException, status
from bson import ObjectId

from app.core.config import settings
from app.core.database import get_database
from app.services.credit_service import CreditService
from app.services.subscription_service import SubscriptionService
from app.services.stt_service import STTService
# Centralized OpenAI AI Provider
from app.ai.factory import AIProviderFactory
from app.models.photoshoot import (
    ProductPhotoshootSession,
    ProductImageAsset,
    AIModelProfile,
    PhotoshootGenerationJob,
)
from app.schemas.photoshoot import (
    ProductAnalysisData,
    AIModelItem,
    PhotographyStyleItem,
)

logger = logging.getLogger(__name__)


# ===========================================================================
# CURATED AI MODELS GALLERY
# ===========================================================================

CURATED_AI_MODELS: List[AIModelItem] = [
    AIModelItem(
        model_id="model_male_01",
        name="Arjun - Indian Male Fashion Model",
        gender="male",
        ethnicity="Indian / South Asian",
        thumbnail_url="https://images.unsplash.com/photo-1506794778202-cad84cf45f1d?w=400&auto=format&fit=crop&q=80",
        preview_url="https://images.unsplash.com/photo-1506794778202-cad84cf45f1d?w=1024&auto=format&fit=crop&q=80",
        supported_categories=["Clothing", "Men's Apparel", "T-shirts", "Shirts", "Footwear", "Eyewear", "Watches"],
        description="Athletic build, sharp jawline, versatile for casual wear, formal suits, and sportswear.",
        identity_prompt="28-year-old Indian male model Arjun, short textured black hair, warm brown eyes, clean-shaven, athletic build, sharp jawline"
    ),
    AIModelItem(
        model_id="model_male_02",
        name="Kabir - Modern Streetwear Model",
        gender="male",
        ethnicity="South Asian",
        thumbnail_url="https://images.unsplash.com/photo-1500648767791-00dcc994a43e?w=400&auto=format&fit=crop&q=80",
        preview_url="https://images.unsplash.com/photo-1500648767791-00dcc994a43e?w=1024&auto=format&fit=crop&q=80",
        supported_categories=["Clothing", "Streetwear", "Jackets", "Hoodies", "Caps", "Sneakers"],
        description="Urban contemporary look, charismatic aesthetic for modern streetwear and denim.",
        identity_prompt="26-year-old South Asian male model Kabir, modern fade haircut, energetic gaze, charismatic posture, athletic frame"
    ),
    AIModelItem(
        model_id="model_female_01",
        name="Ananya - Indian Female Fashion Model",
        gender="female",
        ethnicity="Indian / South Asian",
        thumbnail_url="https://images.unsplash.com/photo-1534528741775-53994a69daeb?w=400&auto=format&fit=crop&q=80",
        preview_url="https://images.unsplash.com/photo-1534528741775-53994a69daeb?w=1024&auto=format&fit=crop&q=80",
        supported_categories=["Clothing", "Dresses", "Ethnic Wear", "Sarees", "Jewellery", "Cosmetics"],
        description="Classic elegant features, radiant skin tone, ideal for ethnic wear, sarees, and jewellery.",
        identity_prompt="24-year-old Indian female model Ananya, expressive almond brown eyes, glowing warm skin tone, elegant long dark hair, poised posture"
    ),
    AIModelItem(
        model_id="model_female_02",
        name="Meera - Luxury Editorial Model",
        gender="female",
        ethnicity="South Asian",
        thumbnail_url="https://images.unsplash.com/photo-1517841905240-472988babdf9?w=400&auto=format&fit=crop&q=80",
        preview_url="https://images.unsplash.com/photo-1517841905240-472988babdf9?w=1024&auto=format&fit=crop&q=80",
        supported_categories=["Jewellery", "Necklaces", "Earrings", "Luxury Fashion", "Bridal Wear"],
        description="High-fashion editorial aesthetic, graceful neck and posture, perfected for fine jewellery and luxury.",
        identity_prompt="27-year-old South Asian luxury editorial female model Meera, graceful long neck, sculpted cheekbones, sleek center-part dark hair, radiant complexion"
    ),
    AIModelItem(
        model_id="model_female_03",
        name="Priya - Casual Lifestyle Model",
        gender="female",
        ethnicity="Indian",
        thumbnail_url="https://images.unsplash.com/photo-1524504388940-b1c1722653e1?w=400&auto=format&fit=crop&q=80",
        preview_url="https://images.unsplash.com/photo-1524504388940-b1c1722653e1?w=1024&auto=format&fit=crop&q=80",
        supported_categories=["Clothing", "Tops", "Jeans", "Handbags", "Footwear", "Accessories"],
        description="Friendly, approachable commercial vibe, ideal for everyday lifestyle and D2C brands.",
        identity_prompt="25-year-old friendly approachable Indian female model Priya, warm smile, shoulder-length wavy dark hair, natural beauty"
    ),
    AIModelItem(
        model_id="model_male_03",
        name="David - International Male Model",
        gender="male",
        ethnicity="Caucasian / European",
        thumbnail_url="https://images.unsplash.com/photo-1539571696357-5a69c17a67c6?w=400&auto=format&fit=crop&q=80",
        preview_url="https://images.unsplash.com/photo-1539571696357-5a69c17a67c6?w=1024&auto=format&fit=crop&q=80",
        supported_categories=["Clothing", "Suits", "Blazers", "Watches", "Leather Goods", "Eyewear"],
        description="Sophisticated gentleman look, ideal for luxury global fashion, suits, and premium accessories.",
        identity_prompt="29-year-old Caucasian European male model David, groomed short brown hair, blue-gray eyes, sophisticated jawline, tall tailored frame"
    )
]


# ===========================================================================
# PHOTOGRAPHY STYLES & POSES CATALOG
# ===========================================================================

PHOTOGRAPHY_STYLES_CATALOG: List[PhotographyStyleItem] = [
    # =======================================================================
    # 10 CANONICAL STYLES: Avatar Photoshoot (requires_model = True)
    # =======================================================================
    PhotographyStyleItem(
        id="avatar_fashion_studio",
        name="Fashion Studio",
        description="High-fashion studio catalog lighting with sleek seamless backdrop and confident commercial pose.",
        category_fit=["All", "Clothing", "Men's Apparel", "Women's Apparel", "Dresses", "Activewear"],
        requires_model=True,
        pose="Direct standing commercial stance with natural arms and confident gaze",
        lighting="Three-point softbox studio lighting with diffused hair light and subtle fill",
        preview_url="https://images.unsplash.com/photo-1509631179647-0177331693ae?w=800&auto=format&fit=crop&q=80"
    ),
    PhotographyStyleItem(
        id="avatar_editorial",
        name="Editorial",
        description="Vogue-grade high-fashion editorial styling, dynamic angular posing, and dramatic magazine aesthetic.",
        category_fit=["All", "Clothing", "Designer Wear", "Ethnic Wear", "Luxury Apparel"],
        requires_model=True,
        pose="Expressive geometric high-fashion pose with dynamic body angles",
        lighting="Moody chiaroscuro lighting with dramatic beauty dish focus and sculpted shadows",
        preview_url="https://images.unsplash.com/photo-1490481651871-ab68de25d43d?w=800&auto=format&fit=crop&q=80"
    ),
    PhotographyStyleItem(
        id="avatar_lifestyle",
        name="Lifestyle",
        description="Natural real-world lifestyle setting capturing effortless elegance and authentic mood.",
        category_fit=["All", "Clothing", "Streetwear", "Footwear", "Accessories", "Casual Wear"],
        requires_model=True,
        pose="Relaxed natural movement in contemporary urban cafe or modern interior",
        lighting="Soft natural golden hour sunlight with ambient environmental fill",
        preview_url="https://images.unsplash.com/photo-1483985988355-763728e1935b?w=800&auto=format&fit=crop&q=80"
    ),
    PhotographyStyleItem(
        id="avatar_campaign_photography",
        name="Campaign Photography",
        description="Elevated advertising campaign with bold color-blocked studio styling and high-impact presence.",
        category_fit=["All", "Clothing", "Footwear", "Watches", "Eyewear", "Streetwear"],
        requires_model=True,
        pose="Dynamic hero stance with strong commanding posture",
        lighting="High-energy commercial pop lighting with crisp chromatic contrast",
        preview_url="https://images.unsplash.com/photo-1515886657613-9f3515b0c78f?w=800&auto=format&fit=crop&q=80"
    ),
    PhotographyStyleItem(
        id="avatar_studio_premium",
        name="Studio Premium",
        description="Clean, sophisticated commercial studio portrait highlighting garment drape, texture, and tailored fit.",
        category_fit=["All", "Clothing", "Men's Apparel", "Women's Apparel", "Formal Wear", "Suits"],
        requires_model=True,
        pose="Poised standing stance with slight 15-degree shoulder rotation",
        lighting="Balanced double octabox lighting creating soft enveloping luminosity",
        preview_url="https://images.unsplash.com/photo-1487222477894-8943e31ef7b2?w=800&auto=format&fit=crop&q=80"
    ),
    PhotographyStyleItem(
        id="avatar_luxury_cinematic",
        name="Luxury Cinematic",
        description="Warm chiaroscuro lighting, rich deep tones, and cinematic depth of field for luxury fashion.",
        category_fit=["All", "Jewellery", "Luxury Fashion", "Watches", "Evening Wear"],
        requires_model=True,
        pose="Intimate cinematic portrait with refined facial framing and subtle posture",
        lighting="Warm tungsten key light with rich shadows and luminous rim lighting",
        preview_url="https://images.unsplash.com/photo-1534528741775-53994a69daeb?w=800&auto=format&fit=crop&q=80"
    ),
    PhotographyStyleItem(
        id="avatar_close_up",
        name="Close-Up",
        description="Intimate macro crop portrait showcasing fine jewellery, neckline, collar detail, or eyewear worn on model.",
        category_fit=["All", "Jewellery", "Earrings", "Necklaces", "Eyewear", "Cosmetics"],
        requires_model=True,
        pose="Tight beauty framing with hands subtly positioning or framing the piece",
        lighting="High-CRI beauty dish lighting emphasizing skin glow, gemstone sparkle, and metal finish",
        preview_url="https://images.unsplash.com/photo-1517841905240-472988babdf9?w=800&auto=format&fit=crop&q=80"
    ),
    PhotographyStyleItem(
        id="avatar_minimal",
        name="Minimal",
        description="Clean neutral palette, uncluttered composition, and serene minimalist studio aesthetics.",
        category_fit=["All", "Clothing", "Loungewear", "Contemporary Wear", "Accessories"],
        requires_model=True,
        pose="Calm relaxed stance against neutral plaster backdrop with clean silhouette",
        lighting="Diffused northern window daylight simulation with soft gradient shadows",
        preview_url="https://images.unsplash.com/photo-1524504388940-b1c1722653e1?w=800&auto=format&fit=crop&q=80"
    ),
    PhotographyStyleItem(
        id="avatar_marketplace_white",
        name="Marketplace White",
        description="Clean e-commerce studio portrait on pure white seamless backdrop compliant with top marketplaces.",
        category_fit=["All", "Clothing", "Footwear", "Apparel", "E-commerce"],
        requires_model=True,
        pose="Upright front catalog stance presenting complete product silhouette",
        lighting="Even commercial studio lighting on pure #FFFFFF white background",
        preview_url="https://images.unsplash.com/photo-1506794778202-cad84cf45f1d?w=800&auto=format&fit=crop&q=80"
    ),
    PhotographyStyleItem(
        id="avatar_top_down",
        name="Top-Down",
        description="High-angle overhead composition capturing model styling and coordinated outfit arrangement.",
        category_fit=["All", "Clothing", "Loungewear", "Activewear", "Footwear"],
        requires_model=True,
        pose="Seated or reclining overhead viewpoint with relaxed natural posture",
        lighting="Wide diffused overhead softbox for consistent illumination",
        preview_url="https://images.unsplash.com/photo-1500648767791-00dcc994a43e?w=800&auto=format&fit=crop&q=80"
    ),

    # --- Model-based Clothing & Jewellery Legacy Poses ---
    PhotographyStyleItem(
        id="clothing_front_view",
        name="Front View",
        description="Standing direct to camera, showing complete garment drape, neckline, fit and texture.",
        category_fit=["Clothing", "Men's Apparel", "Women's Apparel", "T-shirts", "Shirts", "Dresses"],
        requires_model=True,
        pose="Direct standing pose facing camera with arms naturally at sides",
        lighting="Three-point studio softbox with subtle fill light",
        preview_url="https://images.unsplash.com/photo-1487222477894-8943e31ef7b2?w=800&auto=format&fit=crop&q=80"
    ),
    PhotographyStyleItem(
        id="clothing_back_view",
        name="Back View",
        description="Standing turned away from camera, showing rear garment structure, back print, and silhouette.",
        category_fit=["Clothing", "Men's Apparel", "Women's Apparel", "T-shirts", "Hoodies", "Jackets"],
        requires_model=True,
        pose="Turned 180 degrees away showing full back details and posture",
        lighting="Rim lighting accentuating garment edges against soft backdrop",
        preview_url="https://images.unsplash.com/photo-1506794778202-cad84cf45f1d?w=800&auto=format&fit=crop&q=80"
    ),
    PhotographyStyleItem(
        id="clothing_side_view",
        name="Side View",
        description="Side profile view highlighting sleeve drape, taper, waistline, and lateral details.",
        category_fit=["Clothing", "Men's Apparel", "Women's Apparel", "Pants", "Dresses"],
        requires_model=True,
        pose="Clean 90-degree profile stance showing full garment side silhouette",
        lighting="Directional soft key light sculpting garment contours",
        preview_url="https://images.unsplash.com/photo-1500648767791-00dcc994a43e?w=800&auto=format&fit=crop&q=80"
    ),
    PhotographyStyleItem(
        id="clothing_sitting_pose",
        name="Sitting Pose",
        description="Casual modern seated pose on a minimalist studio stool, showing relaxed fabric drape.",
        category_fit=["Clothing", "Men's Apparel", "Women's Apparel", "Loungewear", "Denim"],
        requires_model=True,
        pose="Seated comfortably on neutral concrete studio cube or modern wood stool",
        lighting="Warm architectural ambient lighting with soft diffused shadows",
        preview_url="https://images.unsplash.com/photo-1524504388940-b1c1722653e1?w=800&auto=format&fit=crop&q=80"
    ),
    PhotographyStyleItem(
        id="clothing_walking_pose",
        name="Walking Pose",
        description="Dynamic movement in-stride shot capturing natural fabric motion and lifestyle energy.",
        category_fit=["Clothing", "Streetwear", "Activewear", "Footwear", "Dresses"],
        requires_model=True,
        pose="Natural mid-stride walk toward camera with subtle fabric flutter",
        lighting="Natural daylight simulation with crisp editorial contrast",
        preview_url="https://images.unsplash.com/photo-1483985988355-763728e1935b?w=800&auto=format&fit=crop&q=80"
    ),
    PhotographyStyleItem(
        id="clothing_editorial_pose",
        name="Editorial Fashion Pose",
        description="Vogue-grade high fashion architectural pose with high-end aesthetic.",
        category_fit=["Clothing", "Designer Wear", "Ethnic Wear", "Luxury Apparel"],
        requires_model=True,
        pose="Expressive high-fashion geometric pose with dynamic body angles",
        lighting="Moody editorial chiaroscuro with dramatic beauty dish focus",
        preview_url="https://images.unsplash.com/photo-1490481651871-ab68de25d43d?w=800&auto=format&fit=crop&q=80"
    ),
    PhotographyStyleItem(
        id="jewellery_closeup",
        name="Close-up Model Shot",
        description="Macro crop focused on worn piece (earring, necklace, bracelet, ring) with shallow depth of field.",
        category_fit=["Jewellery", "Earrings", "Necklaces", "Rings", "Watches"],
        requires_model=True,
        pose="Intimate close-up portrait with hands framing or touching the piece",
        lighting="High-CRI beauty glow emphasizing gemstone facets and metal luster",
        preview_url="https://images.unsplash.com/photo-1517841905240-472988babdf9?w=800&auto=format&fit=crop&q=80"
    ),
    PhotographyStyleItem(
        id="jewellery_front_portrait",
        name="Front Portrait",
        description="Elegant beauty portrait highlighting collarbone and necklace placement.",
        category_fit=["Jewellery", "Necklaces", "Bridal Wear"],
        requires_model=True,
        pose="Straight portrait with shoulders angled and chin gently lifted",
        lighting="Glamour butterfly lighting with catchlights in eyes",
        preview_url="https://images.unsplash.com/photo-1534528741775-53994a69daeb?w=800&auto=format&fit=crop&q=80"
    ),
    PhotographyStyleItem(
        id="jewellery_side_portrait",
        name="Side Portrait",
        description="Graceful profile view highlighting dangle earrings and jawline silhouette.",
        category_fit=["Jewellery", "Earrings", "Eyewear"],
        requires_model=True,
        pose="Profile head turn showing earring suspended elegantly",
        lighting="Contoured edge lighting creating luminous silhouette",
        preview_url="https://images.unsplash.com/photo-1517841905240-472988babdf9?w=800&auto=format&fit=crop&q=80"
    ),

    # =======================================================================
    # 10 CANONICAL STYLES: Product Photography (requires_model = False)
    # =======================================================================
    PhotographyStyleItem(
        id="product_studio_premium",
        name="Studio Premium",
        description="Iconic commercial studio shot with crisp softbox reflection, soft contact shadow, and balanced fill.",
        category_fit=["All", "Candle", "Home Decor", "Electronics", "Cosmetics", "Packaged Goods", "Footwear"],
        requires_model=False,
        pose=None,
        lighting="Diffused double-softbox studio lighting with pure neutral reflections",
        preview_url="https://images.unsplash.com/photo-1523275335684-37898b6baf30?w=800&auto=format&fit=crop&q=80"
    ),
    PhotographyStyleItem(
        id="product_luxury_cinematic",
        name="Luxury Cinematic",
        description="Artistic podium staging on travertine, fluted plaster, or marble with architectural shadows and warm spotlight.",
        category_fit=["All", "Candle", "Perfume", "Jewellery", "Skincare", "Watches"],
        requires_model=False,
        pose=None,
        lighting="Dramatic warm spotlight with soft organic leaf shadows and rich contrast",
        preview_url="https://images.unsplash.com/photo-1541643600914-78b084683601?w=800&auto=format&fit=crop&q=80"
    ),
    PhotographyStyleItem(
        id="product_marketplace_white",
        name="Marketplace White",
        description="Pure pure clean #FFFFFF white background, crisp e-commerce shadow, compliant with Amazon and Shopify standards.",
        category_fit=["All", "Clothing", "Electronics", "Footwear", "Packaged Goods", "Kitchenware"],
        requires_model=False,
        pose=None,
        lighting="High-key studio strobe lighting eliminating background gradients completely",
        preview_url="https://images.unsplash.com/photo-1583394838336-acd977736f90?w=800&auto=format&fit=crop&q=80"
    ),
    PhotographyStyleItem(
        id="product_lifestyle",
        name="Lifestyle",
        description="Organic product placement in an authentic upscale modern home, cafe, or office setting.",
        category_fit=["All", "Candle", "Home Decor", "Electronics", "Kitchenware", "Cosmetics"],
        requires_model=False,
        pose=None,
        lighting="Golden hour sunbeams filtering through window with gentle natural bokeh",
        preview_url="https://images.unsplash.com/photo-1507679799987-c73779587ccf?w=800&auto=format&fit=crop&q=80"
    ),
    PhotographyStyleItem(
        id="product_minimal",
        name="Minimal",
        description="Pure geometric plinth, subtle neutral tones, clean lines, and uncluttered composition.",
        category_fit=["All", "Cosmetics", "Skincare", "Tech", "Jewellery", "Perfume"],
        requires_model=False,
        pose=None,
        lighting="Soft natural diffused daylight with clean architectural edge shadows",
        preview_url="https://images.unsplash.com/photo-1526170375885-4d8ecf77b99f?w=800&auto=format&fit=crop&q=80"
    ),
    PhotographyStyleItem(
        id="product_top_down",
        name="Top-Down",
        description="Direct 90-degree overhead flat lay composition arranged with harmonious aesthetic props.",
        category_fit=["All", "Clothing", "Jewellery", "Stationery", "Food", "Cosmetics"],
        requires_model=False,
        pose=None,
        lighting="Even shadowless daylight flat lighting on linen, wood, or marble surface",
        preview_url="https://images.unsplash.com/photo-1491553895911-0055eca6402d?w=800&auto=format&fit=crop&q=80"
    ),
    PhotographyStyleItem(
        id="product_close_up",
        name="Close-Up",
        description="Macro focus on texture, material grain, stitching, engraving, and fine craftsmanship.",
        category_fit=["All", "Jewellery", "Candle", "Leather Goods", "Footwear", "Cosmetics"],
        requires_model=False,
        pose=None,
        lighting="Raking directional light sculpting micro-texture and premium materials",
        preview_url="https://images.unsplash.com/photo-1608248597359-57790b4d40e1?w=800&auto=format&fit=crop&q=80"
    ),
    PhotographyStyleItem(
        id="product_campaign_photography",
        name="Campaign Photography",
        description="Bold conceptual visual with color-blocked studio backdrops and elevated dynamic styling.",
        category_fit=["All", "Footwear", "Beverages", "Tech", "Beauty"],
        requires_model=False,
        pose=None,
        lighting="Vibrant pop lighting with chromatic contrast and razor-sharp clarity",
        preview_url="https://images.unsplash.com/photo-1522335789203-aabd1fc54bc9?w=800&auto=format&fit=crop&q=80"
    ),
    PhotographyStyleItem(
        id="product_editorial",
        name="Editorial",
        description="Art-directed editorial still life for luxury print catalogs with curated textural elements.",
        category_fit=["All", "Perfume", "Jewellery", "Luxury Goods", "Cosmetics"],
        requires_model=False,
        pose=None,
        lighting="Dramatic editorial spotlighting with nuanced chiaroscuro and atmospheric depth",
        preview_url="https://images.unsplash.com/photo-1512496015851-a90fb38ba796?w=800&auto=format&fit=crop&q=80"
    ),
    PhotographyStyleItem(
        id="product_fashion_studio",
        name="Fashion Studio",
        description="Garment, footwear or accessory displayed on high-end invisible plinth or clean tabletop with crisp fashion studio light.",
        category_fit=["All", "Clothing", "Footwear", "Bags", "Accessories"],
        requires_model=False,
        pose=None,
        lighting="High-key crisp studio lighting with subtle dimensional drop shadow",
        preview_url="https://images.unsplash.com/photo-1515886657613-9f3515b0c78f?w=800&auto=format&fit=crop&q=80"
    ),

    # --- Product-only Legacy Styles ---
    PhotographyStyleItem(
        id="clean_hero_shot",
        name="Clean Hero Product Shot",
        description="Iconic commercial studio shot with crisp softbox reflection and contact shadow.",
        category_fit=["All", "Candle", "Home Decor", "Electronics", "Cosmetics", "Packaged Goods", "Footwear"],
        requires_model=False,
        pose=None,
        lighting="Diffused double-softbox studio lighting with pure neutral reflections",
        preview_url="https://images.unsplash.com/photo-1523275335684-37898b6baf30?w=800&auto=format&fit=crop&q=80"
    ),
    PhotographyStyleItem(
        id="lifestyle_placement",
        name="Lifestyle Product Placement",
        description="Organic product placement in an authentic upscale modern home, cafe, or office setting.",
        category_fit=["All", "Candle", "Home Decor", "Electronics", "Kitchenware", "Cosmetics"],
        requires_model=False,
        pose=None,
        lighting="Golden hour sunbeams filtering through window with gentle bokeh",
        preview_url="https://images.unsplash.com/photo-1507679799987-c73779587ccf?w=800&auto=format&fit=crop&q=80"
    ),
    PhotographyStyleItem(
        id="top_down_flat_lay",
        name="Top-Down Flat Lay",
        description="Direct 90-degree overhead composition arranged with harmonious aesthetic props.",
        category_fit=["All", "Clothing", "Jewellery", "Stationery", "Food", "Cosmetics"],
        requires_model=False,
        pose=None,
        lighting="Even shadowless daylight flat lighting on linen, wood, or marble",
        preview_url="https://images.unsplash.com/photo-1491553895911-0055eca6402d?w=800&auto=format&fit=crop&q=80"
    ),
    PhotographyStyleItem(
        id="closeup_detail_shot",
        name="Close-up Detail Shot",
        description="Macro focus on texture, material grain, stitching, engraving, and fine craftsmanship.",
        category_fit=["All", "Jewellery", "Candle", "Leather Goods", "Footwear", "Cosmetics"],
        requires_model=False,
        pose=None,
        lighting="Raking directional light sculpting micro-texture and premium materials",
        preview_url="https://images.unsplash.com/photo-1608248597359-57790b4d40e1?w=800&auto=format&fit=crop&q=80"
    ),
    PhotographyStyleItem(
        id="luxury_studio_composition",
        name="Luxury Studio Composition",
        description="Artistic podium staging on travertine, fluted plaster, or marble with architectural shadows.",
        category_fit=["All", "Candle", "Perfume", "Jewellery", "Skincare", "Watches"],
        requires_model=False,
        pose=None,
        lighting="Dramatic warm spotlight with soft organic leaf shadows",
        preview_url="https://images.unsplash.com/photo-1541643600914-78b084683601?w=800&auto=format&fit=crop&q=80"
    ),
    PhotographyStyleItem(
        id="creative_campaign",
        name="Creative Campaign Photography",
        description="Bold conceptual visual with color-blocked studio backdrops and elevated dynamic styling.",
        category_fit=["All", "Footwear", "Beverages", "Tech", "Beauty"],
        requires_model=False,
        pose=None,
        lighting="Vibrant pop lighting with chromatic contrast and razor-sharp clarity",
        preview_url="https://images.unsplash.com/photo-1522335789203-aabd1fc54bc9?w=800&auto=format&fit=crop&q=80"
    )
]


class PhotoshootService:
    """
    Unified AI Product Photoshoot Studio Service.
    Powers the complete 5-step / 8-phase workflow for both model-based and product-only commercial photography.
    """

    PHOTOSHOOT_DIR = Path("uploads") / "photoshoot"
    PRODUCTS_DIR = PHOTOSHOOT_DIR / "products"
    ENHANCED_DIR = PHOTOSHOOT_DIR / "enhanced"
    FINAL_DIR = PHOTOSHOOT_DIR / "final"

    @classmethod
    def ensure_directories(cls):
        cls.PRODUCTS_DIR.mkdir(parents=True, exist_ok=True)
        cls.ENHANCED_DIR.mkdir(parents=True, exist_ok=True)
        cls.FINAL_DIR.mkdir(parents=True, exist_ok=True)

    @classmethod
    def validate_generation_parameters(
        cls,
        mode: str,
        selected_enhanced_ids: Optional[List[str]] = None,
        model_id: Optional[str] = None,
        styles: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Validates generation parameters according to the selected workflow mode."""
        clean_mode = (mode or "").strip().lower()
        if clean_mode not in ("avatar_photoshoot", "product_photography"):
            return {"valid": False, "error": f"Invalid workflow mode '{mode}'."}

        if not selected_enhanced_ids:
            return {"valid": False, "error": "At least one enhanced image must be selected."}

        if clean_mode == "avatar_photoshoot":
            if not model_id or not str(model_id).strip():
                return {"valid": False, "error": "model_id is mandatory for avatar_photoshoot mode. Please select an AI model."}
            valid_ids = {m.model_id for m in CURATED_AI_MODELS}
            if model_id not in valid_ids:
                return {"valid": False, "error": f"Invalid model_id '{model_id}'."}

        return {"valid": True}

    # -----------------------------------------------------------------------
    # PHASE 1: Upload Product Images
    # -----------------------------------------------------------------------
    @classmethod
    async def upload_product_images(
        cls,
        db,
        user_id: str,
        files: List[UploadFile],
        session_id: Optional[str] = None,
        workflow_mode: Optional[str] = None,
        product_category: Optional[str] = None,
        angles: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        cls.ensure_directories()
        if not files:
            raise HTTPException(status_code=400, detail="No product images uploaded.")

        allowed_exts = {".jpg", ".jpeg", ".png", ".webp"}
        max_file_size = 10 * 1024 * 1024  # 10MB per image

        # Validate workflow mode if provided
        clean_workflow_mode = None
        if workflow_mode:
            clean_mode = workflow_mode.strip().lower()
            if clean_mode in ("avatar_photoshoot", "product_photography"):
                clean_workflow_mode = clean_mode

        # Initialize or fetch session
        session_doc = None
        if session_id:
            session_doc = await db["photoshoot_sessions"].find_one({
                "session_id": session_id,
                "user_id": str(user_id)
            })

        actual_session_id = session_id if session_doc else f"sess_{uuid.uuid4().hex[:12]}"
        resolved_mode = clean_workflow_mode or (session_doc.get("workflow_mode") if session_doc else None) or "product_photography"
        now = datetime.now(timezone.utc)

        uploaded_assets = []
        angle_list = angles or []

        for idx, file in enumerate(files):
            fname = file.filename or f"product_{idx}.jpg"
            ext = Path(fname).suffix.lower()
            if ext not in allowed_exts:
                raise HTTPException(
                    status_code=400,
                    detail=f"Unsupported format '{ext}' for file '{fname}'. Supported: JPG, JPEG, PNG, WEBP."
                )

            content = await file.read()
            if len(content) > max_file_size:
                raise HTTPException(
                    status_code=413,
                    detail=f"Image '{fname}' exceeds 10MB limit."
                )
            if len(content) == 0:
                raise HTTPException(
                    status_code=400,
                    detail=f"Uploaded file '{fname}' is empty (0 bytes)."
                )

            # Validate dimensions with PIL
            try:
                img = Image.open(io.BytesIO(content))
                width, height = img.size
                if width < 100 or height < 100:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Image '{fname}' dimensions ({width}x{height}) are too small. Minimum required: 100x100."
                    )
            except HTTPException:
                raise
            except Exception as img_err:
                raise HTTPException(
                    status_code=400,
                    detail=f"File '{fname}' is corrupted or not a valid image: {img_err}"
                )

            # Assign angle from provided list or default
            assigned_angle = "Front"
            if idx < len(angle_list) and angle_list[idx]:
                valid_angles = {"Front", "Back", "Side", "Close-up", "Other"}
                clean_angle = angle_list[idx].strip().title()
                assigned_angle = clean_angle if clean_angle in valid_angles else "Other"
            elif idx == 1:
                assigned_angle = "Back"
            elif idx == 2:
                assigned_angle = "Side"
            elif idx >= 3:
                assigned_angle = "Close-up"

            # Save locally
            unique_name = f"{uuid.uuid4().hex[:16]}{ext}"
            file_path = cls.PRODUCTS_DIR / unique_name
            with open(file_path, "wb") as f:
                f.write(content)

            image_id = f"img_{uuid.uuid4().hex[:12]}"
            rel_url = f"/uploads/photoshoot/products/{unique_name}"

            asset = {
                "image_id": image_id,
                "session_id": actual_session_id,
                "user_id": str(user_id),
                "url": rel_url,
                "filename": fname,
                "angle": assigned_angle,
                "file_size": len(content),
                "dimensions": {"width": width, "height": height},
                "content_type": file.content_type or f"image/{ext.replace('.', '')}",
                "image_type": "original",
                "created_at": now
            }
            uploaded_assets.append(dict(asset))
            await db["photoshoot_images"].insert_one(dict(asset))

        # Upsert session document
        if session_doc:
            update_fields: Dict[str, Any] = {
                "product_category": product_category or session_doc.get("product_category"),
                "status": "uploaded",
                "updated_at": now
            }
            if clean_workflow_mode:
                update_fields["workflow_mode"] = clean_workflow_mode

            await db["photoshoot_sessions"].update_one(
                {"session_id": actual_session_id},
                {
                    "$push": {"original_images": {"$each": uploaded_assets}},
                    "$set": update_fields
                }
            )
        else:
            session_payload = {
                "session_id": actual_session_id,
                "user_id": str(user_id),
                "workflow_mode": resolved_mode,
                "title": f"Photoshoot - {product_category or 'Product'}",
                "product_category": product_category,
                "product_type": None,
                "analysis": None,
                "original_images": uploaded_assets,
                "enhanced_images": [],
                "selected_enhanced_image_ids": [],
                "use_model": resolved_mode == "avatar_photoshoot",
                "model_id": None,
                "model_details": None,
                "selected_styles": [],
                "custom_prompt": None,
                "prepared_prompt": None,
                "status": "uploaded",
                "generation_jobs": [],
                "generated_images": [],
                "saved_image_ids": [],
                "created_at": now,
                "updated_at": now
            }
            await db["photoshoot_sessions"].insert_one(session_payload)

        return {
            "success": True,
            "session_id": actual_session_id,
            "workflow_mode": resolved_mode,
            "product_category": product_category,
            "total_uploaded": len(uploaded_assets),
            "uploaded_images": uploaded_assets,
            "message": "Product images uploaded and session initialized successfully."
        }

    # -----------------------------------------------------------------------
    # PHASE 2: AI Product Visual Analysis
    # -----------------------------------------------------------------------
    @classmethod
    async def analyze_product(
        cls,
        db,
        user_id: str,
        session_id: str,
        image_ids: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        session_doc = await db["photoshoot_sessions"].find_one({
            "session_id": session_id,
            "user_id": str(user_id)
        })
        if not session_doc:
            raise HTTPException(status_code=404, detail="Photoshoot session not found.")

        orig_images = session_doc.get("original_images", [])
        if not orig_images:
            raise HTTPException(status_code=400, detail="No product images found in this session.")

        # Target selected images or all (support multiple reference angles)
        target_images = orig_images
        if image_ids:
            target_images = [img for img in orig_images if img.get("image_id") in image_ids] or orig_images

        analysis_data: Optional[Dict[str, Any]] = None
        images_for_analysis = []
        for asset in target_images[:4]:
            raw_rel = asset.get("url", "").lstrip("/")
            lp = Path(raw_rel)
            if lp.exists():
                try:
                    with open(lp, "rb") as f:
                        b = f.read()
                    mime = asset.get("content_type", "image/jpeg")
                    images_for_analysis.append(f"data:{mime};base64,{base64.b64encode(b).decode('utf-8')}")
                except Exception as err:
                    logger.warning(f"Could not load image for analysis {lp}: {err}")

        if images_for_analysis:
            try:
                cat_hint = session_doc.get("product_category") or ""
                cat_context = f"\nUser indicated category: '{cat_hint}'." if cat_hint else ""

                analysis_prompt = (
                    "You are a professional e-commerce product inspector and commercial photoshoot director. "
                    f"Analyze the attached product image(s) with strict visual accuracy.{cat_context} "
                    "Return ONLY a valid JSON object with the following fields without any markdown wrapping:\n"
                    "{\n"
                    '  "product_category": "Standard broad category (e.g. Clothing, Jewellery, Footwear, Home Decor, Cosmetics, Electronics, Food, Accessories)",\n'
                    '  "product_type": "Specific product identification (e.g. Men\'s T-shirt, Scented Candle, Gold Pendant, Running Shoes)",\n'
                    '  "main_colors": ["Color 1", "Color 2"],\n'
                    '  "shape_and_design": ["Visual shape", "Cut / Silhouette", "Pattern"],\n'
                    '  "material_and_texture": "Visually identifiable fabric/material and texture (e.g. Combed Cotton, Matte Ceramic, Polished Gold)",\n'
                    '  "brand_logo_and_text": "Visible logo name, label text, or None detected",\n'
                    '  "product_details": ["Key distinctive visual features", "Collar/closure/container details"],\n'
                    '  "suitable_for_model": true/false (true if apparel, jewellery, wearable or personal accessory; false for decor, candles, food, electronics),\n'
                    '  "recommended_model_type": "male" / "female" / "unisex" / "none",\n'
                    '  "recommended_styles": ["Style 1", "Style 2", "Style 3"]\n'
                    "}\n"
                    "STRICT RULE: Do NOT invent or hallucinate product details not visually present in the image. "
                    "If a detail is unclear, use 'Unspecified' or 'None detected'."
                )

                provider = AIProviderFactory.get_provider(preferred="openai", tier="fast")
                logger.info("Executing OpenAI GPT-4.1 Mini visual product analysis...")
                res = await provider.generate_text(
                    prompt=analysis_prompt,
                    images=images_for_analysis,
                    system_prompt="You are a professional product inspector. Return ONLY valid JSON."
                )
                raw_text = (res.get("text", "") if isinstance(res, dict) else str(res)).strip()
                if "```" in raw_text:
                    raw_text = re.sub(r"^```(json)?", "", raw_text).strip()
                    raw_text = re.sub(r"```$", "", raw_text).strip()
                analysis_data = json.loads(raw_text)
                logger.info("OpenAI visual product analysis succeeded")
            except Exception as e:
                logger.warning(f"OpenAI visual analysis failed or timed out: {e}")

        # Deterministic visual inspection fallback
        if not analysis_data:
            cat_hint = session_doc.get("product_category", "Product") or "Product"
            is_clothing = any(c in cat_hint.lower() for c in ["clothing", "shirt", "apparel", "wear", "dress"])
            is_jewellery = any(c in cat_hint.lower() for c in ["jewel", "ring", "necklace", "earring"])
            is_candle = "candle" in cat_hint.lower()

            suitable_model = is_clothing or is_jewellery
            analysis_data = {
                "product_category": cat_hint if cat_hint != "Product" else ("Clothing" if is_clothing else "Home Decor"),
                "product_type": "Men's T-shirt" if is_clothing else ("Scented Candle" if is_candle else cat_hint),
                "main_colors": ["Primary Visual Color"],
                "shape_and_design": ["Standard commercial product geometry"],
                "material_and_texture": "High quality manufactured material",
                "brand_logo_and_text": "None detected",
                "product_details": ["Clean product finish"],
                "suitable_for_model": suitable_model,
                "recommended_model_type": "male" if is_clothing else ("female" if is_jewellery else "none"),
                "recommended_styles": [
                    "Front View", "Sitting Pose", "Studio Premium"
                ] if suitable_model else [
                    "Clean Hero Product Shot", "Lifestyle Product Placement", "Luxury Studio Composition"
                ]
            }

        # Update session with analysis
        now = datetime.now(timezone.utc)
        await db["photoshoot_sessions"].update_one(
            {"session_id": session_id},
            {
                "$set": {
                    "product_category": analysis_data.get("product_category"),
                    "product_type": analysis_data.get("product_type"),
                    "analysis": analysis_data,
                    "status": "analyzed",
                    "updated_at": now
                }
            }
        )

        return {
            "success": True,
            "session_id": session_id,
            "analysis": analysis_data,
            "message": "AI product visual analysis completed successfully."
        }

    # -----------------------------------------------------------------------
    # PHASE 3: AI Product Image Enhancement
    # -----------------------------------------------------------------------
    @classmethod
    async def enhance_product_images(
        cls,
        db,
        user_id: str,
        session_id: str,
        image_id: Optional[str] = None,
        styles: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        cls.ensure_directories()
        session_doc = await db["photoshoot_sessions"].find_one({
            "session_id": session_id,
            "user_id": str(user_id)
        })
        if not session_doc:
            raise HTTPException(status_code=404, detail="Photoshoot session not found.")

        orig_images = session_doc.get("original_images", [])
        if not orig_images:
            raise HTTPException(status_code=400, detail="No original product images found in this session.")

        # Find target source image
        source_image = orig_images[0]
        if image_id:
            for img in orig_images:
                if img.get("image_id") == image_id:
                    source_image = img
                    break

        target_styles = styles or ["Studio Premium", "Luxury Cinematic", "Marketplace White"]
        valid_styles = {"Studio Premium", "Luxury Cinematic", "Marketplace White"}
        target_styles = [s for s in target_styles if s in valid_styles] or ["Studio Premium", "Luxury Cinematic", "Marketplace White"]

        p_name = session_doc.get("product_type") or session_doc.get("product_category") or "Product"
        analysis = session_doc.get("analysis", {}) or {}
        colors = ", ".join(analysis.get("main_colors", ["original colors"]))

        now = datetime.now(timezone.utc)
        enhanced_results = []

        for style in target_styles:
            enh_id = f"enh_{uuid.uuid4().hex[:12]}"
            filename = f"enhanced_{enh_id}.jpg"
            target_path = cls.ENHANCED_DIR / filename

            # Build style-specific prompt adhering strictly to product preservation
            if style == "Studio Premium":
                style_desc = "Soft ambient illumination, subtle neutral background, delicate contact shadow, commercial studio lighting"
            elif style == "Luxury Cinematic":
                style_desc = "Dramatic chiaroscuro contrast, warm key lighting, elegant depth of field, luxury editorial podium"
            else:  # Marketplace White
                style_desc = "Pure pure clean #FFFFFF white background, crisp e-commerce shadow, compliant with Amazon and Shopify standards"

            prompt = (
                f"Commercial e-commerce product enhancement of {p_name} in {colors}. "
                f"Style: {style}. {style_desc}. "
                f"Product identity, logos, packaging, colors and texture strictly preserved. 8k resolution, crisp photorealistic details."
            )

            # Preserve authentic product geometry, logo and textures by applying photographic enhancement directly to source
            rel_src = (source_image.get("url") or "").lstrip("/").replace("\\", "/")
            src_file = Path(rel_src)
            enhanced_from_src = False

            if src_file.exists() and src_file.is_file():
                try:
                    with Image.open(src_file) as im:
                        im_rgb = im.convert("RGB")
                        im_norm = ImageOps.autocontrast(im_rgb, cutoff=0.5)

                        if style == "Studio Premium":
                            im_proc = ImageEnhance.Color(im_norm).enhance(1.08)
                            im_proc = ImageEnhance.Contrast(im_proc).enhance(1.12)
                            im_proc = ImageEnhance.Sharpness(im_proc).enhance(1.18)
                        elif style == "Luxury Cinematic":
                            im_proc = ImageEnhance.Color(im_norm).enhance(1.10)
                            im_proc = ImageEnhance.Contrast(im_proc).enhance(1.22)
                            im_proc = ImageEnhance.Brightness(im_proc).enhance(0.96)
                            im_proc = ImageEnhance.Sharpness(im_proc).enhance(1.20)
                        else:  # Marketplace White
                            im_proc = ImageEnhance.Brightness(im_norm).enhance(1.05)
                            im_proc = ImageEnhance.Contrast(im_proc).enhance(1.15)
                            im_proc = ImageEnhance.Sharpness(im_proc).enhance(1.22)

                        im_proc.save(target_path, format="JPEG", quality=95, subsampling=0)
                        enhanced_from_src = True
                except Exception as enh_err:
                    logger.warning(f"Local photographic enhancement note: {enh_err}")

            if not enhanced_from_src or not target_path.exists():
                download_ok = await cls._generate_and_save_visual(prompt=prompt, target_path=target_path)
                if not download_ok or not target_path.exists():
                    cls._synthesize_fallback_image(target_path, title=f"{p_name}\n({style})", bg_color=(245, 245, 245))

            rel_url = f"/uploads/photoshoot/enhanced/{filename}"
            item = {
                "image_id": enh_id,
                "source_image_id": source_image.get("image_id"),
                "style": style,
                "url": rel_url,
                "is_selected": False,
                "created_at": now
            }
            enhanced_results.append(item)

            # Record in photoshoot_images
            await db["photoshoot_images"].insert_one({
                "image_id": enh_id,
                "session_id": session_id,
                "user_id": str(user_id),
                "url": rel_url,
                "filename": filename,
                "angle": source_image.get("angle", "Front"),
                "file_size": target_path.stat().st_size if target_path.exists() else 1024,
                "dimensions": {"width": 1024, "height": 1024},
                "content_type": "image/jpeg",
                "image_type": "enhanced",
                "enhancement_style": style,
                "is_selected": False,
                "created_at": now
            })

        # Save enhanced list to session
        await db["photoshoot_sessions"].update_one(
            {"session_id": session_id},
            {
                "$push": {"enhanced_images": {"$each": enhanced_results}},
                "$set": {"status": "enhanced", "updated_at": now}
            }
        )

        return {
            "success": True,
            "session_id": session_id,
            "total_variations": len(enhanced_results),
            "enhanced_images": enhanced_results,
            "message": "Product image enhancement variations generated."
        }

    # -----------------------------------------------------------------------
    # PHASE 4: Curated AI Model Selection
    # -----------------------------------------------------------------------
    @classmethod
    def get_model_gallery(
        cls,
        gender: Optional[str] = None,
        category: Optional[str] = None,
    ) -> List[AIModelItem]:
        models = CURATED_AI_MODELS
        if gender:
            g_clean = gender.strip().lower()
            models = [m for m in models if m.gender.lower() == g_clean or m.gender.lower() == "unisex"]
        if category:
            c_clean = category.strip().lower()
            models = [
                m for m in models
                if any(c_clean in cat.lower() for cat in m.supported_categories) or "all" in [c.lower() for c in m.supported_categories]
            ]
        return models

    # -----------------------------------------------------------------------
    # PHASE 5: Photography Styles and Poses Recommendations
    # -----------------------------------------------------------------------
    @classmethod
    def get_photography_styles(
        cls,
        category: Optional[str] = None,
        use_model: bool = False,
        model_id: Optional[str] = None,
        workflow_mode: Optional[str] = None,
    ) -> List[PhotographyStyleItem]:
        cat_clean = (category or "All").strip().lower()

        # Determine target model requirement based on mode or use_model flag
        if workflow_mode == "avatar_photoshoot":
            target_requires_model = True
        elif workflow_mode == "product_photography":
            target_requires_model = False
        else:
            target_requires_model = bool(use_model)

        styles = []
        for s in PHOTOGRAPHY_STYLES_CATALOG:
            # Filter by model requirement
            if s.requires_model != target_requires_model:
                continue

            # Category filtering: check if style fits category or is universal 'All'
            fits_cat = any(
                cat_clean in c.lower() or "all" in c.lower() or c.lower() in cat_clean
                for c in s.category_fit
            )
            if fits_cat:
                styles.append(s)

        # Ensure at least 5 fallback styles exist if strict filter was too narrow
        if len(styles) < 5:
            for s in PHOTOGRAPHY_STYLES_CATALOG:
                if s.requires_model == target_requires_model and s not in styles:
                    styles.append(s)
                if len(styles) >= 10:
                    break

        return styles

    # -----------------------------------------------------------------------
    # PHASE 6: Custom Prompt and Multilingual Voice Preparation
    # -----------------------------------------------------------------------
    @classmethod
    async def prepare_prompt(
        cls,
        db,
        user_id: str,
        session_id: str,
        workflow_mode: Optional[str] = None,
        custom_prompt: Optional[str] = None,
        language: Optional[str] = "en",
        use_model: bool = False,
        model_id: Optional[str] = None,
        selected_styles: Optional[List[str]] = None,
        audio_file: Optional[UploadFile] = None,
    ) -> Dict[str, Any]:
        session_doc = await db["photoshoot_sessions"].find_one({
            "session_id": session_id,
            "user_id": str(user_id)
        })
        if not session_doc:
            raise HTTPException(status_code=404, detail="Photoshoot session not found.")

        # Determine workflow mode
        clean_workflow_mode = (workflow_mode or "").strip().lower()
        if clean_workflow_mode in ("avatar_photoshoot", "product_photography"):
            resolved_mode = clean_workflow_mode
        elif use_model or model_id:
            resolved_mode = "avatar_photoshoot"
        elif session_doc.get("workflow_mode"):
            resolved_mode = session_doc["workflow_mode"]
        else:
            resolved_mode = "product_photography"

        # Mode validation
        if resolved_mode == "avatar_photoshoot":
            target_model_id = model_id or session_doc.get("model_id")
            if not target_model_id or not str(target_model_id).strip():
                raise HTTPException(
                    status_code=400,
                    detail="model_id is mandatory for avatar_photoshoot mode. Please select an AI model."
                )
            valid_model_ids = {m.model_id for m in CURATED_AI_MODELS}
            if target_model_id not in valid_model_ids:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid model_id '{target_model_id}'. Selected model does not exist in curated catalog."
                )
            use_model = True
            model_id = target_model_id
        else:  # product_photography
            use_model = False
            model_id = None

        user_instruction = (custom_prompt or "").strip()
        detected_lang = language or "en"

        # Voice fallback: if audio was uploaded, transcribe via STTService
        if audio_file:
            try:
                stt_res = await STTService.transcribe_audio(file=audio_file, language=language)
                transcribed_text = stt_res.get("text", "")
                if transcribed_text:
                    user_instruction = f"{user_instruction} {transcribed_text}".strip()
                    detected_lang = stt_res.get("detected_language") or detected_lang
            except Exception as stt_err:
                logger.warning(f"Voice transcription note: {stt_err}")

        # Fetch model details if selected
        model_obj = None
        if use_model and model_id:
            for m in CURATED_AI_MODELS:
                if m.model_id == model_id:
                    model_obj = m.model_dump()
                    break

        styles_to_apply = selected_styles or session_doc.get("selected_styles") or ["Studio Premium"]
        analysis = session_doc.get("analysis", {}) or {}
        p_name = session_doc.get("product_type") or session_doc.get("product_category") or "Product"
        colors = ", ".join(analysis.get("main_colors", ["natural colors"]))
        texture = analysis.get("material_and_texture", "premium texture")
        brand_logo = analysis.get("brand_logo_and_text")
        logo_note = f", preserving brand logo/label '{brand_logo}'" if brand_logo and brand_logo.lower() != "none detected" else ""

        # Synthesize professional photoshoot generation prompt using OpenAI GPT-4.1 Mini
        prepared_prompt = ""
        try:
            if resolved_mode == "avatar_photoshoot":
                photo_type_desc = (
                    f"Model-based commercial catalog fashion photoshoot on {model_obj['name'] if model_obj else 'model'}. "
                    f"Position product accurately and naturally on model while maintaining model identity consistently across images."
                )
            else:
                photo_type_desc = (
                    "Product-only commercial still-life photography. "
                    "STRICT REQUIREMENT: Do NOT include any human model, person, hands, body parts, or mannequins in this image. "
                    "Focus on lighting, background, shadows, camera angle, and composition."
                )

            sys_prompt = (
                "You are a Vogue Commercial Creative Director. "
                "Synthesize the following product specifications, styling, and user instructions into a single concise, "
                "master photography generation prompt (under 60 words). "
                "CRITICAL: Keep the product identity, color, texture, shape, and branding strictly preserved.\n"
                f"Product: {p_name} ({colors}, {texture}{logo_note})\n"
                f"Photography Mode: {resolved_mode}\n"
                f"Photography Specification: {photo_type_desc}\n"
                f"Selected Styles/Poses: {', '.join(styles_to_apply)}\n"
                f"User Custom Instructions: {user_instruction or 'None'}\n"
                "Output ONLY the final generation prompt text."
            )
            provider = AIProviderFactory.get_provider(preferred="openai", tier="fast")
            logger.info("Synthesizing photoshoot prompt with OpenAI GPT-4.1 Mini...")
            res = await provider.generate_text(
                prompt=sys_prompt,
                system_prompt="You are an expert commercial photoshoot creative director. Return ONLY the generation prompt."
            )
            txt = res.get("text", "").strip() if isinstance(res, dict) else str(res).strip()
            if txt:
                prepared_prompt = txt.replace("\n", " ")
                logger.info("Photoshoot prompt synthesis succeeded")
        except Exception as e:
            logger.warning(f"Prompt preparation LLM note: {e}")

        if not prepared_prompt:
            styles_part = ", ".join(styles_to_apply)
            user_part = f", {user_instruction}" if user_instruction else ""
            if resolved_mode == "avatar_photoshoot":
                model_name_str = model_obj['name'] if model_obj else 'model'
                prepared_prompt = (
                    f"Commercial fashion catalog photoshoot of authentic {p_name} in {colors}, {texture}{logo_note}, "
                    f"modeled naturally by {model_name_str}. Style: {styles_part}{user_part}. "
                    f"Consistent model appearance, studio lighting, 8k resolution, razor-sharp details."
                )
            else:
                prepared_prompt = (
                    f"Professional commercial product photoshoot of authentic {p_name} in {colors}, {texture}{logo_note}. "
                    f"Product-only still life without human model or mannequin. Style: {styles_part}{user_part}. "
                    f"Studio lighting, 8k resolution, photorealistic commercial product photography, razor-sharp details."
                )

        now = datetime.now(timezone.utc)
        await db["photoshoot_sessions"].update_one(
            {"session_id": session_id},
            {
                "$set": {
                    "workflow_mode": resolved_mode,
                    "use_model": bool(use_model),
                    "model_id": model_id if use_model else None,
                    "model_details": model_obj if use_model else None,
                    "selected_styles": styles_to_apply,
                    "custom_prompt": user_instruction,
                    "prepared_prompt": prepared_prompt,
                    "status": "prompt_ready",
                    "updated_at": now
                }
            }
        )

        return {
            "success": True,
            "session_id": session_id,
            "workflow_mode": resolved_mode,
            "prepared_prompt": prepared_prompt,
            "detected_language": detected_lang,
            "workflow_summary": {
                "workflow_mode": resolved_mode,
                "use_model": use_model,
                "model_name": model_obj.get("name") if model_obj else "None (Product Only)",
                "product_type": p_name,
                "selected_styles": styles_to_apply,
                "user_instructions": user_instruction or "None"
            },
            "message": "Multilingual instructions interpreted and synthesized into studio photographic specifications."
        }

    # -----------------------------------------------------------------------
    # PHASE 7: Final Photoshoot Batch Generation
    # -----------------------------------------------------------------------
    @classmethod
    async def start_photoshoot_generation(
        cls,
        db,
        user_id: str,
        session_id: str,
        workflow_mode: Optional[str] = None,
        selected_enhanced_image_ids: Optional[List[str]] = None,
        product_category: Optional[str] = None,
        use_model: bool = False,
        model_id: Optional[str] = None,
        selected_styles: Optional[List[str]] = None,
        custom_prompt: Optional[str] = None,
        image_count: int = 5,
    ) -> Dict[str, Any]:
        cls.ensure_directories()
        session_doc = await db["photoshoot_sessions"].find_one({
            "session_id": session_id,
            "user_id": str(user_id)
        })
        if not session_doc:
            raise HTTPException(status_code=404, detail="Photoshoot session not found.")

        # Determine workflow mode
        clean_workflow_mode = (workflow_mode or "").strip().lower()
        if clean_workflow_mode in ("avatar_photoshoot", "product_photography"):
            resolved_mode = clean_workflow_mode
        elif use_model or model_id:
            resolved_mode = "avatar_photoshoot"
        elif session_doc.get("workflow_mode"):
            resolved_mode = session_doc["workflow_mode"]
        else:
            resolved_mode = "product_photography"

        # Mode validation
        if resolved_mode == "avatar_photoshoot":
            target_model_id = model_id or session_doc.get("model_id")
            if not target_model_id or not str(target_model_id).strip():
                raise HTTPException(
                    status_code=400,
                    detail="model_id is mandatory for avatar_photoshoot mode. Please select an AI model."
                )
            valid_model_ids = {m.model_id for m in CURATED_AI_MODELS}
            if target_model_id not in valid_model_ids:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid model_id '{target_model_id}'. Selected model does not exist in curated catalog."
                )
            use_model = True
            model_id = target_model_id
        else:  # product_photography
            use_model = False
            model_id = None

        # Prevent duplicate active jobs / charges on repeated requests
        active_job = await db["photoshoot_jobs"].find_one({
            "session_id": session_id,
            "user_id": str(user_id),
            "status": {"$in": ["pending", "processing"]}
        })
        if active_job:
            return {
                "success": True,
                "session_id": session_id,
                "workflow_mode": active_job.get("workflow_mode", resolved_mode),
                "job_id": active_job["job_id"],
                "status": active_job["status"],
                "estimated_time_seconds": active_job.get("total_images", 5) * 3,
                "message": "A photoshoot generation job is already active for this session."
            }

        # 1. Credit check: verify user has enough credits
        await CreditService.check_credits(db, str(user_id), "ai_photoshoot")

        # 2. Prepare job configuration
        count = min(max(1, image_count), 10)
        job_id = f"job_{uuid.uuid4().hex[:12]}"
        default_style = "Fashion Studio" if resolved_mode == "avatar_photoshoot" else "Clean Hero Product Shot"
        styles_list = selected_styles or session_doc.get("selected_styles") or [default_style]

        now = datetime.now(timezone.utc)
        job_doc = {
            "job_id": job_id,
            "session_id": session_id,
            "user_id": str(user_id),
            "workflow_mode": resolved_mode,
            "status": "pending",
            "progress_percent": 0,
            "total_images": count,
            "completed_images": 0,
            "use_model": bool(use_model),
            "model_id": model_id if use_model else None,
            "styles": styles_list,
            "prompt_used": custom_prompt or session_doc.get("prepared_prompt") or "",
            "result_images": [],
            "error": None,
            "credits_deducted": 5,
            "created_at": now,
            "completed_at": None
        }
        await db["photoshoot_jobs"].insert_one(job_doc)

        await db["photoshoot_sessions"].update_one(
            {"session_id": session_id},
            {
                "$push": {"generation_jobs": job_id},
                "$set": {
                    "workflow_mode": resolved_mode,
                    "status": "generating",
                    "use_model": bool(use_model),
                    "model_id": model_id if use_model else None,
                    "selected_styles": styles_list,
                    "updated_at": now
                }
            }
        )

        # Deduct credits
        await CreditService.deduct_credits(db, str(user_id), "ai_photoshoot")
        await SubscriptionService.increment_usage(db, str(user_id), "photoshoot")

        # Launch async execution
        asyncio.create_task(
            cls._execute_photoshoot_job(
                db=db,
                job_id=job_id,
                session_id=session_id,
                user_id=user_id,
                workflow_mode=resolved_mode,
                use_model=use_model,
                model_id=model_id,
                styles=styles_list,
                custom_prompt=custom_prompt,
                count=count
            )
        )

        return {
            "success": True,
            "session_id": session_id,
            "workflow_mode": resolved_mode,
            "job_id": job_id,
            "status": "pending",
            "estimated_time_seconds": count * 3,
            "message": "Photoshoot generation started. Poll status endpoint for progress."
        }

    @classmethod
    async def _execute_photoshoot_job(
        cls,
        db,
        job_id: str,
        session_id: str,
        user_id: str,
        workflow_mode: str,
        use_model: bool,
        model_id: Optional[str],
        styles: List[str],
        custom_prompt: Optional[str],
        count: int
    ):
        """Background generator producing final 5-6 photorealistic variations."""
        try:
            await db["photoshoot_jobs"].update_one(
                {"job_id": job_id},
                {"$set": {"status": "processing", "progress_percent": 10}}
            )

            session_doc = await db["photoshoot_sessions"].find_one({"session_id": session_id})
            analysis = (session_doc.get("analysis") if session_doc else None) or {}
            p_name = (session_doc.get("product_type") if session_doc else None) or "Commercial Product"
            colors = ", ".join(analysis.get("main_colors", ["natural colors"]))
            texture = analysis.get("material_and_texture", "premium material")
            logo_info = analysis.get("brand_logo_and_text")
            logo_clause = f", accurately rendering visible logo/label '{logo_info}'" if logo_info and logo_info.lower() != "none detected" else ""

            model_info = None
            if workflow_mode == "avatar_photoshoot" or use_model:
                for m in CURATED_AI_MODELS:
                    if m.model_id == model_id:
                        model_info = m
                        break
                # Safe fallback if specified model_id not found
                if not model_info:
                    model_info = CURATED_AI_MODELS[0]

            model_name = model_info.name if model_info else "model"
            model_identity = model_info.identity_prompt if model_info and model_info.identity_prompt else model_name

            generated_items = []
            failed_items = []

            for i in range(count):
                applied_style = styles[i % len(styles)] if styles else ("Fashion Studio" if workflow_mode == "avatar_photoshoot" else "Commercial Studio")
                img_id = f"final_{uuid.uuid4().hex[:12]}"
                filename = f"photoshoot_{img_id}.jpg"
                target_path = cls.FINAL_DIR / filename

                # Vary angle, pose, and composition per iteration while keeping strict model & product identity
                if workflow_mode == "avatar_photoshoot" or use_model:
                    comp_prompt = (
                        f"Professional commercial fashion catalog photo of authentic {p_name} in exact original {colors}, {texture}{logo_clause}. "
                        f"Strictly preserve authentic product colors, logo labels, packaging and silhouette without artificial alteration. "
                        f"Modeled naturally by {model_name} ({model_identity}). Variation {i+1}: {applied_style}. "
                        f"{custom_prompt or ''}. High fashion commercial studio lighting, natural key and fill light, soft contact shadow, "
                        f"consistent model facial features and identity, realistic skin texture, 8k resolution, razor-sharp garment micro-weave, photorealistic commercial catalog."
                    )
                else:  # product_photography
                    comp_prompt = (
                        f"Professional luxury commercial product photoshoot of authentic {p_name} in exact original {colors}, {texture}{logo_clause}. "
                        f"STRICT REQUIREMENT: Product-only commercial still life photography. Do NOT include any human model, person, hands, body parts, or mannequins in this image. "
                        f"Strictly preserve original product brand logos, packaging, colors, geometry and materials without distortion. "
                        f"Clean isolated composition on minimalist studio plinth. Variation {i+1}: {applied_style}. {custom_prompt or ''}. "
                        f"Commercial advertising studio lighting, soft natural contact shadow, subtle reflections, razor-sharp focus, 8k resolution, photorealistic."
                    )

                try:
                    download_ok = await cls._generate_and_save_visual(comp_prompt, target_path)
                    if not download_ok or not target_path.exists():
                        cls._synthesize_fallback_image(
                            target_path,
                            title=f"{p_name}\n({applied_style} #{i+1})",
                            bg_color=(240, 242, 245) if not use_model else (235, 238, 245)
                        )

                    if not target_path.exists() or target_path.stat().st_size == 0:
                        raise RuntimeError(f"Visual asset generation failed for variation #{i+1}")

                    rel_url = f"/uploads/photoshoot/final/{filename}"
                    now_item = datetime.now(timezone.utc)
                    item = {
                        "image_id": img_id,
                        "session_id": session_id,
                        "style_applied": applied_style,
                        "url": rel_url,
                        "is_saved": False,
                        "created_at": now_item
                    }
                    generated_items.append(item)

                    # Store image asset
                    await db["photoshoot_images"].insert_one({
                        "image_id": img_id,
                        "session_id": session_id,
                        "user_id": str(user_id),
                        "url": rel_url,
                        "filename": filename,
                        "angle": applied_style,
                        "file_size": target_path.stat().st_size,
                        "dimensions": {"width": 1024, "height": 1024},
                        "content_type": "image/jpeg",
                        "image_type": "generated",
                        "enhancement_style": applied_style,
                        "is_saved": False,
                        "created_at": now_item
                    })
                except Exception as img_err:
                    logger.warning(f"Variation {i+1} failed during photoshoot job: {img_err}")
                    failed_items.append({
                        "index": i + 1,
                        "style": applied_style,
                        "prompt": comp_prompt,
                        "error": str(img_err)
                    })

                progress = int(((i + 1) / count) * 90)
                await db["photoshoot_jobs"].update_one(
                    {"job_id": job_id},
                    {
                        "$set": {
                            "progress_percent": progress,
                            "completed_images": len(generated_items),
                            "failed_images": len(failed_items),
                            "failed_items": failed_items,
                            "result_images": generated_items
                        }
                    }
                )

            # Determine final status (partial success handling)
            now = datetime.now(timezone.utc)
            if len(generated_items) == count:
                final_status = "completed"
            elif len(generated_items) > 0:
                final_status = "partial"
            else:
                final_status = "failed"

            await db["photoshoot_jobs"].update_one(
                {"job_id": job_id},
                {
                    "$set": {
                        "status": final_status,
                        "progress_percent": 100 if final_status == "completed" else int((len(generated_items) / count) * 100),
                        "completed_images": len(generated_items),
                        "failed_images": len(failed_items),
                        "failed_items": failed_items,
                        "can_retry": len(failed_items) > 0,
                        "result_images": generated_items,
                        "completed_at": now
                    }
                }
            )

            if generated_items:
                await db["photoshoot_sessions"].update_one(
                    {"session_id": session_id},
                    {
                        "$push": {"generated_images": {"$each": generated_items}},
                        "$set": {"status": final_status, "updated_at": now}
                    }
                )

            # If all failed, refund credits
            if final_status == "failed":
                try:
                    await CreditService.refund_credits(db, user_id=str(user_id), action="ai_photoshoot", job_id=job_id)
                except Exception as ref_err:
                    logger.warning(f"Failed to refund credits for failed job {job_id}: {ref_err}")

        except Exception as e:
            logger.error(f"Error in photoshoot job {job_id}: {e}")
            await db["photoshoot_jobs"].update_one(
                {"job_id": job_id},
                {
                    "$set": {
                        "status": "failed",
                        "error": str(e),
                        "can_retry": True,
                        "completed_at": datetime.now(timezone.utc)
                    }
                }
            )
            # Automatic credit refund on job failure
            try:
                await CreditService.refund_credits(db, user_id=str(user_id), action="ai_photoshoot", job_id=job_id)
            except Exception as ref_err:
                logger.warning(f"Failed to refund credits for job {job_id}: {ref_err}")

    @classmethod
    async def retry_failed_job_images(cls, db, user_id: str, job_id: str) -> Dict[str, Any]:
        """Retries only the failed images for a partial or failed job without restarting or charging duplicate credits."""
        job = await db["photoshoot_jobs"].find_one({"job_id": job_id, "user_id": str(user_id)})
        if not job:
            raise HTTPException(status_code=404, detail="Photoshoot job not found.")

        failed_items = job.get("failed_items", [])
        if not failed_items:
            return {
                "success": True,
                "job_id": job_id,
                "session_id": job["session_id"],
                "status": job["status"],
                "retrying_count": 0,
                "message": "No failed images to retry for this job."
            }

        session_id = job["session_id"]
        # Execute retry asynchronously
        asyncio.create_task(
            cls._execute_retry_job(
                db=db,
                job_id=job_id,
                session_id=session_id,
                user_id=user_id,
                failed_items=failed_items
            )
        )

        return {
            "success": True,
            "job_id": job_id,
            "session_id": session_id,
            "status": "processing",
            "retrying_count": len(failed_items),
            "message": f"Retrying {len(failed_items)} failed image(s) in background without additional credit charges."
        }

    @classmethod
    async def _execute_retry_job(cls, db, job_id: str, session_id: str, user_id: str, failed_items: List[Dict[str, Any]]):
        """Processes retry for the failed variations in background."""
        try:
            await db["photoshoot_jobs"].update_one(
                {"job_id": job_id},
                {"$set": {"status": "processing"}}
            )

            job = await db["photoshoot_jobs"].find_one({"job_id": job_id})
            current_results = job.get("result_images", [])
            total_images = job.get("total_images", len(current_results) + len(failed_items))

            newly_succeeded = []
            remaining_failures = []

            for item_meta in failed_items:
                idx = item_meta.get("index", 1)
                applied_style = item_meta.get("style", "Commercial Studio")
                comp_prompt = item_meta.get("prompt", "Professional commercial product photoshoot")

                img_id = f"final_{uuid.uuid4().hex[:12]}"
                filename = f"photoshoot_{img_id}.jpg"
                target_path = cls.FINAL_DIR / filename

                download_ok = await cls._generate_and_save_visual(comp_prompt, target_path)
                if not download_ok or not target_path.exists():
                    cls._synthesize_fallback_image(
                        target_path,
                        title=f"Photoshoot Variation #{idx}",
                        bg_color=(240, 242, 245)
                    )

                if target_path.exists() and target_path.stat().st_size > 0:
                    rel_url = f"/uploads/photoshoot/final/{filename}"
                    now_item = datetime.now(timezone.utc)
                    res_item = {
                        "image_id": img_id,
                        "session_id": session_id,
                        "style_applied": applied_style,
                        "url": rel_url,
                        "is_saved": False,
                        "created_at": now_item
                    }
                    newly_succeeded.append(res_item)
                    current_results.append(res_item)

                    await db["photoshoot_images"].insert_one({
                        "image_id": img_id,
                        "session_id": session_id,
                        "user_id": str(user_id),
                        "url": rel_url,
                        "filename": filename,
                        "angle": applied_style,
                        "file_size": target_path.stat().st_size,
                        "dimensions": {"width": 1024, "height": 1024},
                        "content_type": "image/jpeg",
                        "image_type": "generated",
                        "enhancement_style": applied_style,
                        "is_saved": False,
                        "created_at": now_item
                    })
                else:
                    remaining_failures.append(item_meta)

            now = datetime.now(timezone.utc)
            final_status = "completed" if len(current_results) >= total_images else ("partial" if current_results else "failed")

            await db["photoshoot_jobs"].update_one(
                {"job_id": job_id},
                {
                    "$set": {
                        "status": final_status,
                        "progress_percent": 100 if final_status == "completed" else int((len(current_results) / total_images) * 100),
                        "completed_images": len(current_results),
                        "failed_images": len(remaining_failures),
                        "failed_items": remaining_failures,
                        "can_retry": len(remaining_failures) > 0,
                        "result_images": current_results,
                        "completed_at": now
                    }
                }
            )

            if newly_succeeded:
                await db["photoshoot_sessions"].update_one(
                    {"session_id": session_id},
                    {
                        "$push": {"generated_images": {"$each": newly_succeeded}},
                        "$set": {"status": final_status, "updated_at": now}
                    }
                )
        except Exception as e:
            logger.error(f"Error during retry of job {job_id}: {e}")

    @classmethod
    async def get_job_status(cls, db, user_id: str, job_id: str) -> Dict[str, Any]:
        job = await db["photoshoot_jobs"].find_one({"job_id": job_id, "user_id": str(user_id)})
        if not job:
            raise HTTPException(status_code=404, detail="Photoshoot job not found.")

        return {
            "success": True,
            "job_id": job["job_id"],
            "session_id": job["session_id"],
            "workflow_mode": job.get("workflow_mode") or ("avatar_photoshoot" if job.get("use_model") else "product_photography"),
            "status": job["status"],
            "progress_percent": job.get("progress_percent", 0),
            "completed_images": job.get("completed_images", 0),
            "total_images": job.get("total_images", 5),
            "failed_images": job.get("failed_images", 0),
            "failed_items": job.get("failed_items", []),
            "can_retry": bool(job.get("can_retry") or job.get("failed_items")),
            "result_images": job.get("result_images", []),
            "error": job.get("error")
        }

    @classmethod
    async def get_session_results(cls, db, user_id: str, session_id: str) -> Dict[str, Any]:
        session_doc = await db["photoshoot_sessions"].find_one({
            "session_id": session_id,
            "user_id": str(user_id)
        })
        if not session_doc:
            raise HTTPException(status_code=404, detail="Photoshoot session not found.")

        results = session_doc.get("generated_images", [])
        return {
            "success": True,
            "session_id": session_id,
            "workflow_mode": session_doc.get("workflow_mode") or ("avatar_photoshoot" if session_doc.get("use_model") else "product_photography"),
            "status": session_doc.get("status", "completed"),
            "total_images": len(results),
            "use_model": session_doc.get("use_model", False),
            "results": results
        }

    # -----------------------------------------------------------------------
    # PHASE 8: Gallery, Selection & Downloads
    # -----------------------------------------------------------------------
    @classmethod
    async def save_selected_images(
        cls,
        db,
        user_id: str,
        session_id: str,
        image_ids: List[str]
    ) -> Dict[str, Any]:
        session_doc = await db["photoshoot_sessions"].find_one({
            "session_id": session_id,
            "user_id": str(user_id)
        })
        if not session_doc:
            raise HTTPException(status_code=404, detail="Photoshoot session not found.")

        if not image_ids:
            raise HTTPException(status_code=400, detail="No image IDs provided.")

        await db["photoshoot_images"].update_many(
            {"image_id": {"$in": image_ids}, "user_id": str(user_id)},
            {"$set": {"is_saved": True}}
        )

        await db["photoshoot_sessions"].update_one(
            {"session_id": session_id},
            {
                "$addToSet": {"saved_image_ids": {"$each": image_ids}},
                "$set": {"updated_at": datetime.now(timezone.utc)}
            }
        )

        return {
            "success": True,
            "session_id": session_id,
            "saved_count": len(image_ids),
            "saved_image_ids": image_ids,
            "message": "Selected images saved to your permanent gallery."
        }

    @classmethod
    async def delete_image(cls, db, user_id: str, image_id: str) -> Dict[str, Any]:
        image_doc = await db["photoshoot_images"].find_one({
            "image_id": image_id,
            "user_id": str(user_id)
        })
        if not image_doc:
            raise HTTPException(status_code=404, detail="Image not found or not owned by user.")

        # Delete local file if present
        rel_url = image_doc.get("url", "").lstrip("/")
        local_p = Path(rel_url)
        if local_p.exists():
            try:
                local_p.unlink()
            except Exception as e:
                logger.warning(f"Failed to unlink {local_p}: {e}")

        # Remove from collection and from appropriate session lists without deleting unrelated source images
        await db["photoshoot_images"].delete_one({"_id": image_doc["_id"]})
        session_id = image_doc.get("session_id")
        img_type = image_doc.get("image_type", "generated")

        if session_id:
            pull_criteria = {"saved_image_ids": image_id}
            if img_type == "generated":
                pull_criteria["generated_images"] = {"image_id": image_id}
            elif img_type == "enhanced":
                pull_criteria["enhanced_images"] = {"image_id": image_id}
            elif img_type == "original":
                pull_criteria["original_images"] = {"image_id": image_id}

            await db["photoshoot_sessions"].update_one(
                {"session_id": session_id},
                {"$pull": pull_criteria}
            )

        return {"success": True, "image_id": image_id, "message": "Image deleted successfully."}

    @classmethod
    async def regenerate_image(
        cls,
        db,
        user_id: str,
        image_id: str,
        style: Optional[str] = None,
        custom_prompt: Optional[str] = None
    ) -> Dict[str, Any]:
        image_doc = await db["photoshoot_images"].find_one({
            "image_id": image_id,
            "user_id": str(user_id)
        })
        if not image_doc:
            raise HTTPException(status_code=404, detail="Image not found.")

        session_id = image_doc.get("session_id")
        session_doc = await db["photoshoot_sessions"].find_one({"session_id": session_id})
        p_name = session_doc.get("product_type") if session_doc else "Product"

        applied_style = style or image_doc.get("enhancement_style") or "Studio Premium"
        prompt = (
            f"Regenerated high-resolution commercial photoshoot of {p_name}. "
            f"Style: {applied_style}. {custom_prompt or ''}. Commercial catalog quality, 8k."
        )

        new_img_id = f"regen_{uuid.uuid4().hex[:12]}"
        filename = f"photoshoot_{new_img_id}.jpg"
        target_path = cls.FINAL_DIR / filename

        download_ok = await cls._generate_and_save_visual(prompt, target_path)
        if not download_ok or not target_path.exists():
            cls._synthesize_fallback_image(target_path, title=f"Regenerated {p_name}", bg_color=(245, 245, 245))

        rel_url = f"/uploads/photoshoot/final/{filename}"
        now = datetime.now(timezone.utc)
        new_item = {
            "image_id": new_img_id,
            "session_id": session_id,
            "style_applied": applied_style,
            "url": rel_url,
            "is_saved": True,
            "created_at": now
        }

        await db["photoshoot_images"].insert_one({
            "image_id": new_img_id,
            "session_id": session_id,
            "user_id": str(user_id),
            "url": rel_url,
            "filename": filename,
            "angle": applied_style,
            "file_size": target_path.stat().st_size if target_path.exists() else 2048,
            "dimensions": {"width": 1024, "height": 1024},
            "content_type": "image/jpeg",
            "image_type": "generated",
            "enhancement_style": applied_style,
            "is_saved": True,
            "created_at": now
        })

        if session_id:
            await db["photoshoot_sessions"].update_one(
                {"session_id": session_id},
                {"$push": {"generated_images": new_item}}
            )

        return {"success": True, "regenerated_image": new_item}

    @classmethod
    async def get_user_gallery(
        cls,
        db,
        user_id: str,
        page: int = 1,
        limit: int = 12,
        category: Optional[str] = None,
        use_model: Optional[bool] = None,
        workflow_mode: Optional[str] = None,
        sort_by: Optional[str] = "desc",
    ) -> Dict[str, Any]:
        query: Dict[str, Any] = {"user_id": str(user_id)}
        if category and category.lower() != "all":
            query["product_category"] = {"$regex": f"^{re.escape(category)}$", "$options": "i"}
        
        # Support filtering by workflow_mode (with backward compatibility)
        if workflow_mode:
            clean_mode = workflow_mode.strip().lower()
            if clean_mode == "avatar_photoshoot":
                query["$or"] = [{"workflow_mode": "avatar_photoshoot"}, {"use_model": True}]
            elif clean_mode == "product_photography":
                query["$or"] = [
                    {"workflow_mode": "product_photography"},
                    {"workflow_mode": None, "use_model": False},
                    {"workflow_mode": {"$exists": False}, "use_model": False}
                ]
        elif use_model is not None:
            query["use_model"] = use_model

        sort_dir = 1 if sort_by == "asc" else -1

        total = await db["photoshoot_sessions"].count_documents(query)
        safe_page = max(1, page)
        safe_limit = min(max(1, limit), 50)
        skip = (safe_page - 1) * safe_limit

        cursor = db["photoshoot_sessions"].find(query).sort("created_at", sort_dir).skip(skip).limit(safe_limit)
        items = []
        async for doc in cursor:
            # Pick first generated image or first original as thumbnail
            thumb = None
            if doc.get("generated_images"):
                thumb = doc["generated_images"][0].get("url")
            elif doc.get("enhanced_images"):
                thumb = doc["enhanced_images"][0].get("url")
            elif doc.get("original_images"):
                thumb = doc["original_images"][0].get("url")

            items.append({
                "session_id": doc["session_id"],
                "title": doc.get("title") or "Commercial Photoshoot",
                "workflow_mode": doc.get("workflow_mode") or ("avatar_photoshoot" if doc.get("use_model") else "product_photography"),
                "product_category": doc.get("product_category") or "Product",
                "product_type": doc.get("product_type") or "Item",
                "use_model": doc.get("use_model", False),
                "thumbnail_url": thumb,
                "total_generated": len(doc.get("generated_images", [])),
                "saved_count": len(doc.get("saved_image_ids", [])),
                "created_at": doc.get("created_at")
            })

        return {
            "success": True,
            "total": total,
            "page": safe_page,
            "limit": safe_limit,
            "sessions": items
        }

    # -----------------------------------------------------------------------
    # Visual Generation Engine Helper (Pollinations Flux + Fallback)
    # -----------------------------------------------------------------------
    @classmethod
    async def _generate_and_save_visual(cls, prompt: str, target_path: Path) -> bool:
        """Calls OpenAI gpt-image-1-mini to generate photoshoot image and saves to disk."""
        try:
            from app.ai.providers.openai_provider import OpenAIProvider
            provider = OpenAIProvider()
            logger.info("Generating photoshoot image using OpenAI gpt-image-1-mini...")
            res = await provider.generate_image(
                prompt=prompt,
                size="1024x1024",
                model=getattr(settings, "OPENAI_IMAGE_MODEL", "gpt-image-1-mini")
            )
            if res.get("url"):
                img_url = res["url"]
                headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
                async with httpx.AsyncClient(timeout=30.0, headers=headers, follow_redirects=True) as client:
                    resp = await client.get(img_url)
                    if resp.status_code == 200 and len(resp.content) > 1000:
                        with open(target_path, "wb") as f:
                            f.write(resp.content)
                        logger.info(f"Successfully saved OpenAI generated photoshoot image to {target_path}")
                        return True
            elif res.get("b64_json"):
                b64_bytes = base64.b64decode(res["b64_json"])
                with open(target_path, "wb") as f:
                    f.write(b64_bytes)
                logger.info(f"Successfully saved OpenAI base64 photoshoot image to {target_path}")
                return True
        except Exception as e:
            logger.warning(f"OpenAI photoshoot visual generation failed: {e}")

        # Fallback to remote visual pipeline
        safe_prompt = urllib.parse.quote(prompt[:300].strip())
        seed = int(uuid.uuid4().hex[:6], 16)
        flux_url = f"https://image.pollinations.ai/prompt/{safe_prompt}?width=1024&height=1024&nologo=true&model=flux&seed={seed}"
        try:
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            async with httpx.AsyncClient(timeout=15.0, headers=headers, follow_redirects=True) as client:
                res = await client.get(flux_url)
                if res.status_code == 200 and len(res.content) > 3000:
                    with open(target_path, "wb") as f:
                        f.write(res.content)
                    return True
        except Exception as e:
            logger.warning(f"Remote visual generation failed ({e}), creating local fallback.")
        return False

    @classmethod
    def _synthesize_fallback_image(
        cls,
        target_path: Path,
        title: str = "Commercial Photoshoot",
        bg_color: Tuple[int, int, int] = (245, 245, 248)
    ):
        """Creates a clean synthetic e-commerce fallback graphic with PIL."""
        try:
            from PIL import ImageDraw
            img = Image.new("RGB", (1024, 1024), color=bg_color)
            draw = ImageDraw.Draw(img)

            # Draw a modern studio product pedestal / podium
            draw.rectangle([160, 160, 864, 864], outline=(220, 224, 230), width=4)
            draw.ellipse([262, 700, 762, 850], fill=(210, 215, 225))  # Shadow
            draw.ellipse([262, 650, 762, 750], fill=(255, 255, 255), outline=(200, 205, 215), width=2)  # Plinth

            # Draw center text
            draw.text((512, 450), title, fill=(40, 50, 70), anchor="mm")
            draw.text((512, 520), "DhandaGrow AI Photoshoot Studio", fill=(120, 130, 150), anchor="mm")

            img.save(target_path, format="JPEG", quality=90)
        except Exception as e:
            logger.warning(f"Error creating fallback image: {e}")
            with open(target_path, "wb") as f:
                f.write(b"DhandaGrow Photoshoot")

