import os
import re
import uuid
import logging
import asyncio
import httpx
import subprocess
from typing import List, Dict, Any, Optional
from PIL import Image, ImageEnhance

from app.core.config import settings

try:
    import imageio_ffmpeg
    HAS_FFMPEG = True
except ImportError:
    HAS_FFMPEG = False

logger = logging.getLogger(__name__)


class VideoComposer:
    def __init__(self):
        self.output_dir = "uploads/reels"
        self.temp_dir = "uploads/temp"
        os.makedirs(self.output_dir, exist_ok=True)
        os.makedirs(self.temp_dir, exist_ok=True)
        
        # Check available BGM tracks
        self.bgm_path = None
        for candidate in ["assets/music/cinematic.mp3", "assets/music/bgm.mp3", "assets/music/bgm.ogg"]:
            if os.path.exists(candidate) and os.path.getsize(candidate) > 10000:
                self.bgm_path = candidate
                break

    def _format_ass_time(self, seconds: float) -> str:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        cs = int(round((seconds - int(seconds)) * 100))
        if cs >= 100:
            cs = 99
        return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

    def _clean_text(self, text: str) -> str:
        if not text:
            return ""
        cleaned = text.replace("{", "").replace("}", "").replace("\\", " ")
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned

    def _wrap_text(self, text: str, max_chars: int = 32) -> str:
        words = self._clean_text(text).split()
        lines = []
        cur_line = []
        cur_len = 0
        for w in words:
            if cur_len + len(w) + 1 > max_chars and cur_line:
                lines.append(" ".join(cur_line))
                cur_line = [w]
                cur_len = len(w)
            else:
                cur_line.append(w)
                cur_len += len(w) + 1
        if cur_line:
            lines.append(" ".join(cur_line))
        return "\\N".join(lines)

    def _generate_ass(self, script: Any, output_path: str, brand_colors: Dict[str, str] = None) -> str:
        scenes = script.scenes if hasattr(script, "scenes") else script.get("scenes", [])
        total_duration = script.duration_seconds if hasattr(script, "duration_seconds") else script.get("duration_seconds", 15)
        hook_text = getattr(script, "hook", "") or "🔥 TRENDING NOW"
        cta_text = getattr(script, "cta", "") or "👉 TAP LINK IN BIO TO SHOP"

        ass_lines = [
            "[Script Info]",
            "ScriptType: v4.00+",
            "PlayResX: 720",
            "PlayResY: 1280",
            "",
            "[V4+ Styles]",
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
            # Top badge (Hook / Brand Badge)
            "Style: TopHook, Arial, 24, &H0000FFFF, &H000000FF, &H00000000, &H90000000, 1, 0, 0, 0, 100, 100, 1, 0, 3, 5, 0, 8, 40, 40, 100, 1",
            # Center / Upper Scene Headline
            "Style: SceneTitle, Arial, 32, &H00FFFFFF, &H000000FF, &H00000000, &HB0000000, 1, 0, 0, 0, 100, 100, 1, 0, 3, 6, 0, 8, 40, 40, 180, 1",
            # Spoken Voiceover subtitle (Elevated to MarginV=340 to stay ABOVE Instagram UI elements)
            "Style: VoiceCaption, Arial, 26, &H00FFFFFF, &H000000FF, &H00000000, &HB0000000, 1, 0, 0, 0, 100, 100, 0, 0, 3, 4, 0, 2, 40, 40, 340, 1",
            # Final Scene CTA Badge
            "Style: BottomCTA, Arial, 30, &H0000FFFF, &H000000FF, &H00000000, &HB0000000, 1, 0, 0, 0, 100, 100, 1, 0, 3, 6, 0, 2, 40, 40, 280, 1",
            "",
            "[Events]",
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        ]

        current_time = 0.0
        num_scenes = len(scenes)

        for i, scene in enumerate(scenes):
            duration = scene.get("duration_seconds", 4) if isinstance(scene, dict) else getattr(scene, "duration_seconds", 4)
            start_time = current_time
            end_time = current_time + duration

            start_str = self._format_ass_time(start_time)
            end_str = self._format_ass_time(end_time)

            if i == 0:
                badge = f"🔥 {self._clean_text(hook_text)[:30].upper()}" if hook_text else "🔥 TRENDING NOW"
                ass_lines.append(f"Dialogue: 0,{start_str},{end_str},TopHook,,0,0,0,,{badge}")
            elif i == 1:
                ass_lines.append(f"Dialogue: 0,{start_str},{end_str},TopHook,,0,0,0,,⚡ PREMIUM QUALITY")
            elif i == 2:
                ass_lines.append(f"Dialogue: 0,{start_str},{end_str},TopHook,,0,0,0,,✨ SIGNATURE STYLE")
            elif i >= 3:
                ass_lines.append(f"Dialogue: 0,{start_str},{end_str},TopHook,,0,0,0,,💥 LIMITED EDITION")

            raw_title = scene.get("on_screen_text", "") if isinstance(scene, dict) else getattr(scene, "on_screen_text", "")
            if not raw_title:
                raw_title = scene.get("visual", "") if isinstance(scene, dict) else getattr(scene, "visual", "")
            if raw_title:
                wrapped_title = self._wrap_text(raw_title, max_chars=28)
                ass_lines.append(f"Dialogue: 1,{start_str},{end_str},SceneTitle,,0,0,0,,{wrapped_title}")

            raw_voice = scene.get("voiceover", "") if isinstance(scene, dict) else getattr(scene, "voiceover", "")
            if raw_voice:
                wrapped_voice = self._wrap_text(raw_voice, max_chars=36)
                ass_lines.append(f"Dialogue: 2,{start_str},{end_str},VoiceCaption,,0,0,0,,{wrapped_voice}")

            if i == num_scenes - 1:
                cta_badge = f"👉 {self._clean_text(cta_text)[:36].upper()}"
                ass_lines.append(f"Dialogue: 3,{start_str},{end_str},BottomCTA,,0,0,0,,{cta_badge}")

            current_time += duration

        with open(output_path, "w", encoding="utf-8") as f:
            f.write("\n".join(ass_lines))

        return output_path

    async def _download_file(self, url: str, path: str) -> bool:
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                res = await client.get(url, follow_redirects=True)
                if res.status_code == 200 and len(res.content) > 1000:
                    with open(path, "wb") as f:
                        f.write(res.content)
                    return True
                else:
                    logger.warning(f"Image download returned status {res.status_code} for {url}")
        except Exception as e:
            logger.warning(f"Failed to download image {url}: {e}")
        return False

    def _find_fallback_image(self, fallback_name: str = "general") -> str:
        from app.ai.image.generator import CURATED_CATEGORY_IMAGES, ImageGenerator
        cat = ImageGenerator()._detect_category(fallback_name)
        curated_list = CURATED_CATEGORY_IMAGES.get(cat, CURATED_CATEGORY_IMAGES["general"])
        
        # 1. First prioritize valid local files
        for item in curated_list:
            clean = item.lstrip("/\\")
            if os.path.exists(clean) and os.path.getsize(clean) > 5000:
                return clean
            if os.path.exists(item) and os.path.getsize(item) > 5000:
                return item

        # 2. Check if cached downloaded fallback exists
        local_target = os.path.join(self.temp_dir, f"curated_fb_{cat}.jpg")
        if os.path.exists(local_target) and os.path.getsize(local_target) > 5000:
            return local_target

        # 3. Download from remote URL if needed
        for item in curated_list:
            if item.startswith("http"):
                try:
                    import urllib.request
                    req = urllib.request.Request(item, headers={"User-Agent": "Mozilla/5.0"})
                    with urllib.request.urlopen(req, timeout=12) as r:
                        content = r.read()
                        if len(content) > 5000:
                            with open(local_target, "wb") as f:
                                f.write(content)
                            return local_target
                except Exception as e:
                    logger.warning(f"Could not download fallback image: {e}")
                    continue
        return None

    async def _resolve_image_path(self, image_url_or_path: str, temp_prefix: str, product_name: str = "general") -> str:
        if not image_url_or_path:
            return self._find_fallback_image(product_name)
        
        # 1. Check if URL references local uploads or media folder
        if "/uploads/" in image_url_or_path:
            clean_sub = "uploads/" + image_url_or_path.split("/uploads/", 1)[1]
            if os.path.exists(clean_sub):
                return clean_sub
        if "/media/" in image_url_or_path:
            clean_sub = "media/" + image_url_or_path.split("/media/", 1)[1]
            if os.path.exists(clean_sub):
                return clean_sub

        # 2. Check if local file exists directly
        clean_path = image_url_or_path.lstrip("/\\")
        if os.path.exists(clean_path):
            return clean_path
        if os.path.exists(image_url_or_path):
            return image_url_or_path

        if image_url_or_path.startswith("http"):
            ext = ".mp4" if ".mp4" in image_url_or_path.lower() else ".jpg"
            local_path = os.path.join(self.temp_dir, f"{temp_prefix}{ext}")
            ok = await self._download_file(image_url_or_path, local_path)
            if ok and os.path.exists(local_path):
                return local_path
            return self._find_fallback_image(product_name)

        base_name = os.path.basename(image_url_or_path)
        for d in ["media/videos", "media", "uploads/reels", "uploads/enhanced", "uploads/products", "uploads"]:
            cand = os.path.join(d, base_name)
            if os.path.exists(cand):
                return cand

        return self._find_fallback_image(product_name)

    def _create_macro_detail_crop(self, src_img_path: str, target_path: str) -> str:
        """
        Extracts a high-resolution craftsmanship macro detail crop from the authentic product image.
        Focuses on the central material texture with enhanced micro-contrast.
        """
        try:
            with Image.open(src_img_path) as img:
                img = img.convert("RGB")
                w, h = img.size
                # Crop center 55%
                left = int(w * 0.22)
                top = int(h * 0.25)
                right = int(w * 0.78)
                bottom = int(h * 0.80)
                cropped = img.crop((left, top, right, bottom))
                
                # Enhance micro-contrast for authentic texture presentation
                enhancer = ImageEnhance.Contrast(cropped)
                enhanced = enhancer.enhance(1.15)
                enhancer_sharp = ImageEnhance.Sharpness(enhanced)
                macro_img = enhancer_sharp.enhance(1.25)
                
                macro_img.save(target_path, format="JPEG", quality=95)
                return target_path
        except Exception as e:
            logger.warning(f"Failed to create macro detail crop: {e}")
            return src_img_path

    def _get_bgm_for_style(self, style: Optional[str] = None) -> Optional[str]:
        if not style or style.lower() in ["none", "off", "false"]:
            return None
        st = style.lower().strip()
        candidates = [
            f"assets/music/{st}.mp3",
            f"assets/music/{st}.ogg",
            f"uploads/audio/bgm/{st}.mp3",
            "assets/music/cinematic.mp3",
            "assets/music/bgm.mp3",
            "assets/music/bgm.ogg"
        ]
        for c in candidates:
            if os.path.exists(c) and os.path.getsize(c) > 5000:
                logger.info(f"Resolved background music track for '{style}': {c}")
                return c
        return self.bgm_path

    def _get_camera_motion_filter(self, motion_type: str, frames: int, fps: int = 30) -> str:
        """
        Generates genuine cinematic camera motions in 9:16 vertical orientation:
        1. lateral_dolly_right: Smooth horizontal tracking pan right
        2. lateral_dolly_left: Smooth horizontal tracking pan left
        3. push_in: Controlled cinematic push towards hero focal center
        4. macro_scan: Diagonal craftsmanship glide across texture
        5. pedestal_tilt: Low-angle crane pedestal rising from base to top
        6. pull_out: Smooth pull-back reveal framing the Call to Action
        7. arc_glide: Curved orbital gimbal glide
        """
        m = (motion_type or "").lower().replace("-", "_").replace(" ", "_")

        if "push" in m or "dolly_in" in m or "zoom_in" in m:
            # Cinematic Push-In (Smooth sinusoidal deceleration towards product center)
            return f"zoompan=z='min(1.04+0.18*(sin(PI/2*on/{frames})),1.22)':x='(iw-iw/zoom)*0.50':y='(ih-ih/zoom)*0.42':d={frames}:s=720x1280:fps={fps}"

        elif "left" in m or "dolly_left" in m or "pan_left" in m:
            # Lateral Dolly Left
            return f"zoompan=z='1.14':x='(iw-iw/zoom)*(0.85-0.70*(sin(PI/2*on/{frames})))':y='(ih-ih/zoom)*0.45':d={frames}:s=720x1280:fps={fps}"

        elif "macro" in m or "detail" in m or "texture" in m:
            # Macro Craftsmanship Diagonal Drift
            return f"zoompan=z='1.28':x='(iw-iw/zoom)*(0.20+0.55*(on/{frames}))':y='(ih-ih/zoom)*(0.30+0.35*(on/{frames}))':d={frames}:s=720x1280:fps={fps}"

        elif "pedestal" in m or "tilt" in m or "crane" in m or "low_angle" in m or "upward" in m:
            # Low-angle Pedestal Crane Reveal (rising from bottom to top)
            return f"zoompan=z='1.12':x='(iw-iw/zoom)*0.50':y='(ih-ih/zoom)*(0.85-0.70*(sin(PI/2*on/{frames})))':d={frames}:s=720x1280:fps={fps}"

        elif "pull" in m or "pull_out" in m or "dolly_out" in m or "reveal" in m:
            # Smooth Pull-Out Reveal
            return f"zoompan=z='max(1.20-0.14*(sin(PI/2*on/{frames})),1.04)':x='(iw-iw/zoom)*0.50':y='(ih-ih/zoom)*0.40':d={frames}:s=720x1280:fps={fps}"

        elif "orbit" in m or "arc" in m or "gimbal" in m:
            # Orbital Gimbal Arc
            return f"zoompan=z='1.10+0.06*sin(PI*on/{frames})':x='(iw-iw/zoom)*(0.5+0.35*cos(PI*on/{frames}))':y='(ih-ih/zoom)*(0.45+0.25*sin(PI*on/{frames}))':d={frames}:s=720x1280:fps={fps}"

        else:
            # Default: Lateral Dolly Right (Smooth horizontal tracking glide)
            return f"zoompan=z='1.14':x='(iw-iw/zoom)*(0.15+0.70*(sin(PI/2*on/{frames})))':y='(ih-ih/zoom)*0.45':d={frames}:s=720x1280:fps={fps}"

    async def compose_reel(
        self,
        video_segments: List[str],
        audio_url: str = None,
        brand_colors: Dict[str, str] = None,
        captions: str = None,
        logo_url: str = None,
        script: Any = None,
        product_name: str = "product",
        music_style: str = "cinematic",
        captions_enabled: bool = True,
        voiceover_mode: str = "ai",
        **kwargs
    ) -> str:
        if not HAS_FFMPEG:
            logger.error("imageio-ffmpeg is not installed.")
            raise Exception("FFmpeg not available for composition")

        if not video_segments or not video_segments[0]:
            raise Exception("No visual assets provided for composition")

        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        job_id = str(uuid.uuid4())
        fps = 30

        scenes = []
        if script and hasattr(script, "scenes") and script.scenes:
            scenes = script.scenes
        elif script and isinstance(script, dict) and script.get("scenes"):
            scenes = script["scenes"]
        else:
            class DummyScene:
                def __init__(self, dur, movement):
                    self.duration_seconds = dur
                    self.on_screen_text = "Featured Collection"
                    self.voiceover = ""
                    self.visual = "Product Showcase"
                    self.camera_movement = movement
            total_dur = getattr(script, "duration_seconds", 15) if script else 15
            movements = ["lateral_dolly_right", "push_in", "macro_scan", "pull_out"]
            scenes = [DummyScene(max(3, total_dur // 4), movements[i % 4]) for i in range(4)]

        # Ordered sequence of cinematic camera motions across scenes
        default_motions = [
            "lateral_dolly_right",   # Scene 0: Wide Hero Establishing Track
            "push_in",               # Scene 1: 3/4 Perspective Controlled Push
            "macro_scan",            # Scene 2: Craftsmanship & Texture Macro Glide
            "pull_out",              # Scene 3: Hero Outro Pull-Back for CTA
            "pedestal_tilt",         # Scene 4+: Low-Angle Pedestal Crane
            "arc_glide"              # Scene 5+: Gimbal Orbit
        ]

        scene_video_files = []
        total_duration = 0.0

        for i, sc in enumerate(scenes):
            seg_img_raw = video_segments[i] if i < len(video_segments) else video_segments[0]
            local_img_path = await self._resolve_image_path(seg_img_raw, f"{job_id}_img_{i}", product_name=product_name)
            if not local_img_path or not os.path.exists(local_img_path):
                local_img_path = await self._resolve_image_path(video_segments[0], f"{job_id}_img_0", product_name=product_name)

            duration = sc.get("duration_seconds", 4) if isinstance(sc, dict) else getattr(sc, "duration_seconds", 4)
            total_duration += duration
            frames = int(duration * fps)

            # Determine motion for this scene
            sc_motion = sc.get("camera_movement", None) if isinstance(sc, dict) else getattr(sc, "camera_movement", None)
            if not sc_motion or sc_motion.strip().lower() in ["none", "static"]:
                sc_motion = default_motions[i % len(default_motions)]

            # If Scene 2 represents macro/detail and we only have 1 input image, synthesize macro detail crop
            if (i == 2 or "macro" in sc_motion or "texture" in sc_motion) and len(set(video_segments)) <= 1:
                macro_crop_path = os.path.join(self.temp_dir, f"{job_id}_macro_crop_{i}.jpg")
                local_img_path = self._create_macro_detail_crop(local_img_path, macro_crop_path)
                sc_motion = "macro_scan"

            camera_filter = self._get_camera_motion_filter(sc_motion, frames, fps)

            scene_out_path = os.path.join(self.temp_dir, f"{job_id}_scene_{i}.mp4")
            scene_video_files.append(scene_out_path)

            is_video = local_img_path.lower().endswith((".mp4", ".mov", ".webm", ".mkv"))
            fade_in_d = min(0.35, duration * 0.15)
            fade_out_st = max(0.0, duration - fade_in_d)

            if is_video:
                # Video input: 9:16 vertical scale, color grade & boundary crossfade
                vf = (
                    "[0:v]scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280,setsar=1,"
                    "eq=contrast=1.06:brightness=0.01:saturation=1.08,unsharp=5:5:0.6:5:5:0.0,vignette=PI/4,"
                    f"fade=t=in:st=0:d={fade_in_d},fade=t=out:st={fade_out_st}:d={fade_in_d}[v]"
                )
                cmd_scene = [
                    ffmpeg_exe, "-y",
                    "-i", local_img_path,
                    "-filter_complex", vf,
                    "-map", "[v]",
                    "-t", str(duration),
                    "-r", str(fps),
                    "-c:v", "libx264",
                    "-preset", "veryfast",
                    "-pix_fmt", "yuv420p",
                    scene_out_path
                ]
            else:
                # Still image input: Full-bleed 9:16 vertical canvas with high-res subpixel camera motion
                # Buffer image to 1440x2560 for smooth camera tracking without pixelation
                vf = (
                    "[0:v]scale=1440:2560:force_original_aspect_ratio=increase,crop=1440:2560,setsar=1[buf];"
                    f"[buf]{camera_filter}[mot];"
                    "[mot]eq=contrast=1.06:brightness=0.01:saturation=1.08,unsharp=5:5:0.6:5:5:0.0,vignette=PI/4,"
                    f"fade=t=in:st=0:d={fade_in_d},fade=t=out:st={fade_out_st}:d={fade_in_d},setsar=1[v]"
                )
                cmd_scene = [
                    ffmpeg_exe, "-y",
                    "-loop", "1",
                    "-i", local_img_path,
                    "-filter_complex", vf,
                    "-map", "[v]",
                    "-t", str(duration),
                    "-r", str(fps),
                    "-c:v", "libx264",
                    "-preset", "veryfast",
                    "-pix_fmt", "yuv420p",
                    scene_out_path
                ]

            def run_scene_render(cmd=cmd_scene):
                return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

            proc = await asyncio.to_thread(run_scene_render)
            if proc.returncode != 0:
                logger.error(f"FFmpeg scene {i} failed: {proc.stderr.decode('utf-8', errors='ignore')}")
                raise Exception(f"Failed to compose reel scene {i}")

        # Subtitles generation if captions are enabled
        ass_path = None
        if captions_enabled and script:
            ass_path = os.path.join(self.temp_dir, f"{job_id}.ass")
            self._generate_ass(script, ass_path, brand_colors)

        out_filename = f"{job_id}.mp4"
        output_path = os.path.join(self.output_dir, out_filename)

        inputs = []
        for p in scene_video_files:
            inputs.extend(["-i", p])

        # Voiceover audio
        local_audio = None
        if audio_url and voiceover_mode != "none":
            local_audio = audio_url.lstrip("/")
            if not os.path.exists(local_audio):
                local_audio = None

        has_voice = local_audio is not None and os.path.exists(local_audio)
        if has_voice:
            inputs.extend(["-i", local_audio])
            voice_input_idx = len(scene_video_files)
        else:
            inputs.extend(["-f", "lavfi", "-t", str(total_duration), "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"])
            voice_input_idx = len(scene_video_files)

        # Background music
        selected_bgm = self._get_bgm_for_style(music_style)
        has_bgm = selected_bgm is not None and os.path.exists(selected_bgm)
        if has_bgm:
            inputs.extend(["-stream_loop", "-1", "-i", selected_bgm])
            bgm_input_idx = voice_input_idx + 1

        # Video concatenation and audio mixing
        n_scenes = len(scene_video_files)
        sar_normalizers = ";".join([f"[{j}:v]setsar=1[v{j}]" for j in range(n_scenes)])
        concat_inputs = "".join([f"[v{j}]" for j in range(n_scenes)])
        concat_v = f"{sar_normalizers};{concat_inputs}concat=n={n_scenes}:v=1:a=0[raw_v]"

        # Overlay subtitles if enabled
        if ass_path and os.path.exists(ass_path):
            escaped_ass = ass_path.replace("\\", "/").replace(":", "\\:")
            video_filter = f"{concat_v};[raw_v]subtitles='{escaped_ass}':charenc=UTF-8[v]"
        else:
            video_filter = f"{concat_v};[raw_v]copy[v]"

        # Dynamic Audio Ducking: Voiceover ducks background music smoothly by -14dB
        if has_bgm and has_voice:
            # Music ducks under voiceover using sidechaincompress
            audio_filter = (
                f"[{voice_input_idx}:a]asplit=2[v_audio][v_ctrl];"
                f"[{bgm_input_idx}:a]volume=0.35[bgm_pre];"
                f"[bgm_pre][v_ctrl]sidechaincompress=threshold=0.03:ratio=5:attack=25:release=400:makeup=1.0[bgm_ducked];"
                f"[v_audio]volume=1.8[v_out];"
                f"[v_out][bgm_ducked]amix=inputs=2:duration=first:dropout_transition=2[a]"
            )
        elif has_bgm and not has_voice:
            # Music only (Voiceover disabled) - full studio volume with fade in/out
            audio_filter = (
                f"[{bgm_input_idx}:a]volume=0.90,"
                f"afade=t=in:ss=0:d=0.8,afade=t=out:st={max(0, total_duration - 1.2)}:d=1.2[a]"
            )
        else:
            # Voiceover only or silent track
            audio_filter = f"[{voice_input_idx}:a]volume=1.5[a]"

        filter_complex = f"{video_filter};{audio_filter}"

        cmd_final = [
            ffmpeg_exe, "-y",
            *inputs,
            "-filter_complex", filter_complex,
            "-map", "[v]",
            "-map", "[a]",
            "-t", str(total_duration),
            "-r", str(fps),
            "-c:v", "libx264",
            "-preset", "fast",
            "-b:v", "3200k",
            "-maxrate", "4200k",
            "-bufsize", "6000k",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "192k",
            output_path
        ]

        def run_final_render():
            logger.info(f"Rendering final cinematic Reel: {' '.join(cmd_final)}")
            return subprocess.run(cmd_final, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        final_proc = await asyncio.to_thread(run_final_render)
        if final_proc.returncode != 0:
            err = final_proc.stderr.decode("utf-8", errors="ignore")
            logger.error(f"FFmpeg final composition failed: {err}")
            # If subtitles filter failed (e.g. fontconfig issue on Windows), retry without subtitles filter
            if "subtitles" in filter_complex and ("font" in err.lower() or "subtitles" in err.lower()):
                logger.warning("Retrying final composition without burned subtitles filter...")
                fallback_filter = f"{concat_v};[raw_v]copy[v];{audio_filter}"
                cmd_fallback = [
                    ffmpeg_exe, "-y",
                    *inputs,
                    "-filter_complex", fallback_filter,
                    "-map", "[v]",
                    "-map", "[a]",
                    "-t", str(total_duration),
                    "-r", str(fps),
                    "-c:v", "libx264",
                    "-preset", "fast",
                    "-b:v", "3200k",
                    "-pix_fmt", "yuv420p",
                    "-c:a", "aac",
                    "-b:a", "192k",
                    output_path
                ]
                retry_proc = await asyncio.to_thread(lambda: subprocess.run(cmd_fallback, stdout=subprocess.PIPE, stderr=subprocess.PIPE))
                if retry_proc.returncode != 0:
                    raise Exception(f"Failed to compose final reel video: {retry_proc.stderr.decode('utf-8', errors='ignore')}")
            else:
                raise Exception("Failed to compose final reel video")

        # Clean up temporary scene mp4 files asynchronously
        for sc_file in scene_video_files:
            try:
                if os.path.exists(sc_file):
                    os.remove(sc_file)
            except Exception:
                pass

        logger.info(f"Cinematic Reel successfully created: /{self.output_dir}/{out_filename}")
        return f"/{self.output_dir}/{out_filename}"
