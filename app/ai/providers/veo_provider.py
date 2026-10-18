import os
import uuid
import logging
import asyncio
import tempfile
from typing import Optional, Dict, Any
import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

class VeoError(Exception):
    """Base exception for Veo video generation errors."""
    pass

class VeoQuotaError(VeoError):
    """Raised when the Gemini/Veo API key has exhausted its quota (429 RESOURCE_EXHAUSTED)."""
    pass

class VeoModelError(VeoError):
    """Raised when the specified Veo model is unavailable or not permitted."""
    pass


class VeoVideoProvider:
    """
    Google Veo Video Provider using the official Google GenAI SDK (`google.genai`).
    Supports:
    - Text-to-Video & Image-to-Video generation using configured Veo models (e.g. veo-3.1-fast-generate-preview).
    - Aspect ratio 9:16 vertical video for Instagram Reels and TikTok.
    - Reference product image conditioning.
    - Asynchronous operation initiation, progress polling, and MP4 artifact persistence.
    """

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self.api_key = api_key or settings.GEMINI_API_KEY
        self.model = model or getattr(settings, "GEMINI_VIDEO_MODEL", "veo-3.1-fast-generate-preview")
        self._client = None

    def _get_client(self):
        if self._client is None:
            if not self.api_key:
                raise VeoError("GEMINI_API_KEY is not configured in backend environment.")
            try:
                from google import genai
                self._client = genai.Client(api_key=self.api_key)
            except ImportError:
                raise VeoError("google-genai package is not installed.")
            except Exception as e:
                raise VeoError(f"Failed to initialize Google GenAI client: {e}")
        return self._client

    async def _resolve_image_to_local_file(self, image_url_or_path: str) -> Optional[str]:
        """Ensures image is accessible as a local file for the GenAI SDK."""
        if not image_url_or_path:
            return None

        # Check if already local
        if os.path.exists(image_url_or_path):
            return image_url_or_path

        # If it's a relative URL to our media directory
        if image_url_or_path.startswith("/media/") or image_url_or_path.startswith("media/"):
            clean_rel = image_url_or_path.lstrip("/")
            if os.path.exists(clean_rel):
                return clean_rel

        # If it's a remote URL, download to temporary file
        if image_url_or_path.startswith("http://") or image_url_or_path.startswith("https://"):
            try:
                ext = ".jpg"
                if ".png" in image_url_or_path.lower():
                    ext = ".png"
                elif ".webp" in image_url_or_path.lower():
                    ext = ".webp"

                tmp = tempfile.NamedTemporaryFile(suffix=ext, delete=False)
                tmp_path = tmp.name
                tmp.close()

                async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as http_client:
                    resp = await http_client.get(image_url_or_path)
                    if resp.status_code == 200:
                        with open(tmp_path, "wb") as f:
                            f.write(resp.content)
                        return tmp_path
                    else:
                        logger.warning(f"Could not download reference image from {image_url_or_path}: status {resp.status_code}")
                        if os.path.exists(tmp_path):
                            os.remove(tmp_path)
                        return None
            except Exception as e:
                logger.warning(f"Failed to fetch reference image for Veo: {e}")
                return None

        return None

    async def start_video_generation(
        self,
        prompt: str,
        image_url_or_path: Optional[str] = None,
        duration_seconds: int = 6,
        aspect_ratio: str = "9:16",
        negative_prompt: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Submits a video generation request to the configured Veo model.
        Returns:
            dict containing operation_name, model, status, and metadata.
        """
        client = self._get_client()
        from google.genai import types
        from google.genai.errors import ClientError

        # Clamp duration to Veo bounds (4-8 seconds supported)
        dur = min(max(int(duration_seconds), 4), 8)

        local_img_path = None
        genai_image = None
        if image_url_or_path:
            local_img_path = await self._resolve_image_to_local_file(image_url_or_path)
            if local_img_path and os.path.exists(local_img_path):
                try:
                    genai_image = types.Image.from_file(location=local_img_path)
                    logger.info(f"Loaded reference product image for Veo conditioning from {local_img_path}")
                except Exception as img_err:
                    logger.warning(f"Failed to load image into types.Image: {img_err}")

        # Build GenerateVideosConfig
        default_negative = (
            "blurry, low resolution, morphing shapes, extra limbs, bad hands, distorted logos, "
            "unreadable text, cartoonish, oversaturated, flicker, jitter, artifacts, watermark"
        )
        config = types.GenerateVideosConfig(
            aspect_ratio=aspect_ratio,
            duration_seconds=dur,
            negative_prompt=negative_prompt or default_negative,
        )

        logger.info(
            f"Submitting Veo video generation: model={self.model}, duration={dur}s, "
            f"aspect_ratio={aspect_ratio}, with_reference_image={bool(genai_image)}"
        )

        try:
            # Run the synchronous SDK call in executor to keep event loop free
            loop = asyncio.get_running_loop()
            
            def _call_veo():
                kwargs = {
                    "model": self.model,
                    "prompt": prompt,
                    "config": config,
                }
                if genai_image is not None:
                    kwargs["image"] = genai_image
                return client.models.generate_videos(**kwargs)

            operation = await loop.run_in_executor(None, _call_veo)
            
            op_name = getattr(operation, "name", None) or f"veo-op-{uuid.uuid4().hex[:12]}"
            is_done = getattr(operation, "done", False)

            logger.info(f"Veo operation initiated successfully: name={op_name}, done={is_done}")
            return {
                "success": True,
                "operation_name": op_name,
                "model": self.model,
                "done": is_done,
                "operation": operation
            }

        except ClientError as ce:
            err_str = str(ce)
            logger.error(f"Veo API ClientError: {err_str}")
            if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                raise VeoQuotaError(
                    f"Google Veo API Quota Exceeded (429): Your Gemini API key currently has 0 video quota. "
                    f"A paid Google Cloud / Gemini billing account is required for live Veo rendering."
                )
            elif "404" in err_str or "NOT_FOUND" in err_str:
                raise VeoModelError(
                    f"Configured Veo model '{self.model}' was not found or is not enabled for this project."
                )
            elif "403" in err_str or "PERMISSION_DENIED" in err_str:
                raise VeoModelError(
                    f"Permission denied for Veo model '{self.model}'. Verify API key permissions."
                )
            else:
                raise VeoError(f"Veo API ClientError: {err_str}")

        except Exception as e:
            err_str = str(e)
            logger.error(f"Unexpected error calling Veo: {err_str}")
            if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                raise VeoQuotaError(
                    f"Google Veo API Quota Exceeded (429): Your Gemini API key currently has 0 video quota."
                )
            raise VeoError(f"Veo invocation failed: {err_str}")

        finally:
            # Clean up temporary downloaded file if one was created
            if local_img_path and local_img_path.startswith(tempfile.gettempdir()) and os.path.exists(local_img_path):
                try:
                    os.remove(local_img_path)
                except Exception:
                    pass

    async def poll_operation(
        self,
        operation_name: str,
        max_wait_seconds: int = 180,
        poll_interval: int = 5,
        on_progress = None
    ) -> str:
        """
        Polls a Veo long-running operation until finished, downloads the MP4,
        and saves it to the backend media storage directory.
        Returns the relative media URL (e.g., /media/videos/veo_12345.mp4).
        """
        client = self._get_client()
        from google.genai import types

        loop = asyncio.get_running_loop()
        elapsed = 0

        logger.info(f"Polling Veo operation '{operation_name}' for up to {max_wait_seconds}s...")

        while elapsed < max_wait_seconds:
            try:
                def _get_op():
                    return client.operations.get(types.GenerateVideosOperation(name=operation_name))

                op = await loop.run_in_executor(None, _get_op)

                if getattr(op, "done", False):
                    # Check for operation error
                    if getattr(op, "error", None):
                        raise VeoError(f"Veo generation failed: {op.error.message}")

                    # Extract generated video
                    resp = getattr(op, "response", None)
                    if not resp or not getattr(resp, "generated_videos", None):
                        raise VeoError("Veo operation completed but returned no video assets.")

                    gen_video = resp.generated_videos[0].video
                    video_bytes = getattr(gen_video, "video_bytes", None)
                    video_uri = getattr(gen_video, "uri", None)

                    # Ensure media directory exists
                    media_dir = os.path.join("uploads", "videos")
                    os.makedirs(media_dir, exist_ok=True)

                    out_filename = f"veo_{uuid.uuid4().hex[:10]}.mp4"
                    out_path = os.path.join(media_dir, out_filename)

                    if video_bytes:
                        with open(out_path, "wb") as f:
                            f.write(video_bytes)
                        logger.info(f"Veo MP4 video saved from bytes: {out_path} ({len(video_bytes)} bytes)")
                    elif video_uri:
                        # Download from URI
                        async with httpx.AsyncClient(timeout=60.0) as http_client:
                            v_resp = await http_client.get(video_uri)
                            if v_resp.status_code == 200:
                                with open(out_path, "wb") as f:
                                    f.write(v_resp.content)
                                logger.info(f"Veo MP4 video downloaded from URI: {out_path}")
                            else:
                                raise VeoError(f"Failed to download video from URI: {video_uri} (status {v_resp.status_code})")
                    else:
                        raise VeoError("Generated video object did not contain video_bytes or uri.")

                    rel_url = f"/uploads/videos/{out_filename}"
                    return rel_url

            except Exception as e:
                if isinstance(e, VeoError):
                    raise e
                logger.warning(f"Error during Veo polling iteration: {e}")

            await asyncio.sleep(poll_interval)
            elapsed += poll_interval
            if on_progress:
                # Approximate progress curve from 60% to 85%
                pct = min(60 + int((elapsed / max_wait_seconds) * 25), 85)
                await on_progress(pct, f"Rendering realistic video clip with Veo ({elapsed}s)")

        raise VeoError(f"Veo operation '{operation_name}' timed out after {max_wait_seconds} seconds.")
