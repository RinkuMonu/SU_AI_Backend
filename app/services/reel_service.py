import asyncio
import logging
import traceback
from datetime import datetime
from bson import ObjectId

from app.core.database import get_database
from app.core.config import settings
from app.schemas.reel import GenerateReelRequest, ReelJobStatus
from app.services.reel_script_service import ReelScriptService
from app.ai.prompts.reel import detect_product_domain
from app.ai.providers.voice_provider import get_voice_provider
from app.ai.providers.video_provider import get_video_provider
from app.ai.providers.veo_provider import VeoVideoProvider, VeoQuotaError, VeoModelError, VeoError
from app.ai.video.composer import VideoComposer

logger = logging.getLogger(__name__)

_background_tasks = set()

class ReelService:
    def __init__(self, db):
        self.db = db
        self.script_service = ReelScriptService()
        self.voice_provider = get_voice_provider()
        self.veo_provider = VeoVideoProvider()
        self.composer = VideoComposer()

    async def create_reel_job(self, user_id: str, business_id: str, request: GenerateReelRequest, product: dict, brand: dict) -> str:
        """Creates an asynchronous background job for realistic AI Reel generation with locked product context."""
        gen_mode = getattr(request, "generation_mode", "product") or "product"
        user_prompt_val = getattr(request, "prompt", None) or getattr(request, "custom_prompt", None)
        if gen_mode in ["prompt", "veo"] or user_prompt_val:
            gen_mode = "prompt"
            if not product.get("name") or product.get("name") in ["Product", "general"]:
                product["name"] = request.product_name or (user_prompt_val[:45] if user_prompt_val else "AI Custom Reel")
            product["description"] = user_prompt_val or product.get("description", "")
            product["category"] = request.product_category or "AI Cinematic Reel"
            product["prompt"] = user_prompt_val
            product["video_style"] = getattr(request, "video_style", "Cinematic 8K Photoreal")

        product_cat = request.product_category or product.get("category") or "Commercial Product"
        fest_theme = getattr(request, "festival_theme", "none") or "none"

        job_doc = {
            "user_id": ObjectId(user_id) if ObjectId.is_valid(user_id) else user_id,
            "business_id": ObjectId(business_id) if ObjectId.is_valid(business_id) else business_id,
            "product_id": request.product_id,
            "product_name": product.get("name", "Product"),
            "product_category": product_cat,
            "product_description": product.get("description", ""),
            "objective": request.objective,
            "generation_mode": gen_mode,
            "festival_theme": fest_theme,
            "platform": request.platform,
            "language": request.language,
            "duration": request.duration,
            "status": "queued",
            "progress": 0,
            "stage": "Waiting in generation queue",
            "provider": "veo",
            "provider_status": "queued",
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
            
        script_obj = job.get("script") or {}
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
            product_category=job.get("product_category"),
            generation_mode=job.get("generation_mode"),
            festival_theme=job.get("festival_theme"),
            hook_headline=job.get("hook_headline") or script_obj.get("hook_headline"),
            hook_highlight=job.get("hook_highlight") or script_obj.get("hook_highlight"),
            trending_audio=job.get("trending_audio") or script_obj.get("trending_audio") or "Trending Sound • Viral Hit",
            creator_name=job.get("creator_name") or script_obj.get("creator_name") or "Viral Reel Creator",
            follower_count=job.get("follower_count") or script_obj.get("follower_count") or "26.4K followers",
            likes_count=job.get("likes_count") or script_obj.get("likes_count") or "28.5K",
            comments_count=job.get("comments_count") or script_obj.get("comments_count") or "894",
            provider=job.get("provider"),
            provider_operation_id=job.get("provider_operation_id"),
            provider_status=job.get("provider_status"),
            provider_error=job.get("provider_error"),
        )

    async def _update_job(self, job_id: str, updates: dict):
        updates["updated_at"] = datetime.utcnow()
        await self.db["reel_jobs"].update_one(
            {"_id": ObjectId(job_id)},
            {"$set": updates}
        )

    async def _process_reel_generation(self, job_id: str, user_id: str, product: dict, brand: dict, request: GenerateReelRequest):
        try:
            gen_mode = getattr(request, "generation_mode", "product") or "product"
            fest_theme = getattr(request, "festival_theme", "none") or "none"

            # 1. Intelligent Gemini Prompt Planning & Storyboard
            await self._update_job(job_id, {
                "status": "planning",
                "progress": 15,
                "stage": "Planning creative storyboard with Gemini"
            })
            
            script = await self.script_service.generate_script(
                product=product,
                brand=brand,
                objective=request.objective,
                platform=request.platform,
                duration=request.duration,
                language=request.language,
                tone=request.tone,
                offer=request.offer,
                additional_instruction=request.additional_instruction,
                generation_mode=gen_mode,
                festival_theme=fest_theme
            )
            
            # Ensure viral hook components are present and locked to this product
            hook_text = script.hook or ""
            hook_headline = getattr(script, "hook_headline", None)
            hook_highlight = getattr(script, "hook_highlight", None)
            if not hook_headline or not hook_highlight:
                prod_name = product.get("name", "Product")
                if "?" in hook_text:
                    parts = hook_text.split("?", 1)
                    hook_headline = parts[0].strip() + "?"
                    hook_highlight = parts[1].strip() if len(parts) > 1 and parts[1].strip() else f"{prod_name} ✨"
                elif "!" in hook_text:
                    parts = hook_text.split("!", 1)
                    hook_headline = parts[0].strip() + "!"
                    hook_highlight = parts[1].strip() if len(parts) > 1 and parts[1].strip() else f"Discover {prod_name} ✨"
                elif len(hook_text.split()) > 2:
                    words = hook_text.split()
                    hook_headline = " ".join(words[:2])
                    hook_highlight = " ".join(words[2:])
                else:
                    hook_headline = "Meet the new..."
                    hook_highlight = f"{prod_name} 🔥"
                script.hook_headline = hook_headline
                script.hook_highlight = hook_highlight

            # Smart trending audio & creator defaults locked strictly to product domain
            domain = detect_product_domain(product.get("name", ""), product.get("category", ""), product.get("description", ""))
            business_name = brand.get("business_name") or brand.get("name") or "SevenUnique Partner"

            if not getattr(script, "trending_audio", None) or script.trending_audio == "Trending Sound • Viral Hit":
                if domain in ["laptop_computer", "electronics_tech"]:
                    script.trending_audio = "Synthwave Tech • Trending"
                    script.creator_name = script.creator_name or f"{business_name} Tech"
                    script.follower_count = script.follower_count or "98.7K followers"
                elif domain in ["saree_ethnic", "lehenga_ethnic"]:
                    script.trending_audio = "Rangi Re (Trending)"
                    script.creator_name = script.creator_name or f"{business_name} Couture"
                    script.follower_count = script.follower_count or "24.5K followers"
                elif domain in ["skincare_beauty", "cosmetics_fragrance"]:
                    script.trending_audio = "Bridal Sparkle • Trending"
                    script.creator_name = script.creator_name or f"{business_name} Glow"
                    script.follower_count = script.follower_count or "72.6K followers"
                elif domain == "food_dining":
                    script.trending_audio = "Food Grooves • Trending"
                    script.creator_name = script.creator_name or f"{business_name} Kitchen"
                    script.follower_count = script.follower_count or "45.1K followers"
                elif domain == "jewellery_luxury":
                    script.trending_audio = "Pure Velvet • Trending"
                    script.creator_name = script.creator_name or f"{business_name} Jewels"
                    script.follower_count = script.follower_count or "54.2K followers"
                else:
                    script.trending_audio = "Commercial Energy • Trending"
                    script.creator_name = script.creator_name or f"{business_name} Official"
                    script.follower_count = script.follower_count or "34.2K followers"

            script_dict = script.model_dump()
            await self._update_job(job_id, {
                "script": script_dict,
                "caption": script.caption,
                "hashtags": script.hashtags,
                "hook_headline": script.hook_headline,
                "hook_highlight": script.hook_highlight,
                "trending_audio": script.trending_audio,
                "creator_name": script.creator_name,
                "follower_count": getattr(script, "follower_count", "28.4K followers"),
                "likes_count": getattr(script, "likes_count", "26.3K"),
                "comments_count": getattr(script, "comments_count", "874"),
                "advertising_objective": getattr(script, "advertising_objective", None),
                "visual_concept": getattr(script, "visual_concept", None)
            })
            
            # Extract combined voiceover text
            full_voiceover = " ".join([scene.voiceover for scene in script.scenes if scene.voiceover])
            if not full_voiceover.strip():
                full_voiceover = f"Check out {product.get('name', 'this product')}! {request.offer or 'Available now.'}"
            
            # 2. Generate Neural Voiceover
            await self._update_job(job_id, {
                "status": "generating_voice",
                "progress": 35,
                "stage": "Generating neural voiceover"
            })
            try:
                audio_url = await self.voice_provider.generate_audio(
                    text=full_voiceover,
                    language=script.language or request.language or "Hinglish",
                    voice=getattr(request, "voice", None) or "hi-IN-SwaraNeural",
                    speed=1.05 if (request.tone or "").lower() == "energetic" else 1.0
                )
            except Exception as voice_err:
                logger.warning(f"Voice generation failed: {voice_err}. Falling back to mock audio.")
                from app.ai.providers.voice_provider import MockVoiceProvider
                audio_url = await MockVoiceProvider().generate_audio(
                    text=full_voiceover,
                    language=script.language or request.language or "Hinglish"
                )
            
            # 3. Resolve Product Visual Assets
            product_images = []
            if product.get("images") and isinstance(product["images"], list):
                product_images.extend([img for img in product["images"] if img and isinstance(img, str)])
            if product.get("image_url") and product["image_url"] not in product_images:
                product_images.insert(0, product["image_url"])

            primary_image = product_images[0] if product_images else None

            from app.ai.image.generator import ImageGenerator
            image_gen = ImageGenerator(
                api_url=getattr(settings, "IMAGE_API_URL", "https://api.openai.com/v1/images/generations"),
                api_key=getattr(settings, "IMAGE_API_KEY", "your_api_key_here")
            )
            product_name = product.get("name", "Product")
            product_desc = product.get("description", "")
            product_category = product.get("category", "")

            # If no product image was supplied, synthesize an authentic product image locked to this exact product
            if not primary_image:
                await self._update_job(job_id, {"progress": 45, "stage": "Acquiring authentic product imagery"})
                img_prompt = f"{product_name} {product_category} {product_desc}".strip()
                img_res = await image_gen.generate(prompt=img_prompt, scene_idx=0)
                primary_image = img_res.get("image_url")
                if primary_image:
                    product_images.append(primary_image)

            if not primary_image:
                raise Exception("Failed to acquire or generate visual assets for product.")

            # 4. Realistic Video Generation with Google Veo
            await self._update_job(job_id, {
                "status": "generating_video",
                "progress": 55,
                "stage": "Submitting video generation to Google Veo 3.1"
            })

            # Formulate the best Veo prompt from the user prompt or Gemini creative plan
            user_direct_prompt = getattr(request, "prompt", None) or getattr(request, "custom_prompt", None)
            v_style = getattr(request, "video_style", "")
            if user_direct_prompt:
                veo_prompt = f"{user_direct_prompt}, {v_style}, 9:16 vertical video, photorealistic cinematic lighting, ultra high fidelity, smooth camera motion".strip(", ")
            else:
                veo_prompt = getattr(script, "veo_video_prompt", None)
            if not veo_prompt and script.scenes and getattr(script.scenes[0], "veo_prompt", None):
                veo_prompt = script.scenes[0].veo_prompt
            if not veo_prompt:
                veo_prompt = (
                    f"Cinematic photorealistic commercial video of {product_name}, 9:16 vertical video, "
                    f"professional studio lighting, smooth camera movement, highly detailed textures."
                )

            veo_video_url = None
            veo_fallback_reason = None

            try:
                # Attempt to generate real video via Google GenAI Veo
                veo_submission = await self.veo_provider.start_video_generation(
                    prompt=veo_prompt,
                    image_url_or_path=primary_image,
                    duration_seconds=min(max(request.duration, 4), 8),
                    aspect_ratio="9:16",
                    negative_prompt=getattr(script, "negative_constraints", None)
                )

                op_name = veo_submission.get("operation_name")
                await self._update_job(job_id, {
                    "progress": 65,
                    "stage": "Rendering realistic video with Google Veo",
                    "provider": "veo",
                    "provider_operation_id": op_name,
                    "provider_status": "generating"
                })

                async def _on_veo_progress(pct, stage_msg):
                    await self._update_job(job_id, {"progress": pct, "stage": stage_msg})

                veo_video_url = await self.veo_provider.poll_operation(
                    operation_name=op_name,
                    max_wait_seconds=120,
                    poll_interval=5,
                    on_progress=_on_veo_progress
                )

                await self._update_job(job_id, {
                    "provider_status": "completed"
                })
                logger.info(f"Veo successfully produced video: {veo_video_url}")

            except (VeoQuotaError, VeoModelError, VeoError) as veo_err:
                veo_fallback_reason = str(veo_err)
                logger.warning(f"Veo video generation note: {veo_fallback_reason}")
                await self._update_job(job_id, {
                    "provider": "veo_fallback_composer",
                    "provider_status": "quota_exhausted_fallback" if "429" in veo_fallback_reason else "fallback",
                    "provider_error": veo_fallback_reason,
                    "stage": "Rendering cinematic dynamic scenes"
                })

            except Exception as unk_err:
                veo_fallback_reason = str(unk_err)
                logger.warning(f"Veo video call exception: {unk_err}")
                await self._update_job(job_id, {
                    "provider": "veo_fallback_composer",
                    "provider_status": "fallback",
                    "provider_error": veo_fallback_reason,
                    "stage": "Rendering cinematic dynamic scenes"
                })

            # Assemble visual segments for composition:
            # If Veo succeeded, use the Veo video segment!
            # Otherwise, use high-resolution scene imagery with FFmpeg Ken Burns dynamic camera motion
            if veo_video_url:
                video_segments = [veo_video_url]
            else:
                await self._update_job(job_id, {"progress": 70, "stage": "Preparing aesthetic scene visuals"})

                # PRODUCT CONTEXT PRESERVATION:
                # If product_images were provided, anchor ALL scenes strictly to this product's authentic photos!
                if product_images:
                    video_segments = [
                        product_images[i % len(product_images)]
                        for i in range(len(script.scenes))
                    ]
                else:
                    # If no product image was supplied, synthesize scene visuals locked to this product
                    async def resolve_scene_image(idx, scene):
                        visual_desc = getattr(scene, "visual", "") or f"showcase of {product_name}"
                        prompt = f"{product_name}, {product_category}, {visual_desc}"
                        try:
                            res = await image_gen.generate(prompt=prompt, scene_idx=idx)
                            return res.get("image_url") or primary_image
                        except Exception:
                            return primary_image

                    video_segments = await asyncio.gather(*[
                        resolve_scene_image(i, sc) for i, sc in enumerate(script.scenes)
                    ])
                    if not video_segments:
                        video_segments = [primary_image] * len(script.scenes)

            # 5. Compose Final Video (Audio mixing, dynamic subtitles, brand overlay, 9:16 export)
            await self._update_job(job_id, {
                "status": "composing",
                "progress": 85,
                "stage": "Composing final reel with synchronized audio & captions"
            })
            
            final_video_url = await self.composer.compose_reel(
                video_segments=video_segments,
                audio_url=audio_url,
                brand_colors={"primary": brand.get("primary_color", "#7928CA")},
                script=script,
                product_name=product_name
            )

            if not final_video_url:
                raise Exception("Failed to compose final video")

            # 6. Completed Successfully
            await self._update_job(job_id, {
                "status": "completed",
                "progress": 100,
                "stage": "Completed",
                "video_url": final_video_url,   
                "thumbnail_url": primary_image,      
                "audio_url": audio_url,          
                "product_name": product.get("name", ""),
                "product_category": product.get("category", ""),
                "product_description": product.get("description", ""),
            })
            logger.info(f"Reel job {job_id} successfully completed with locked product context: {product_name}")
            
        except Exception as e:
            err_msg = str(e).strip() or repr(e)
            if len(err_msg) > 250:
                err_msg = err_msg[:250] + "..."
                
            logger.error(f"Reel generation failed for job {job_id}: {traceback.format_exc()}")
            await self._update_job(job_id, {
                "status": "failed",
                "progress": 0,
                "stage": f"Failed: {err_msg}"
            })
            
            # Safe credit refund on failed jobs
            try:
                from app.services.credit_service import CreditService
                await CreditService.refund_credits(self.db, user_id=user_id, action="ai_reel", job_id=job_id)
            except Exception as refund_err:
                logger.error(f"Failed to refund credits for job {job_id}: {refund_err}")
