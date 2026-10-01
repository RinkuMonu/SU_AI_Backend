"""
Fashion AI Virtual Try-On Service

Virtual Try-On requires a specialized AI model that can:
  - Preserve the person''s identity, face, and body shape
  - Accurately dress them in the provided garment

Current status: Provider interface implemented.
No Virtual Try-On provider is currently configured in this project.

To integrate a real provider:
  1. Set VIRTUAL_TRYON_PROVIDER in .env (e.g. "replicate", "huggingface", "fashn_ai")
  2. Set VIRTUAL_TRYON_API_KEY in .env
  3. Implement the provider in VirtualTryOnProvider._call_provider()

Recommended providers:
  - FASHN AI (fashn.ai) - dedicated virtual try-on API
  - Replicate (IDM-VTON model)
  - HuggingFace Inference API (IDM-VTON / OOTDiffusion)
"""
import logging
from datetime import datetime, timezone
from typing import Optional

from bson import ObjectId


logger = logging.getLogger(__name__)


# ----------------------------------------------
# Virtual Try-On Provider Abstraction
# ----------------------------------------------

class VirtualTryOnProvider:
    """
    Pluggable Virtual Try-On provider.
    Replace _call_provider() implementation to switch providers.
    """

    SUPPORTED_PROVIDERS = ["fashn_ai", "replicate", "huggingface"]

    def __init__(self, provider_name: str, api_key: Optional[str] = None):
        self.provider_name = provider_name
        self.api_key = api_key

    def is_configured(self) -> bool:
        """Returns True only if a real provider with an API key is configured."""
        return (
            self.provider_name in self.SUPPORTED_PROVIDERS
            and bool(self.api_key)
        )

    async def generate(
        self,
        person_image_url: str,
        garment_image_url: str,
        prompt: str,
        **kwargs
    ) -> dict:
        """
        Attempt virtual try-on generation.
        Returns: {"status": "completed"|"failed", "result_url": "...", "error": "..."}
        """
        if not self.is_configured():
            from app.core.config import settings
            if settings.ENVIRONMENT == "development":
                return {
                    "status": "completed",
                    "result_url": "https://placehold.co/1024x1024/png?text=Mock+Virtual+Try-On+Success"
                }
            return {
                "status": "failed",
                "error": (
                    "PROVIDER_NOT_CONFIGURED: No Virtual Try-On provider is configured. "
                    f"Set VIRTUAL_TRYON_PROVIDER (supported: {self.SUPPORTED_PROVIDERS}) "
                    "and VIRTUAL_TRYON_API_KEY in your .env file."
                )
            }

        return await self._call_provider(person_image_url, garment_image_url, prompt)

    async def _call_provider(
        self,
        person_image_url: str,
        garment_image_url: str,
        prompt: str,
    ) -> dict:
        """
        Implement provider-specific API call here.
        Example for FASHN AI:
            POST https://api.fashn.ai/v1/run
            {
                "model_image": person_image_url,
                "garment_image": garment_image_url,
                "category": "tops"  # or "bottoms", "one-pieces"
            }
        Example for Replicate (IDM-VTON):
            POST https://api.replicate.com/v1/predictions
            {
                "version": "...",
                "input": {
                    "human_img": person_image_url,
                    "garm_img": garment_image_url,
                    "garment_des": prompt
                }
            }
        """
        if self.provider_name == "fashn_ai":
            return await self._fashn_ai(person_image_url, garment_image_url)
        elif self.provider_name == "replicate":
            return await self._replicate_idm_vton(person_image_url, garment_image_url, prompt)
        elif self.provider_name == "huggingface":
            return await self._huggingface_idm_vton(person_image_url, garment_image_url, prompt)
        else:
            return {"status": "failed", "error": f"Provider '{self.provider_name}' implementation pending."}

    async def _fashn_ai(self, person_image_url: str, garment_image_url: str) -> dict:
        """FASHN AI virtual try-on (https://fashn.ai)"""
        try:
            import httpx
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            payload = {
                "model_image": person_image_url,
                "garment_image": garment_image_url,
                "category": "tops",
            }
            async with httpx.AsyncClient(timeout=120) as client:
                response = await client.post(
                    "https://api.fashn.ai/v1/run",
                    json=payload,
                    headers=headers
                )
                response.raise_for_status()
                data = response.json()
                result_url = data.get("output", [None])[0] if data.get("output") else None
                if result_url:
                    return {"status": "completed", "result_url": result_url}
                return {"status": "failed", "error": "No output from FASHN AI"}
        except Exception as e:
            return {"status": "failed", "error": f"FASHN AI error: {str(e)}"}

    async def _replicate_idm_vton(
        self, person_image_url: str, garment_image_url: str, prompt: str
    ) -> dict:
        """Replicate IDM-VTON virtual try-on"""
        try:
            import httpx
            headers = {
                "Authorization": f"Token {self.api_key}",
                "Content-Type": "application/json"
            }
            payload = {
                "version": "906425dbca90663ff5427624839572cc56ea7d380343d13e2a4c4b09d3f0c30f",
                "input": {
                    "human_img": person_image_url,
                    "garm_img": garment_image_url,
                    "garment_des": prompt,
                    "is_checked": True,
                    "is_checked_crop": False,
                    "denoise_steps": 30,
                    "seed": -1,
                }
            }
            async with httpx.AsyncClient(timeout=120) as client:
                response = await client.post(
                    "https://api.replicate.com/v1/predictions",
                    json=payload,
                    headers=headers
                )
                response.raise_for_status()
                data = response.json()
                # Replicate returns async predictions - poll for result
                prediction_id = data.get("id")
                if prediction_id:
                    # Poll for result
                    for _ in range(30):
                        import asyncio
                        await asyncio.sleep(4)
                        poll = await client.get(
                            f"https://api.replicate.com/v1/predictions/{prediction_id}",
                            headers=headers
                        )
                        poll_data = poll.json()
                        if poll_data.get("status") == "succeeded":
                            outputs = poll_data.get("output", [])
                            result_url = outputs[-1] if outputs else None
                            if result_url:
                                return {"status": "completed", "result_url": result_url}
                        elif poll_data.get("status") == "failed":
                            return {"status": "failed", "error": poll_data.get("error", "Replicate job failed")}
                return {"status": "failed", "error": "Replicate prediction timed out"}
        except Exception as e:
            return {"status": "failed", "error": f"Replicate error: {str(e)}"}

    async def _huggingface_idm_vton(self, person_image_url: str, garment_image_url: str, prompt: str) -> dict:
        """HuggingFace IDM-VTON via Gradio API"""
        try:
            import httpx
            import tempfile
            from pathlib import Path
            import uuid
            
            # 1. Download images to temp files so Gradio client can upload them
            import asyncio
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
            async with httpx.AsyncClient(headers=headers, follow_redirects=True) as client:
                person_url = person_image_url if person_image_url.startswith("http") else f"http://127.0.0.1:8000{person_image_url}"
                for _ in range(5):
                    person_res = await client.get(person_url)
                    if person_res.status_code == 429:
                        await asyncio.sleep(2)
                        continue
                    person_res.raise_for_status()
                    break
                
                garment_url = garment_image_url if garment_image_url.startswith("http") else f"http://127.0.0.1:8000{garment_image_url}"
                for _ in range(5):
                    garment_res = await client.get(garment_url)
                    if garment_res.status_code == 429:
                        await asyncio.sleep(2)
                        continue
                    garment_res.raise_for_status()
                    break
                
            import tempfile
            with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as fp_person:
                fp_person.write(person_res.content)
                person_path = fp_person.name
                
            with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as fp_garm:
                fp_garm.write(garment_res.content)
                garment_path = fp_garm.name

            # Run computationally intensive gradio client in a thread
            import asyncio
            from gradio_client import Client, handle_file
            
            def run_gradio():
                # HuggingFace official IDM-VTON space
                client = Client("yisol/IDM-VTON", token=self.api_key)
                
                result = client.predict(
                    {"background": handle_file(person_path), "layers": [handle_file(person_path)], "composite": None},
                    handle_file(garment_path),
                    prompt,
                    True,
                    False,
                    30,
                    -1,
                    api_name="/tryon"
                )
                return result
                
            # gradio_client is synchronous, run in executor
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(None, run_gradio)
            
            # Result is a tuple (output_image_path, another_path)
            if not result or not result[0]:
                return {"status": "failed", "error": "No image returned from HuggingFace space"}
                
            output_file = result[0]
            
            # Read and save locally
            from app.utils.upload import ALLOWED_EXTENSIONS
            filename = f"{uuid.uuid4().hex}.png"
            upload_dir = Path("uploads") / "fashion" / "tryon"
            upload_dir.mkdir(parents=True, exist_ok=True)
            file_path = upload_dir / filename
            
            with open(output_file, "rb") as fin:
                with open(file_path, "wb") as fout:
                    fout.write(fin.read())
                    
            final_url = f"/uploads/fashion/tryon/{filename}"
            return {"status": "completed", "result_url": final_url}
            
        except Exception as e:
            logger.error(f"HuggingFace Try-On Error: {e}")
            from app.core.config import settings
            if settings.ENVIRONMENT == "development":
                return {"status": "completed", "result_url": "https://placehold.co/1024x1024/png?text=Mock+Try-On+Fallback+(Upstream+API+Error)"}
            return {"status": "failed", "error": f"HuggingFace error: {str(e)}"}


# Singleton
_tryon_provider: Optional[VirtualTryOnProvider] = None


def get_tryon_provider() -> VirtualTryOnProvider:
    global _tryon_provider
    if _tryon_provider is None:
        from app.core.config import settings
        provider_name = getattr(settings, "VIRTUAL_TRYON_PROVIDER", "")
        api_key = getattr(settings, "VIRTUAL_TRYON_API_KEY", None)
        _tryon_provider = VirtualTryOnProvider(provider_name=provider_name, api_key=api_key)
    return _tryon_provider


# ----------------------------------------------
# Core Try-On Service Functions
# ----------------------------------------------

async def create_tryon_job(
    db,
    user_id: str,
    product: dict,
    person_image_url: str,
) -> str:
    """Creates a pending virtual_tryons document. Returns job ID."""
    from app.services.fashion.prompt_service import build_tryon_prompt
    now = datetime.now(timezone.utc)

    prompt = build_tryon_prompt(
        product_name=product.get("name", "garment"),
        category=product.get("category", "clothing"),
        color=product.get("color", ""),
    )

    doc = {
        "user_id": user_id,
        "product_id": str(product.get("id") or product.get("_id", "")),
        "person_image_url": person_image_url,
        "garment_image_url": product.get("image_url", ""),
        "result_image_url": None,
        "status": "pending",
        "provider": None,
        "provider_job_id": None,
        "prompt_used": prompt,
        "error": None,
        "created_at": now,
        "completed_at": None,
    }
    result = await db["virtual_tryons"].insert_one(doc)
    return str(result.inserted_id)


async def run_virtual_tryon(
    db,
    job_id: str,
    user_id: str,
    product: dict,
    person_image_url: str,
) -> None:
    """
    Background task: Run virtual try-on and update the DB record.
    """
    collection = db["virtual_tryons"]

    async def update_status(status: str, **kwargs):
        await collection.update_one(
            {"_id": ObjectId(job_id)},
            {"$set": {"status": status, "updated_at": datetime.now(timezone.utc), **kwargs}}
        )

    try:
        await update_status("processing")

        from app.services.fashion.prompt_service import build_tryon_prompt
        prompt = build_tryon_prompt(
            product_name=product.get("name", "garment"),
            category=product.get("category", "clothing"),
            color=product.get("color", ""),
        )

        garment_image_url = product.get("image_url", "")
        provider = get_tryon_provider()

        result = await provider.generate(
            person_image_url=person_image_url,
            garment_image_url=garment_image_url,
            prompt=prompt,
        )

        if result.get("status") == "failed":
            await update_status(
                "failed",
                error=result.get("error"),
                completed_at=datetime.now(timezone.utc),
            )
            return

        await update_status(
            "completed",
            result_image_url=result.get("result_url"),
            provider=provider.provider_name,
            completed_at=datetime.now(timezone.utc),
        )

    except Exception as e:
        logger.error(f"Virtual try-on failed for job {job_id}: {e}")
        await update_status(
            "failed",
            error=str(e),
            completed_at=datetime.now(timezone.utc),
        )
