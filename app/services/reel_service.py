import asyncio
import logging
import traceback
from datetime import datetime
from bson import ObjectId
from app.core.database import get_database
from app.schemas.reel import GenerateReelRequest, ReelJobStatus
from app.services.reel_script_service import ReelScriptService
from app.ai.providers.voice_provider import get_voice_provider
from app.ai.providers.video_provider import get_video_provider
from app.ai.video.composer import VideoComposer

logger = logging.getLogger(__name__)

_background_tasks = set()

class ReelService:
    def __init__(self, db):
        self.db = db
        self.script_service = ReelScriptService()
        self.voice_provider = get_voice_provider()
        self.video_provider = get_video_provider()
        self.composer = VideoComposer()

    async def create_reel_job(self, user_id: str, business_id: str, request: GenerateReelRequest, product: dict, brand: dict) -> str:
        """Creates a background job for Reel generation."""
        job_doc = {
            "user_id": ObjectId(user_id) if ObjectId.is_valid(user_id) else user_id,
            "business_id": ObjectId(business_id) if ObjectId.is_valid(business_id) else business_id,
            "product_id": request.product_id,
            "product_name": product.get("name", "Product"),
            "product_description": product.get("description", ""),
            "objective": request.objective,
            "platform": request.platform,
            "language": request.language,
            "duration": request.duration,
            "status": "queued",
            "progress": 0,
            "stage": "Waiting to start",
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        }
        
        result = await self.db["reel_jobs"].insert_one(job_doc)
        job_id = str(result.inserted_id)
        
        # Keep strong reference to prevent premature garbage collection in Python 3.12+
        task = asyncio.create_task(self._process_reel_generation(job_id, str(user_id), product, brand, request))
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)
        
        return job_id

    async def get_job_status(self, job_id: str) -> ReelJobStatus:
        if not ObjectId.is_valid(job_id):
            return None
            
        job = await self.db["reel_jobs"].find_one({"_id": ObjectId(job_id)})
        if not job:
            return None
            
        return ReelJobStatus(
            job_id=str(job["_id"]),
            status=job.get("status", "unknown"),
            progress=job.get("progress", 0),
            stage=job.get("stage", ""),
            video_url=job.get("video_url"),
            thumbnail_url=job.get("thumbnail_url"),
            audio_url=job.get("audio_url"),
            script=job.get("script"),
            caption=job.get("caption"),
            hashtags=job.get("hashtags"),
            product_name=job.get("product_name"),
            product_description=job.get("product_description"),
        )

    async def _update_job(self, job_id: str, updates: dict):
        updates["updated_at"] = datetime.utcnow()
        await self.db["reel_jobs"].update_one(
            {"_id": ObjectId(job_id)},
            {"$set": updates}
        )

    async def _process_reel_generation(self, job_id: str, user_id: str, product: dict, brand: dict, request: GenerateReelRequest):
        try:
            # 1. Generate Script
            await self._update_job(job_id, {"status": "processing", "progress": 10, "stage": "Generating script"})
            script = await self.script_service.generate_script(
                product=product,
                brand=brand,
                objective=request.objective,
                platform=request.platform,
                duration=request.duration,
                language=request.language,
                tone=request.tone,
                offer=request.offer,
                additional_instruction=request.additional_instruction
            )
            await self._update_job(job_id, {"script": script.model_dump(), "caption": script.caption, "hashtags": script.hashtags})
            
            # Extract combined voiceover text
            full_voiceover = " ".join([scene.voiceover for scene in script.scenes if scene.voiceover])
            
            # 2. Generate Voice
            await self._update_job(job_id, {"progress": 30, "stage": "Generating voiceover"})
            audio_url = await self.voice_provider.generate_audio(
                text=full_voiceover,
                language=script.language,
                voice="en_US-lessac-medium" # Should be mapped properly
            )
            
            # 3. Generate Video Scenes
            await self._update_job(job_id, {"progress": 50, "stage": "Generating video scenes"})
            
            # Resolve product images
            product_images = []
            if product.get("images") and isinstance(product["images"], list):
                product_images.extend([img for img in product["images"] if img and isinstance(img, str)])
            if product.get("image_url") and product["image_url"] not in product_images:
                product_images.insert(0, product["image_url"])

            primary_image = product_images[0] if product_images else None

            from app.ai.image.generator import ImageGenerator
            from app.core.config import settings
            image_gen = ImageGenerator(
                api_url=getattr(settings, "IMAGE_API_URL", "https://api.openai.com/v1/images/generations"),
                api_key=getattr(settings, "IMAGE_API_KEY", "your_api_key_here")
            )
            product_name = product.get("name", "Product")

            # If no product image, generate a realistic hero one dynamically
            if not primary_image:
                await self._update_job(job_id, {"progress": 40, "stage": "Generating product hero image"})
                img_prompt = f"Professional product photography of a {product_name}, highly detailed, photorealistic, 8k resolution, commercial studio lighting"
                img_res = await image_gen.generate(prompt=img_prompt)
                primary_image = img_res.get("image_url")
                if primary_image:
                    product_images.append(primary_image)

            if not primary_image:
                raise Exception("Failed to acquire or generate visual assets for composition")

            # Prepare distinct visual images for each scene in parallel
            await self._update_job(job_id, {"progress": 60, "stage": "Generating animated scene visuals"})

            async def resolve_scene_image(idx, scene):
                if idx < len(product_images) and product_images[idx]:
                    return product_images[idx]
                visual_desc = getattr(scene, "visual", "") or f"showcase of {product_name}"
                prompt = f"Professional commercial photography of {product_name}, {visual_desc}, modern cinematic aesthetic, vibrant studio lighting, 8k"
                try:
                    res = await image_gen.generate(prompt=prompt)
                    return res.get("image_url") or primary_image
                except Exception:
                    return primary_image

            video_segments = await asyncio.gather(*[
                resolve_scene_image(i, sc) for i, sc in enumerate(script.scenes)
            ])
            if not video_segments:
                video_segments = [primary_image] * len(script.scenes)
            
            image_url = primary_image
            
            # 4. Compose Final Video
            await self._update_job(job_id, {"progress": 80, "stage": "Composing final reel"})
            final_video_url = await self.composer.compose_reel(
                video_segments=video_segments,
                audio_url=audio_url,
                brand_colors={"primary": brand.get("primary_color", "#000000")},
                script=script
            )

            if not final_video_url:
                raise Exception("Failed to compose final video")

            # 5. Completed
            await self._update_job(job_id, {
                "status": "completed",
                "progress": 100,
                "stage": "Completed",
                "video_url": final_video_url,   
                "thumbnail_url": image_url,      
                "audio_url": audio_url,          
                "product_name": product.get("name", ""),
                "product_description": product.get("description", ""),
            })
            
        except Exception as e:
            err_msg = str(e).strip()
            if not err_msg:
                err_msg = repr(e)
            if len(err_msg) > 200:
                err_msg = err_msg[:200] + "..."
                
            logger.error(f"Reel generation failed for job {job_id}: {traceback.format_exc()}")
            await self._update_job(job_id, {
                "status": "failed",
                "progress": 0,
                "stage": f"Failed: {err_msg}"
            })
            
            # Refund credits safely on failure exactly once
            try:
                from app.services.credit_service import CreditService
                await CreditService.refund_credits(self.db, user_id=user_id, action="ai_reel", job_id=job_id)
            except Exception as refund_err:
                logger.error(f"Failed to refund credits for job {job_id}: {refund_err}")
