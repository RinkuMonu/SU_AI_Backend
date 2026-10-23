import os
import math
import uuid
import logging
from pathlib import Path
from typing import Optional, List, Tuple
from PIL import Image, ImageDraw, ImageFont, ImageFilter

logger = logging.getLogger(__name__)


def hex_to_rgb(hex_str: Optional[str], default: Tuple[int, int, int] = (190, 50, 255)) -> Tuple[int, int, int]:
    if not hex_str:
        return default
    s = hex_str.strip().lstrip("#")
    if len(s) == 3:
        s = "".join([c * 2 for c in s])
    if len(s) == 6:
        try:
            return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
        except ValueError:
            pass
    return default


def interpolate_color(c1: Tuple[int, int, int], c2: Tuple[int, int, int], factor: float) -> Tuple[int, int, int]:
    return (
        int(c1[0] + (c2[0] - c1[0]) * factor),
        int(c1[1] + (c2[1] - c1[1]) * factor),
        int(c1[2] + (c2[2] - c1[2]) * factor),
    )


def draw_linear_gradient(draw: ImageDraw.ImageDraw, size: Tuple[int, int], color1: Tuple[int, int, int], color2: Tuple[int, int, int]):
    w, h = size
    for y in range(h):
        factor = y / max(1, h - 1)
        r, g, b = interpolate_color(color1, color2, factor)
        draw.line([(0, y), (w, y)], fill=(r, g, b, 255))


def get_initials(name: str) -> str:
    parts = [p.strip() for p in name.split() if p.strip()]
    if not parts:
        return "B"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[1][0]).upper()


def generate_artistic_brand_logo(
    business_name: str,
    category: Optional[str] = None,
    style: Optional[str] = "minimalist_modern",
    preferred_colors: Optional[List[str]] = None,
    tagline: Optional[str] = None,
    transparent_background: bool = False,
    target_path: Optional[str] = None,
    seed: int = 42
) -> str:
    """
    Renders an ultra-high-resolution, visually stunning brand emblem/logo.
    Super-samples at 2048x2048 and downscales with Lanczos for razor-sharp vector quality.
    """
    # 1. Colors
    col1 = hex_to_rgb(preferred_colors[0] if preferred_colors and len(preferred_colors) > 0 else None, (190, 50, 255))
    col2 = hex_to_rgb(preferred_colors[1] if preferred_colors and len(preferred_colors) > 1 else None, (240, 68, 155))
    col3 = hex_to_rgb(preferred_colors[2] if preferred_colors and len(preferred_colors) > 2 else None, (252, 154, 93))

    # Canvas setup (Super-sampled 2048x2048)
    W, H = 2048, 2048
    CX, CY = W // 2, H // 2

    if transparent_background:
        canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    else:
        # Sleek dark luxury backdrop
        bg_col = (11, 14, 28, 255)
        canvas = Image.new("RGBA", (W, H), bg_col)
        bg_draw = ImageDraw.Draw(canvas)
        # Subtle radial glow from center
        glow_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        glow_draw = ImageDraw.Draw(glow_layer)
        for r in range(800, 0, -20):
            alpha = int(45 * (1 - r / 800))
            glow_draw.ellipse([CX - r, CY - r, CX + r, CY + r], fill=(col1[0], col1[1], col1[2], alpha))
        canvas = Image.alpha_composite(canvas, glow_layer)

    draw = ImageDraw.Draw(canvas)

    # 2. Geometry based on style
    style_key = (style or "minimalist_modern").lower()

    if "luxury" in style_key or "monogram" in style_key or "emblem" in style_key:
        # Concentric luxury heraldic crest with dual rings and star accents
        R = 620
        # Outer ring
        draw.ellipse([CX - R, CY - R, CX + R, CY + R], outline=col1, width=12)
        draw.ellipse([CX - (R - 28), CY - (R - 28), CX + (R - 28), CY + (R - 28)], outline=col2, width=6)
        draw.ellipse([CX - (R - 56), CY - (R - 56), CX + (R - 56), CY + (R - 56)], outline=col1, width=3)

        # Star / diamond accents around perimeter
        for deg in range(0, 360, 45):
            rad = math.radians(deg)
            sx = CX + int((R - 14) * math.cos(rad))
            sy = CY + int((R - 14) * math.sin(rad))
            draw.ellipse([sx - 10, sy - 10, sx + 10, sy + 10], fill=col3)

        # Inner diamond / crown crest
        id_r = 380
        diamond_pts = [
            (CX, CY - id_r),
            (CX + id_r, CY),
            (CX, CY + id_r),
            (CX - id_r, CY)
        ]
        draw.polygon(diamond_pts, outline=col2, width=8)

    elif "geometric" in style_key or "abstract" in style_key:
        # Dynamic interlocking isometric hexagon & triangle
        R = 640
        hex_pts = []
        for i in range(6):
            ang = math.radians(60 * i - 30)
            hex_pts.append((CX + int(R * math.cos(ang)), CY + int(R * math.sin(ang))))
        draw.polygon(hex_pts, outline=col1, width=16)

        inner_r = 440
        inner_hex = []
        for i in range(6):
            ang = math.radians(60 * i)
            inner_hex.append((CX + int(inner_r * math.cos(ang)), CY + int(inner_r * math.sin(ang))))
        draw.polygon(inner_hex, outline=col2, width=10)

        # Cross lines
        for i in range(3):
            draw.line([inner_hex[i], inner_hex[i + 3]], fill=col3, width=6)

    elif "3d" in style_key or "tech" in style_key or "futuristic" in style_key:
        # Modern 3D isometric cube / node shield
        R = 560
        # Octagon frame
        oct_pts = []
        for i in range(8):
            ang = math.radians(45 * i - 22.5)
            oct_pts.append((CX + int(R * math.cos(ang)), CY + int(R * math.sin(ang))))
        draw.polygon(oct_pts, outline=col1, width=14)

        # Circuit nodes
        for pt in oct_pts:
            draw.ellipse([pt[0] - 18, pt[1] - 18, pt[0] + 18, pt[1] + 18], fill=col2, outline=col3, width=4)

        # Inner floating isometric cube
        s = 220
        # Cube top
        top_pts = [(CX, CY - s), (CX + int(s * 1.2), CY - s // 2), (CX, CY), (CX - int(s * 1.2), CY - s // 2)]
        draw.polygon(top_pts, fill=col1, outline=col3, width=6)
        # Cube left
        left_pts = [(CX - int(s * 1.2), CY - s // 2), (CX, CY), (CX, CY + s), (CX - int(s * 1.2), CY + s // 2)]
        draw.polygon(left_pts, fill=col2, outline=col3, width=6)
        # Cube right
        right_pts = [(CX, CY), (CX + int(s * 1.2), CY - s // 2), (CX + int(s * 1.2), CY + s // 2), (CX, CY + s)]
        draw.polygon(right_pts, fill=col3, outline=col1, width=6)

    else:
        # Minimalist Modern: Clean circular badge with sleek offset rings & clean shield
        R = 600
        draw.ellipse([CX - R, CY - R, CX + R, CY + R], outline=col1, width=14)
        draw.ellipse([CX - (R - 40), CY - (R - 40), CX + (R - 40), CY + (R - 40)], outline=col2, width=6)

        # Modern minimalist horizontal cut accents
        draw.line([(CX - R - 60, CY), (CX - R + 20, CY)], fill=col3, width=10)
        draw.line([(CX + R - 20, CY), (CX + R + 60, CY)], fill=col3, width=10)

    # 3. Monogram / Business Typography
    initials = get_initials(business_name)

    # Try loading system font, else fallback to standard default
    font_large = None
    font_sub = None
    for font_path in [
        "C:\\Windows\\Fonts\\segoeui.ttf",
        "C:\\Windows\\Fonts\\arial.ttf",
        "C:\\Windows\\Fonts\\tahoma.ttf",
        "C:\\Windows\\Fonts\\calibri.ttf"
    ]:
        if os.path.exists(font_path):
            try:
                font_large = ImageFont.truetype(font_path, 340)
                font_sub = ImageFont.truetype(font_path, 80)
                break
            except Exception:
                pass

    if not font_large:
        font_large = ImageFont.load_default()
        font_sub = ImageFont.load_default()

    # Draw centered monogram initials
    bbox = draw.textbbox((0, 0), initials, font=font_large)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    tx = CX - tw // 2
    ty = CY - th // 2 - 40

    # Soft drop shadow for letters
    draw.text((tx + 6, ty + 6), initials, fill=(0, 0, 0, 180), font=font_large)
    # Gradient/metallic letter fill
    draw.text((tx, ty), initials, fill=(255, 255, 255, 255), font=font_large)

    # Bottom brand name banner
    short_name = (business_name or "BRAND").upper()[:24]
    b_bbox = draw.textbbox((0, 0), short_name, font=font_sub)
    bw = b_bbox[2] - b_bbox[0]
    bx = CX - bw // 2
    by = CY + 380

    # Draw pill behind text banner
    pill_pad_x = 40
    pill_pad_y = 18
    draw.rounded_rectangle(
        [bx - pill_pad_x, by - pill_pad_y, bx + bw + pill_pad_x, by + (b_bbox[3] - b_bbox[1]) + pill_pad_y],
        radius=30,
        fill=(18, 24, 48, 230),
        outline=col1,
        width=4
    )
    draw.text((bx, by), short_name, fill=col3, font=font_sub)

    # 4. Downsample to target 1024x1024 with Lanczos for razor-sharp vector antialiasing
    final_img = canvas.resize((1024, 1024), Image.Resampling.LANCZOS)

    # 5. Save output file
    if not target_path:
        out_dir = Path("uploads") / "brand"
        out_dir.mkdir(parents=True, exist_ok=True)
        target_path = str(out_dir / f"{uuid.uuid4().hex}.png")

    final_img.save(target_path, format="PNG", optimize=True)
    logger.info(f"Generated artistic brand logo saved to {target_path}")
    return target_path
