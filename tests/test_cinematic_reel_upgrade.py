import os
import pytest
import asyncio
from app.ai.video.composer import VideoComposer
from app.ai.prompts.reel import detect_product_domain, get_reel_script_prompt
from app.services.video_quality_validator import VideoQualityValidator
from app.schemas.reel import ReelJobStatus, ReelScene

@pytest.mark.asyncio
async def test_all_music_styles_exist_and_resolve():
    composer = VideoComposer()
    expected_styles = ["bollywood", "cinematic", "upbeat", "festive", "elegant", "energetic", "corporate", "soft"]
    
    for style in expected_styles:
        bgm = composer._get_bgm_for_style(style)
        assert bgm is not None, f"Music style '{style}' must resolve to an authentic track"
        assert os.path.exists(bgm), f"Track for '{style}' must exist on disk: {bgm}"
        assert os.path.getsize(bgm) > 100000, f"Track for '{style}' must be a full-length high-bitrate audio file"
        assert style in bgm.lower(), f"Track resolved for '{style}' should match the requested style, got {bgm}"

    # Verify 'none' returns None
    assert composer._get_bgm_for_style("none") is None
    assert composer._get_bgm_for_style("off") is None


def test_furniture_interior_domain_detection():
    # Green velvet sofa reference from user prompt
    domain1 = detect_product_domain("Green Velvet Three-Seater Sofa", "Furniture & Home", "Luxury modern living room sofa with gold brass legs")
    assert domain1 == "furniture_interior"

    domain2 = detect_product_domain("Executive Ergonomic Office Chair", "Office Furniture", "Mesh back lumbar support")
    assert domain2 == "furniture_interior"

    domain3 = detect_product_domain("Solid Teak Wood Dining Table", "Dining Room", "Handcrafted 6-seater dining table")
    assert domain3 == "furniture_interior"

    # Test prompt generation contains furniture specific directives
    prompt = get_reel_script_prompt(
        product={"name": "Green Velvet Three-Seater Sofa", "category": "Living Room Sofa", "description": "Plush emerald green velvet sofa"},
        brand={"name": "Save Dost Furnishings"},
        objective="product_showcase",
        platform="instagram_reels",
        duration=30,
        language="English",
        tone="premium"
    )
    assert "FURNITURE & INTERIOR DESIGN" in prompt
    assert "lateral dolly tracking glide" in prompt
    assert "Three-Quarter Perspective" in prompt
    assert "Macro Craftsmanship" in prompt


@pytest.mark.asyncio
async def test_macro_detail_crop_synthesis():
    composer = VideoComposer()
    # Create sample image
    from PIL import Image
    sample_img_path = "uploads/temp/test_sofa.jpg"
    os.makedirs("uploads/temp", exist_ok=True)
    img = Image.new("RGB", (800, 800), color=(18, 92, 54))  # Emerald green velvet color
    img.save(sample_img_path)

    macro_path = "uploads/temp/test_macro_out.jpg"
    res = composer._create_macro_detail_crop(sample_img_path, macro_path)
    assert os.path.exists(res)
    assert os.path.getsize(res) > 1000

    # Cleanup
    if os.path.exists(sample_img_path):
        os.remove(sample_img_path)
    if os.path.exists(macro_path):
        os.remove(macro_path)


@pytest.mark.asyncio
async def test_cinematic_camera_motion_filters():
    composer = VideoComposer()
    frames = 120
    fps = 30

    dolly = composer._get_camera_motion_filter("lateral_dolly_right", frames, fps)
    assert "zoompan" in dolly
    assert "720x1280" in dolly
    assert "x=" in dolly

    push = composer._get_camera_motion_filter("push_in", frames, fps)
    assert "zoompan" in push
    assert "min(1.04" in push

    macro = composer._get_camera_motion_filter("macro_scan", frames, fps)
    assert "zoompan" in macro
    assert "1.28" in macro

    pedestal = composer._get_camera_motion_filter("pedestal_tilt", frames, fps)
    assert "zoompan" in pedestal

    pull = composer._get_camera_motion_filter("pull_out", frames, fps)
    assert "zoompan" in pull


@pytest.mark.asyncio
async def test_video_quality_validator_with_synthetic_video():
    validator = VideoQualityValidator()
    # Verify report structure on non-existent file returns proper missing classification
    report = await validator.validate_video("uploads/reels/non_existent.mp4")
    assert report["is_valid"] is False
    assert report["classification"] == "missing_file"


def test_reel_job_status_quality_fields():
    status = ReelJobStatus(
        job_id="661e89f81a7b12001e4a1111",
        status="completed",
        progress=100,
        stage="Completed",
        video_url="/uploads/reels/sample.mp4",
        motion_classification="cinematic_multicam",
        motion_score=0.88,
        diversity_score=0.92,
        quality_report={"is_valid": True, "has_audio": True}
    )
    assert status.motion_classification == "cinematic_multicam"
    assert status.motion_score == 0.88
    assert status.diversity_score == 0.92
    assert status.quality_report["is_valid"] is True


@pytest.mark.asyncio
async def test_end_to_end_compose_reel_and_quality_validation():
    """Renders a 6-second cinematic reel with synthetic scenes and verifies motion and audio quality."""
    from PIL import Image
    test_img = "uploads/temp/e2e_test_sofa.png"
    os.makedirs("uploads/temp", exist_ok=True)
    img = Image.new("RGB", (720, 1280), color=(24, 88, 52))
    img.save(test_img)

    class MockScene:
        def __init__(self, dur, movement, text):
            self.duration_seconds = dur
            self.camera_movement = movement
            self.on_screen_text = text
            self.voiceover = ""

    class MockScript:
        def __init__(self):
            self.duration_seconds = 6
            self.scenes = [
                MockScene(3, "lateral_dolly_right", "Handcrafted Green Velvet"),
                MockScene(3, "macro_scan", "Ultra-Soft Texture")
            ]

    composer = VideoComposer()
    validator = VideoQualityValidator()

    reel_url = await composer.compose_reel(
        video_segments=[test_img],
        audio_url=None,
        script=MockScript(),
        product_name="Emerald Velvet Sofa",
        music_style="bollywood",
        voiceover_mode="none"
    )

    local_path = reel_url.lstrip("/")
    assert os.path.exists(local_path)

    report = await validator.validate_video(local_path, expected_duration=6.0)
    assert report["is_valid"] is True
    assert report["classification"] in ["cinematic_multicam", "continuous_camera_motion"]
    assert report["motion_score"] > 0.05
    assert report["has_audio"] is True
    assert report["is_vertical_9_16"] is True

    # Cleanup test files
    if os.path.exists(test_img):
        os.remove(test_img)
    if os.path.exists(local_path):
        os.remove(local_path)
