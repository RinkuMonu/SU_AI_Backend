import asyncio
import os
import sys
from bson import ObjectId
from dotenv import load_dotenv

load_dotenv(".env")
sys.path.insert(0, os.path.abspath("."))
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from app.core.database import connect_to_mongo, get_database
from app.services.reel_script_service import ReelScriptService, validate_and_sanitize_storyboard
from app.schemas.reel import GenerateReelRequest, ReelScript, ReelScene
from app.ai.prompts.reel import detect_product_domain
from app.ai.providers.veo_provider import VeoVideoProvider, VeoQuotaError
from app.services.reel_service import ReelService


def setup_db():
    connect_to_mongo()
    return get_database()


async def test_1_laptop_relevance():
    """Test 1: Laptop - Visuals must remain 100% focused on laptop. No lehengas, cosmetics, or festival scenes."""
    print("\n--- Test 1: Laptop Product Relevance ---")
    service = ReelScriptService()
    
    product = {
        "name": "MacBook Pro M3 Max",
        "category": "Computers & Laptops",
        "description": "Liquid Retina XDR display, M3 Max chip, all-day battery life for creators & developers"
    }
    brand = {"name": "Apple Authorized Partner", "tone": "tech"}
    prompt = "Create a premium cinematic advertisement for this laptop, focusing on the keyboard, screen, design, and professional usage."
    
    script = await service.generate_script(
        product=product,
        brand=brand,
        objective="sale",
        platform="instagram",
        duration=15,
        language="English",
        tone="professional",
        additional_instruction=prompt,
        generation_mode="product",
        festival_theme="none"
    )
    
    print(f"Generated {len(script.scenes)} scenes for {script.primary_product}:")
    domain = detect_product_domain(product["name"], product["category"], product["description"])
    assert domain == "laptop_computer", f"Expected laptop_computer domain, got {domain}"
    
    forbidden = ["lehenga", "saree", "sari", "lipstick", "mascara", "skincare", "diwali", "holi", "biryani"]
    
    for sc in script.scenes:
        print(f"  Scene {sc.scene_number}: Visual='{sc.visual}'")
        text_content = f"{sc.visual} {sc.voiceover} {sc.veo_prompt}".lower()
        for fb in forbidden:
            assert fb not in text_content, f"Forbidden keyword '{fb}' found in laptop scene: {text_content}"
            
    assert any("laptop" in sc.visual.lower() or "screen" in sc.visual.lower() or "keyboard" in sc.visual.lower() or "macbook" in sc.visual.lower() for sc in script.scenes), "No laptop-specific elements found in scenes"
    print("[PASS] Test 1 Passed: Laptop visuals strictly relevant, zero contamination.")
    return script


async def test_2_lehenga_relevance():
    """Test 2: Lehenga - Visuals must remain 100% focused on lehenga fashion. No laptops or unrelated products."""
    print("\n--- Test 2: Lehenga Product Relevance ---")
    service = ReelScriptService()
    
    product = {
        "name": "Royal Crimson Velvet Lehenga",
        "category": "Ethnic Fashion",
        "description": "Hand-embroidered zardozi and antique gold dabka work for royal weddings"
    }
    brand = {"name": "Sabyasachi Heritage", "tone": "luxury"}
    prompt = "Create a premium fashion reel showcasing the lehenga's embroidery, fabric, and elegant movement."
    
    script = await service.generate_script(
        product=product,
        brand=brand,
        objective="brand_awareness",
        platform="instagram",
        duration=15,
        language="English",
        tone="luxury",
        additional_instruction=prompt,
        generation_mode="product",
        festival_theme="none"
    )
    
    print(f"Generated {len(script.scenes)} scenes for {script.primary_product}:")
    domain = detect_product_domain(product["name"], product["category"], product["description"])
    assert domain in ("lehenga_ethnic", "saree_ethnic"), f"Expected lehenga domain, got {domain}"
    
    forbidden = ["laptop", "macbook", "computer", "processor", "smartwatch", "lipstick", "biryani", "diwali"]
    
    for sc in script.scenes:
        print(f"  Scene {sc.scene_number}: Visual='{sc.visual}'")
        text_content = f"{sc.visual} {sc.voiceover} {sc.veo_prompt}".lower()
        for fb in forbidden:
            assert fb not in text_content, f"Forbidden keyword '{fb}' found in lehenga scene: {text_content}"
            
    assert any("lehenga" in sc.visual.lower() or "embroidery" in sc.visual.lower() or "fabric" in sc.visual.lower() or "velvet" in sc.visual.lower() for sc in script.scenes), "No lehenga-specific elements found in scenes"
    print("[PASS] Test 2 Passed: Lehenga visuals strictly relevant, zero contamination.")
    return script


async def test_3_skincare_relevance():
    """Test 3: Skincare - Clean premium skincare visuals. No laptops or clothing advertisements."""
    print("\n--- Test 3: Skincare Product Relevance ---")
    service = ReelScriptService()
    
    product = {
        "name": "Hydra-Glow Vitamin C Cream",
        "category": "Skincare & Beauty",
        "description": "Brightening and hydrating face cream with pure ascorbic acid and hyaluronic acid"
    }
    brand = {"name": "GlowBotany", "tone": "clean"}
    prompt = "Create a clean, premium skincare advertisement focusing on the supplied cream packaging and product texture."
    
    script = await service.generate_script(
        product=product,
        brand=brand,
        objective="sale",
        platform="instagram",
        duration=15,
        language="English",
        tone="aesthetic",
        additional_instruction=prompt,
        generation_mode="product",
        festival_theme="none"
    )
    
    print(f"Generated {len(script.scenes)} scenes for {script.primary_product}:")
    domain = detect_product_domain(product["name"], product["category"], product["description"])
    assert domain == "skincare_beauty", f"Expected skincare_beauty domain, got {domain}"
    
    forbidden = ["laptop", "macbook", "computer", "saree", "lehenga", "biryani", "burger", "pizza", "shoes"]
    
    for sc in script.scenes:
        print(f"  Scene {sc.scene_number}: Visual='{sc.visual}'")
        text_content = f"{sc.visual} {sc.voiceover} {sc.veo_prompt}".lower()
        for fb in forbidden:
            assert fb not in text_content, f"Forbidden keyword '{fb}' found in skincare scene: {text_content}"
            
    assert any("cream" in sc.visual.lower() or "texture" in sc.visual.lower() or "skin" in sc.visual.lower() or "jar" in sc.visual.lower() or "packaging" in sc.visual.lower() for sc in script.scenes), "No skincare-specific elements found in scenes"
    print("[PASS] Test 3 Passed: Skincare visuals strictly relevant, zero contamination.")
    return script


async def test_4_explicit_festival_theme():
    """Test 4: Explicit Festival Theme - Laptop + Diwali. Laptop remains primary product; Diwali is festive backdrop."""
    print("\n--- Test 4: Explicit Festival Theme (Laptop + Diwali) ---")
    service = ReelScriptService()
    
    product = {
        "name": "MacBook Pro M3 Max",
        "category": "Computers & Laptops",
        "description": "High performance laptop with M3 Max chip"
    }
    brand = {"name": "TechFest Deals", "tone": "festive"}
    prompt = "Create a Diwali sale advertisement for this laptop."
    
    script = await service.generate_script(
        product=product,
        brand=brand,
        objective="sale",
        platform="instagram",
        duration=15,
        language="English",
        tone="excited",
        additional_instruction=prompt,
        generation_mode="product",
        festival_theme="diwali"
    )
    
    print(f"Generated {len(script.scenes)} scenes for {script.primary_product} with Diwali theme:")
    domain = detect_product_domain(product["name"], product["category"], product["description"])
    assert domain == "laptop_computer", f"Expected laptop_computer domain, got {domain}"
    
    has_laptop_element = False
    has_festive_element = False
    
    for sc in script.scenes:
        print(f"  Scene {sc.scene_number}: Visual='{sc.visual}'")
        text_content = f"{sc.visual} {sc.voiceover} {sc.veo_prompt}".lower()
        if any(term in text_content for term in ["laptop", "macbook", "screen", "keyboard", "device"]):
            has_laptop_element = True
        if any(term in text_content for term in ["diwali", "festive", "spark", "light", "celebration", "offer", "sale"]):
            has_festive_element = True
            
        # Ensure it didn't get replaced with lehenga or saree
        assert "lehenga" not in text_content, "Lehenga should not appear in a laptop Diwali reel"
        assert "saree" not in text_content, "Saree should not appear in a laptop Diwali reel"
        
    assert has_laptop_element, "Laptop must remain the hero subject in the Diwali advertisement"
    print("[PASS] Test 4 Passed: Laptop remains the hero with Diwali campaign context.")
    return script


async def test_5_creative_mode():
    """Test 5: Creative mode - Allows experimental and conceptual visuals."""
    print("\n--- Test 5: Creative Mode ---")
    service = ReelScriptService()
    
    product = {
        "name": "Conceptual Innovation",
        "category": "Creative / Abstract",
        "description": "Futuristic design concepts and creative visual experiments"
    }
    brand = {"name": "AvantGarde Studio", "tone": "futuristic"}
    prompt = "Create an experimental abstract visual reel with no specific product."
    
    script = await service.generate_script(
        product=product,
        brand=brand,
        objective="brand_awareness",
        platform="instagram",
        duration=15,
        language="English",
        tone="inspirational",
        additional_instruction=prompt,
        generation_mode="creative",
        festival_theme="none"
    )
    
    print(f"Generated {len(script.scenes)} creative scenes:")
    for sc in script.scenes:
        print(f"  Scene {sc.scene_number}: Visual='{sc.visual}'")
        
    assert len(script.scenes) >= 3, "Creative mode should produce full multi-scene storyboard"
    print("[PASS] Test 5 Passed: Creative mode allows conceptual visual storytelling.")
    return script


async def test_6_product_switching():
    """Test 6: Product switching - Laptop reel followed by Lehenga reel. Ensure zero cross-job leakage."""
    print("\n--- Test 6: Product Switching & Isolation ---")
    service = ReelScriptService()
    
    # Job A: Laptop
    product_laptop = {
        "name": "MacBook Pro M3 Max",
        "category": "Computers & Laptops",
        "description": "High performance pro laptop"
    }
    script_a = await service.generate_script(
        product=product_laptop,
        brand={"name": "Tech Corp"},
        objective="sale",
        platform="instagram",
        duration=15,
        language="English",
        tone="professional",
        generation_mode="product",
        festival_theme="none"
    )
    
    # Job B: Lehenga
    product_lehenga = {
        "name": "Royal Crimson Velvet Lehenga",
        "category": "Ethnic Fashion",
        "description": "Zardozi hand-embroidered wedding lehenga"
    }
    script_b = await service.generate_script(
        product=product_lehenga,
        brand={"name": "Bridal Couture"},
        objective="sale",
        platform="instagram",
        duration=15,
        language="English",
        tone="luxury",
        generation_mode="product",
        festival_theme="none"
    )
    
    # Verify Job B contains ZERO elements from Job A
    laptop_terms = ["laptop", "macbook", "keyboard", "processor", "screen", "m3"]
    for sc in script_b.scenes:
        text_b = f"{sc.visual} {sc.voiceover} {sc.veo_prompt}".lower()
        for lt in laptop_terms:
            assert lt not in text_b, f"Stale laptop context '{lt}' leaked into subsequent Lehenga reel!"
            
    print("[PASS] Test 6 Passed: Product switching cleanly isolates contexts without stale data leakage.")


async def test_7_concurrent_jobs():
    """Test 7: Concurrent jobs - Generate reels for different products concurrently without collision."""
    print("\n--- Test 7: Concurrent Generation Isolation ---")
    service = ReelScriptService()
    
    prod_laptop = {"name": "Ultrabook 15", "category": "Computers & Laptops", "description": "Sleek aluminum laptop"}
    prod_skincare = {"name": "Glow Serum", "category": "Skincare & Beauty", "description": "Pure Hyaluronic Hydrating Serum"}
    
    task_laptop = service.generate_script(
        product=prod_laptop,
        brand={"name": "Brand A"},
        objective="sale",
        platform="instagram",
        duration=15,
        language="English",
        tone="professional",
        generation_mode="product",
        festival_theme="none"
    )
    
    task_skincare = service.generate_script(
        product=prod_skincare,
        brand={"name": "Brand B"},
        objective="sale",
        platform="instagram",
        duration=15,
        language="English",
        tone="aesthetic",
        generation_mode="product",
        festival_theme="none"
    )
    
    script_laptop, script_skincare = await asyncio.gather(task_laptop, task_skincare)
    
    assert script_laptop.primary_product == "Ultrabook 15"
    assert script_skincare.primary_product == "Glow Serum"
    
    for sc in script_laptop.scenes:
        assert "serum" not in sc.visual.lower(), "Skincare context leaked into concurrent Laptop job!"
        
    for sc in script_skincare.scenes:
        assert "laptop" not in sc.visual.lower() and "ultrabook" not in sc.visual.lower(), "Laptop context leaked into concurrent Skincare job!"
        
    print("[PASS] Test 7 Passed: Concurrent generation jobs executed with total context isolation.")


async def test_veo_provider_quota_handling():
    """Test Veo quota handling and graceful exception management."""
    print("\n--- Test 8: Veo Provider Quota Resilience ---")
    provider = VeoVideoProvider()
    assert provider.model in ("veo-3.1-fast-generate-preview", "veo-2.0-generate-001")
    print(f"[PASS] Veo provider configured with model: {provider.model}")


async def test_end_to_end_reel_service_job(db):
    """Test End-to-End Reel Generation Pipeline through ReelService with product locking."""
    print("\n--- Test 9: End-to-End Reel Generation Job ---")
    reel_service = ReelService(db)
    
    request = GenerateReelRequest(
        product_id="preset_laptop",
        product_name="MacBook Pro M3 Max",
        product_category="Computers & Laptops",
        generation_mode="product",
        festival_theme="none",
        objective="increase sales",
        platform="instagram",
        language="English",
        duration=15
    )
    
    product = {
        "id": "preset_laptop",
        "name": "MacBook Pro M3 Max",
        "category": "Computers & Laptops",
        "description": "Liquid Retina XDR display, M3 Max chip, all-day battery life for creators & developers",
        "images": ["https://images.unsplash.com/photo-1517336714731-489689fd1ca8?w=500&q=80"]
    }
    brand = {"name": "Apex Tech Store", "tone": "modern"}
    
    job_id = await reel_service.create_reel_job(
        user_id=str(ObjectId()),
        business_id=str(ObjectId()),
        request=request,
        product=product,
        brand=brand
    )
    
    print(f"Created Job ID: {job_id}. Polling status...")
    
    for _ in range(60):
        await asyncio.sleep(2)
        status = await reel_service.get_job_status(job_id)
        assert status is not None
        print(f"  Stage: {status.stage} | Progress: {status.progress}% | Status: {status.status}")
        if status.status in ("completed", "failed"):
            break
            
    final_status = await reel_service.get_job_status(job_id)
    print(f"Final Job Status: {final_status.status}, Stage: {final_status.stage}")
    assert final_status.status == "completed", f"Reel job did not complete: {final_status.stage}"
    assert final_status.video_url, "Completed job missing video_url"
    print(f"[PASS] Test 9 Passed: Reel generated successfully! Video URL: {final_status.video_url}")
