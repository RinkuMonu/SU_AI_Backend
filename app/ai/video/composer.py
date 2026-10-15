import os
import re
import uuid
import logging
import asyncio
import httpx
import subprocess
from typing import List, Dict, Any
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
        for candidate in ["assets/music/bgm.mp3", "assets/music/bgm.ogg"]:
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
        # Remove curly braces, backslashes, and normalize spaces
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
            "Style: TopHook, Arial, 24, &H0000FFFF, &H000000FF, &H00000000, &H90000000, 1, 0, 0, 0, 100, 100, 1, 0, 3, 5, 0, 8, 40, 40, 65, 1",
            # Center / Upper Scene Headline
            "Style: SceneTitle, Arial, 34, &H00FFFFFF, &H000000FF, &H00000000, &HB0000000, 1, 0, 0, 0, 100, 100, 1, 0, 3, 6, 0, 8, 40, 40, 135, 1",
            # Spoken Voiceover subtitle (Lower Third)
            "Style: VoiceCaption, Arial, 28, &H00FFFFFF, &H000000FF, &H00000000, &HA0000000, 1, 0, 0, 0, 100, 100, 0, 0, 3, 4, 0, 2, 40, 40, 215, 1",
            # Final Scene CTA Badge
            "Style: BottomCTA, Arial, 32, &H0000FFFF, &H000000FF, &H00000000, &HB0000000, 1, 0, 0, 0, 100, 100, 1, 0, 3, 6, 0, 2, 40, 40, 85, 1",
            "",
            "[Events]",
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        ]

        current_time = 0.0
        num_scenes = len(scenes)

        for i, scene in enumerate(scenes):
            duration = scene.duration_seconds if hasattr(scene, "duration_seconds") else scene.get("duration_seconds", 4)
            start_time = current_time
            end_time = current_time + duration

            start_str = self._format_ass_time(start_time)
            end_str = self._format_ass_time(end_time)

            # 1. Top Hook Badge (Scene 0 has hook, other scenes have thematic tags)
            if i == 0:
                badge = f"🔥 {self._clean_text(hook_text)[:30].upper()}" if hook_text else "🔥 TRENDING NOW"
                ass_lines.append(f"Dialogue: 0,{start_str},{end_str},TopHook,,0,0,0,,{badge}")
            elif i == 1:
                ass_lines.append(f"Dialogue: 0,{start_str},{end_str},TopHook,,0,0,0,,⚡ PREMIUM QUALITY")
            elif i == 2:
                ass_lines.append(f"Dialogue: 0,{start_str},{end_str},TopHook,,0,0,0,,✨ SIGNATURE STYLE")
            elif i >= 3:
                ass_lines.append(f"Dialogue: 0,{start_str},{end_str},TopHook,,0,0,0,,💥 LIMITED EDITION")

            # 2. Scene Title / Feature Text
            raw_title = scene.on_screen_text if hasattr(scene, "on_screen_text") else scene.get("on_screen_text", "")
            if not raw_title and hasattr(scene, "visual"):
                raw_title = scene.visual
            if raw_title:
                wrapped_title = self._wrap_text(raw_title, max_chars=28)
                ass_lines.append(f"Dialogue: 1,{start_str},{end_str},SceneTitle,,0,0,0,,{wrapped_title}")

            # 3. Voiceover Caption in lower-third
            raw_voice = scene.voiceover if hasattr(scene, "voiceover") else scene.get("voiceover", "")
            if raw_voice:
                wrapped_voice = self._wrap_text(raw_voice, max_chars=36)
                ass_lines.append(f"Dialogue: 2,{start_str},{end_str},VoiceCaption,,0,0,0,,{wrapped_voice}")

            # 4. Final Scene CTA
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

    def _find_fallback_image(self) -> str:
        for f in os.listdir("uploads"):
            if f.endswith(".jpg"):
                candidate = os.path.join("uploads", f)
                if os.path.exists(candidate) and os.path.getsize(candidate) > 2000:
                    return candidate
        return None

    async def _resolve_image_path(self, image_url_or_path: str, temp_prefix: str) -> str:
        if not image_url_or_path:
            return self._find_fallback_image()
        if image_url_or_path.startswith("http"):
            local_path = os.path.join(self.temp_dir, f"{temp_prefix}.jpg")
            ok = await self._download_file(image_url_or_path, local_path)
            if ok and os.path.exists(local_path):
                return local_path
            # If download failed, fallback
            return self._find_fallback_image()
        # Relative or local path
        local_path = image_url_or_path.lstrip("/")
        if os.path.exists(local_path):
            return local_path
        # Search uploads directory
        base_name = os.path.basename(image_url_or_path)
        candidate = os.path.join("uploads", base_name)
        if os.path.exists(candidate):
            return candidate
        return self._find_fallback_image()

    async def compose_reel(
        self,
        video_segments: List[str],
        audio_url: str,
        brand_colors: Dict[str, str] = None,
        captions: str = None,
        logo_url: str = None,
        script: Any = None
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
            # Fallback scenes if no script provided
            class DummyScene:
                def __init__(self, dur):
                    self.duration_seconds = dur
                    self.on_screen_text = "Featured Collection"
                    self.voiceover = ""
                    self.visual = "Product Showcase"
            total_dur = getattr(script, "duration_seconds", 15) if script else 15
            scenes = [DummyScene(max(3, total_dur // max(1, len(video_segments)))) for _ in range(max(1, len(video_segments)))]

        # Motions to cycle through for dynamic camera feel
        motions = [
            "min(zoom+0.0016,1.18)",                 # Scene 0: Smooth Zoom In (Hero Hook)
            "max(1.18-0.0014*on,1.03)",              # Scene 1: Smooth Zoom Out (Detail reveal)
            "min(zoom+0.0015,1.18)",                 # Scene 2: Dynamic Zoom
            "max(1.16-0.0013*on,1.02)",              # Scene 3: Floating Zoom Out
            "min(zoom+0.0018,1.20)",                 # Scene 4: Punchy Zoom In (Final CTA)
        ]

        scene_video_files = []
        total_duration = 0.0

        for i, sc in enumerate(scenes):
            seg_img_raw = video_segments[i] if i < len(video_segments) else video_segments[0]
            local_img_path = await self._resolve_image_path(seg_img_raw, f"{job_id}_img_{i}")
            if not local_img_path or not os.path.exists(local_img_path):
                # Fallback to first image
                local_img_path = await self._resolve_image_path(video_segments[0], f"{job_id}_img_0")

            duration = getattr(sc, "duration_seconds", 4) if hasattr(sc, "duration_seconds") else sc.get("duration_seconds", 4)
            total_duration += duration
            frames = int(duration * fps)
            motion_expr = motions[i % len(motions)]

            scene_out_path = os.path.join(self.temp_dir, f"{job_id}_scene_{i}.mp4")
            scene_video_files.append(scene_out_path)

            # High-production 9:16 layout:
            # 1. Background: Scaled to 720x1280 (filling screen), heavy Gaussian/box blur, dimmed for contrast
            # 2. Foreground: Scaled edge-to-edge (640x800) with dynamic Ken Burns zoom/pan camera motion
            # 3. Centered overlay with seamless contrast, enforcing SAR=1 to prevent concat mismatch
            vf = (
                "[0:v]scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280,setsar=1,boxblur=25:5,eq=brightness=-0.12[bg];"
                f"[0:v]scale=1000:1200:force_original_aspect_ratio=increase,crop=640:800,setsar=1,zoompan=z='{motion_expr}':d={frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=640x800:fps={fps}[fg];"
                "[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1[v]"
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

        # Generate Instagram-styled ASS subtitles
        ass_path = os.path.join(self.temp_dir, f"{job_id}.ass")
        self._generate_ass(script, ass_path, brand_colors)

        # Build final stitching command
        out_filename = f"{job_id}.mp4"
        output_path = os.path.join(self.output_dir, out_filename)

        inputs = []
        for p in scene_video_files:
            inputs.extend(["-i", p])

        # Voiceover audio
        local_audio = None
        if audio_url:
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
        has_bgm = self.bgm_path is not None and os.path.exists(self.bgm_path)
        if has_bgm:
            inputs.extend(["-stream_loop", "-1", "-i", self.bgm_path])
            bgm_input_idx = voice_input_idx + 1

        # Use relative path for subtitles filter to avoid Windows drive colon escaping issues
        rel_ass_path = ass_path.replace("\\", "/")
        n_scenes = len(scene_video_files)
        sar_normalizers = ";".join([f"[{j}:v]setsar=1[v{j}]" for j in range(n_scenes)])
        concat_inputs = "".join([f"[v{j}]" for j in range(n_scenes)])
        concat_v = f"{sar_normalizers};{concat_inputs}concat=n={n_scenes}:v=1:a=0[rawv];[rawv]subtitles={rel_ass_path}[v]"

        if has_bgm:
            filter_complex = f"{concat_v};[{voice_input_idx}:a]volume=1.15[voice];[{bgm_input_idx}:a]volume=0.18[bgm];[voice][bgm]amix=inputs=2:duration=first:dropout_transition=2[a]"
        else:
            filter_complex = f"{concat_v};[{voice_input_idx}:a]volume=1.0[a]"

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
            "-b:v", "2800k",
            "-maxrate", "3500k",
            "-bufsize", "5000k",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "192k",
            output_path
        ]

        def run_final_render():
            logger.info(f"Rendering final Reel: {' '.join(cmd_final)}")
            return subprocess.run(cmd_final, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        final_proc = await asyncio.to_thread(run_final_render)
        if final_proc.returncode != 0:
            err = final_proc.stderr.decode("utf-8", errors="ignore")
            logger.error(f"FFmpeg final composition failed: {err}")
            raise Exception("Failed to compose final reel video")

        # Clean up temporary scene mp4 files asynchronously
        for sc_file in scene_video_files:
            try:
                if os.path.exists(sc_file):
                    os.remove(sc_file)
            except Exception:
                pass

        logger.info(f"Reel successfully created: /{self.output_dir}/{out_filename}")
        return f"/{self.output_dir}/{out_filename}"
