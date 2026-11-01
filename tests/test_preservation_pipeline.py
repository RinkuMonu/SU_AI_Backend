import pytest
import asyncio
from pathlib import Path
from PIL import Image, ImageDraw
from app.services.photoshoot_service import PhotoshootService

def create_product_image(category: str, out_path: Path):
    im = Image.new("RGBA", (512, 512), (250, 250, 250, 255))
    draw = ImageDraw.Draw(im)
    
    if category == "Clothing":
        # Mustard-yellow sleeveless dress
        draw.polygon([(200, 100), (312, 100), (360, 450), (152, 450)], fill=(225, 175, 20, 255))
        draw.pieslice([(230, 80), (282, 130)], 0, 180, fill=(250, 250, 250, 255))
    elif category == "Packaged Food":
        # Salt packaging container
        draw.rectangle([(180, 140), (332, 420)], fill=(30, 80, 180, 255))
        draw.rectangle([(200, 100), (312, 140)], fill=(220, 220, 220, 255))
        draw.text((210, 260), "PURE SALT", fill=(255, 255, 255, 255))
    elif category == "Crockery":
        # Ceramic bowl with glossy rim
        draw.ellipse([(140, 200), (372, 380)], fill=(210, 225, 235, 255), outline=(120, 150, 170, 255), width=4)
        draw.ellipse([(170, 230), (342, 350)], fill=(240, 248, 255, 255))
    elif category == "Jewellery":
        # Gold ring with gemstone setting
        draw.ellipse([(180, 180), (332, 332)], fill=None, outline=(218, 165, 32, 255), width=18)
        draw.polygon([(240, 150), (272, 150), (286, 180), (256, 210), (226, 180)], fill=(0, 206, 209, 255))
    elif category == "Cosmetics":
        # Cosmetic pump bottle
        draw.rectangle([(200, 200), (312, 420)], fill=(240, 190, 190, 255))
        draw.rectangle([(236, 150), (276, 200)], fill=(200, 200, 200, 255))
        draw.rectangle([(210, 130), (276, 150)], fill=(160, 160, 160, 255))
        draw.text((220, 300), "SERUM", fill=(80, 40, 40, 255))
    elif category == "Electronics":
        # Smartphone with screen and camera bezel
        draw.rounded_rectangle([(180, 120), (332, 420)], radius=24, fill=(35, 35, 40, 255), outline=(180, 180, 190, 255), width=3)
        draw.rounded_rectangle([(192, 140), (320, 400)], radius=12, fill=(20, 25, 35, 255))
        draw.ellipse([(246, 126), (266, 134)], fill=(80, 80, 80, 255))
    else:
        draw.rectangle([(180, 180), (332, 332)], fill=(100, 100, 100, 255))
        
    im.save(out_path, format="PNG")
    return out_path

@pytest.mark.asyncio
async def test_all_six_presets_supported():
    presets = [
        "Studio Premium",
        "Cinematic Luxury",
        "Clean E-commerce",
        "Soft Natural Lighting",
        "Editorial Product Look",
        "Premium Commercial"
    ]
    for p in presets:
        prompt_tmpl = PhotoshootService.ENHANCEMENT_PRESET_PROMPTS.get(p)
        assert prompt_tmpl is not None, f"Missing preset prompt template for {p}"
        assert "Strict product preservation" in prompt_tmpl
        assert "Do not add sleeves" in prompt_tmpl

@pytest.mark.asyncio
async def test_preset_aliases_mapping():
    aliases = {
        "studio premium": "Studio Premium",
        "cinematic luxury": "Cinematic Luxury",
        "luxury cinematic": "Cinematic Luxury",
        "clean e-commerce": "Clean E-commerce",
        "marketplace white": "Clean E-commerce",
        "soft natural lighting": "Soft Natural Lighting",
        "editorial product look": "Editorial Product Look",
        "premium commercial": "Premium Commercial",
    }
    for alias, canonical in aliases.items():
        assert PhotoshootService.ENHANCEMENT_PRESET_ALIASES.get(alias) == canonical

@pytest.mark.asyncio
async def test_prepare_image_for_editing(tmp_path):
    img_path = tmp_path / "dress.png"
    create_product_image("Clothing", img_path)
    buf = PhotoshootService._prepare_image_for_editing(img_path, target_size=(1024, 1024))
    assert buf is not None
    im = Image.open(buf)
    assert im.size == (1024, 1024)
    assert im.mode == "RGBA"

@pytest.mark.asyncio
async def test_six_categories_studio_enhancement(tmp_path):
    categories = [
        "Clothing",
        "Packaged Food",
        "Crockery",
        "Jewellery",
        "Cosmetics",
        "Electronics"
    ]
    for cat in categories:
        src = tmp_path / f"{cat.lower()}.png"
        target = tmp_path / f"{cat.lower()}_enhanced.jpg"
        create_product_image(cat, src)
        
        ok = PhotoshootService._apply_local_studio_enhancement(src, target, style="Studio Premium")
        assert ok is True
        assert target.exists()
        assert target.stat().st_size > 500
        with Image.open(target) as enh:
            assert enh.size == (1024, 1024)

@pytest.mark.asyncio
async def test_cv_metrics_computation(tmp_path):
    img1 = tmp_path / "img1.png"
    img2 = tmp_path / "img2.png"
    create_product_image("Clothing", img1)
    create_product_image("Clothing", img2)
    
    cv_res = PhotoshootService._compute_cv_metrics(img1, img2)
    assert "cv_aspect_ratio_similarity" in cv_res
    assert "cv_structural_hash_similarity" in cv_res
    assert cv_res["cv_aspect_ratio_similarity"] > 0.9
    assert cv_res["cv_structural_hash_similarity"] > 0.9

@pytest.mark.asyncio
async def test_category_acceptance_thresholds_configuration():
    expected_categories = ["clothing", "packaged food", "crockery", "jewellery", "cosmetics", "electronics", "default"]
    for cat in expected_categories:
        assert cat in PhotoshootService.CATEGORY_ACCEPTANCE_THRESHOLDS
        cfg = PhotoshootService.CATEGORY_ACCEPTANCE_THRESHOLDS[cat]
        assert "shape_and_silhouette_similarity" in cfg
        assert "composite_preservation_score" in cfg
        assert cfg["composite_preservation_score"] >= 0.80
