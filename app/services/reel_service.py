import os
import asyncio
import logging
import traceback
from datetime import datetime
from bson import ObjectId

from app.core.database import get_database
from app.core.config import settings
from app.schemas.reel import GenerateReelRequest, ReelJobStatus
from app.services.reel_script_service import ReelScriptService
from app.services.image_enhancement_service import ImageEnhancementService
from app.ai.prompts.reel import detect_product_domain
from app.ai.providers.voice_provider import get_voice_provider
from app.ai.providers.video_provider import get_video_provider
from app.ai.providers.veo_provider import VeoVideoProvider, VeoQuotaError, VeoModelError, VeoError
from app.ai.video.composer import VideoComposer
from app.services.video_quality_validator import VideoQualityValidator

logger = logging.getLogger(__name__)

_background_tasks = set()

class ReelService:
    def __init__(self, db):
        self.db = db
        self.script_service = ReelScriptService()
        self.voice_provider = get_voice_provider()
        self.veo_provider = VeoVideoProvider()
        self.composer = VideoComposer()
        self.enhancement_service = ImageEnhancementService()
        self.quality_validator = VideoQualityValidator()

    async def create_reel_job(self, user_id: str, business_id: str, request: GenerateReelRequest, product: dict, brand: dict) -> str:
        """Creates an asynchronous background job for realistic AI Reel generation with locked product context."""
        product_cat = getattr(request, "category", None) or request.product_category or product.get("category") or "Commercial Product"
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
        creation_mode = getattr(request, "creation_mode", "product_image") or "product_image"

        orig_img = request.image_url or request.product_image_url or product.get("image_url")

        job_doc = {
            "user_id": ObjectId(user_id) if ObjectId.is_valid(user_id) else user_id,
            "business_id": ObjectId(business_id) if ObjectId.is_valid(business_id) else business_id,
            "product_id": request.product_id,
            "product_name": product.get("name", "Product"),
            "product_category": product_cat,
            "product_subcategory": getattr(request, "subcategory", None),
            "product_description": product.get("description", ""),
            "creation_mode": creation_mode,
            "objective": getattr(request, "campaign_objective", None) or request.objective,
            "campaign_objective": getattr(request, "campaign_objective", None) or request.objective,
            "generation_mode": gen_mode,
            "festival_theme": fest_theme,
            "platform": request.platform,
            "language": request.language,
            "duration": request.duration,
            "voiceover_mode": getattr(request, "voiceover_mode", "ai"),
            "voice_tone": getattr(request, "voice_tone", "energetic") or request.tone,
            "music_style": getattr(request, "music_style", "cinematic"),
            "captions_enabled": getattr(request, "captions_enabled", True),
            "original_image_url": orig_img,
            "enhanced_image_url": None,
            "use_brand_kit": getattr(request, "use_brand_kit", False),
            "brand_kit_applied": bool(getattr(request, "use_brand_kit", False) and brand),
            "brand": brand if getattr(request, "use_brand_kit", False) else None,
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
            original_image_url=job.get("original_image_url"),
            enhanced_image_url=job.get("enhanced_image_url"),
            creation_mode=job.get("creation_mode"),
            campaign_objective=job.get("campaign_objective") or job.get("objective"),
            platform=job.get("platform"),
            duration=job.get("duration"),
            language=job.get("language"),
            voiceover_mode=job.get("voiceover_mode"),
            music_style=job.get("music_style"),
            captions_enabled=job.get("captions_enabled"),
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
            quality_report=job.get("quality_report"),
            motion_classification=job.get("motion_classification"),
            motion_score=job.get("motion_score"),
            diversity_score=job.get("diversity_score"),
            use_brand_kit=job.get("use_brand_kit", False),
            brand_kit_applied=job.get("brand_kit_applied", False),
            brand=job.get("brand"),
        )

    async def retry_job(self, job_id: str, user_id: str) -> bool:
        """Retries a failed reel generation job using stored assets and configurations."""
        if not ObjectId.is_valid(job_id):
            return False

        job = await self.db["reel_jobs"].find_one({
            "_id": ObjectId(job_id),
            "user_id": ObjectId(user_id) if ObjectId.is_valid(user_id) else user_id
        })
        if not job:
            return False

        use_bk = job.get("use_brand_kit", False)

        # Re-construct request and product
        request = GenerateReelRequest(
            product_id=job.get("product_id", "general"),
            product_name=job.get("product_name"),
            category=job.get("product_category"),
            subcategory=job.get("product_subcategory"),
            product_description=job.get("product_description"),
            creation_mode=job.get("creation_mode", "product_image"),
            image_url=job.get("original_image_url"),
            duration=job.get("duration", 15),
            language=job.get("language", "Hinglish"),
            platform=job.get("platform", "instagram_reels"),
            voiceover_mode=job.get("voiceover_mode", "ai"),
            voice_tone=job.get("voice_tone", "energetic"),
            music_style=job.get("music_style", "cinematic"),
            captions_enabled=job.get("captions_enabled", True),
            campaign_objective=job.get("campaign_objective", "product_showcase"),
            festival_theme=job.get("festival_theme", "none"),
            use_brand_kit=use_bk
        )

        product = {
            "id": job.get("product_id"),
            "name": job.get("product_name"),
            "category": job.get("product_category"),
            "description": job.get("product_description"),
            "image_url": job.get("original_image_url"),
            "images": [job.get("original_image_url")] if job.get("original_image_url") else []
        }

        brand = job.get("brand") or {} if use_bk else {}

        await self._update_job(job_id, {
            "status": "queued",
            "progress": 0,
            "stage": "Retrying reel generation"
        })

        task = asyncio.create_task(self._process_reel_generation(job_id, str(user_id), product, brand, request))
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)
        return True

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
            creation_mode = getattr(request, "creation_mode", "product_image") or "product_image"

            product_name = product.get("name", "Product")
            product_desc = product.get("description", "")
            product_category = product.get("category", "") or request.category or "Commercial Product"

            # -------------------------------------------------------------
            # Stage A: Visual Asset Acquisition & Enhancement
            # -------------------------------------------------------------
            raw_image = request.image_url or request.product_image_url or product.get("image_url")
            primary_image = raw_image
            original_image = raw_image
            enhanced_image = None

            # 1. Product Image Mode: Handle optional AI image enhancement
            if creation_mode == "product_image" and raw_image:
                if getattr(request, "enhance_image", False):
                    await self._update_job(job_id, {
                        "status": "enhancing_image",
                        "progress": 10,
                        "stage": "Enhancing product lighting and visual presentation"
                    })
                    enh_result = await self.enhancement_service.enhance_image(
                        image_url_or_path=raw_image,
                        prompt=request.enhancement_prompt or request.additional_instructions,
                        product_name=product_name,
                        category=product_category,
                        skip_enhancement=False
                    )
                    if enh_result.get("success") and enh_result.get("enhanced"):
                        enhanced_image = enh_result.get("enhanced_image_url")
                        primary_image = enhanced_image
                        logger.info(f"Using enhanced image for Reel: {enhanced_image}")
                    await self._update_job(job_id, {
                        "original_image_url": original_image,
                        "enhanced_image_url": enhanced_image
                    })
                else:
                    await self._update_job(job_id, {
                        "original_image_url": original_image,
                        "enhanced_image_url": original_image
                    })

            # 2. Text Prompt Mode: Synthesize realistic product visual from description
            from app.ai.image.generator import ImageGenerator
            image_gen = ImageGenerator(
                api_url=getattr(settings, "IMAGE_API_URL", "https://api.openai.com/v1/images/generations"),
                api_key=getattr(settings, "IMAGE_API_KEY", "your_api_key_here")
            )

            if not primary_image or creation_mode == "text_prompt":
                await self._update_job(job_id, {
                    "status": "generating_product_visual",
                    "progress": 15,
                    "stage": "Generating authentic product visual from description"
                })
                img_prompt = f"{product_name} {product_category} {product_desc} {request.additional_instructions or ''}".strip()
                img_res = await image_gen.generate(prompt=img_prompt, scene_idx=0)
                primary_image = img_res.get("image_url")
                if not primary_image:
                    raise Exception("Image generation service is currently unavailable. Please provide a product image or try again later.")
                original_image = primary_image

            product_images = [primary_image]
            if product.get("images") and isinstance(product["images"], list):
                product_images.extend([img for img in product["images"] if img and isinstance(img, str) and img != primary_image])

            # -------------------------------------------------------------
            # Stage B: Gemini Intelligent Storyboard Planning
            # -------------------------------------------------------------
            await self._update_job(job_id, {
                "status": "generating_script",
                "progress": 25,
                "stage": "Planning commercial storyboard with Gemini"
            })
            
            use_bk = getattr(request, "use_brand_kit", False) and bool(brand and any(brand.values()))
            script = await self.script_service.generate_script(
                product=product,
                brand=brand if use_bk else {},
                objective=request.campaign_objective or request.objective,
                platform=request.platform,
                duration=request.duration,
                language=request.language,
                tone=request.voice_tone or request.tone,
                offer=request.offer_text or request.offer,
                additional_instruction=request.additional_instructions or request.additional_instruction,
                generation_mode=gen_mode,
                festival_theme=fest_theme,
                use_brand_kit=use_bk
            )
            
            # Ensure viral hook components are present and locked to this product
            hook_text = script.hook or ""
            hook_headline = getattr(script, "hook_headline", None)
            hook_highlight = getattr(script, "hook_highlight", None)
            if not hook_headline or not hook_highlight:
                if "?" in hook_text:
                    parts = hook_text.split("?", 1)
                    hook_headline = parts[0].strip() + "?"
                    hook_highlight = parts[1].strip() if len(parts) > 1 and parts[1].strip() else f"{product_name} ✨"
                elif "!" in hook_text:
                    parts = hook_text.split("!", 1)
                    hook_headline = parts[0].strip() + "!"
                    hook_highlight = parts[1].strip() if len(parts) > 1 and parts[1].strip() else f"Discover {product_name} ✨"
                elif len(hook_text.split()) > 2:
                    words = hook_text.split()
                    hook_headline = " ".join(words[:2])
                    hook_highlight = " ".join(words[2:])
                else:
                    hook_headline = "Meet the new..."
                    hook_highlight = f"{product_name} 🔥"
                script.hook_headline = hook_headline
                script.hook_highlight = hook_highlight

            # Persist intermediate script status
            await self._update_job(job_id, {
                "script": script.model_dump(mode="json"),
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
            
            # -------------------------------------------------------------
            # Stage C: Voiceover & Audio Configuration
            # -------------------------------------------------------------
            audio_url = None
            voiceover_mode = (request.voiceover_mode or "ai").lower()

            if voiceover_mode == "none":
                logger.info(f"Reel job {job_id}: Voiceover disabled by user request.")
            elif voiceover_mode == "uploaded" and (request.uploaded_audio_url or request.uploaded_audio_id):
                audio_url = request.uploaded_audio_url or request.uploaded_audio_id
                logger.info(f"Reel job {job_id}: Using user uploaded audio track: {audio_url}")
            else:
                # Generate AI TTS voiceover
                full_voiceover = " ".join([scene.voiceover for scene in script.scenes if scene.voiceover])
                if not full_voiceover.strip():
                    full_voiceover = f"Check out {product_name}! {request.offer_text or request.offer or 'Available now.'}"

                await self._update_job(job_id, {
                    "status": "generating_voiceover",
                    "progress": 40,
                    "stage": "Generating voiceover narration"
                })
                try:
                    audio_url = await self.voice_provider.generate_audio(
                        text=full_voiceover,
                        language=script.language or request.language or "Hinglish",
                        voice=request.voice,
                        speed=1.05 if (request.voice_tone or request.tone or "").lower() == "energetic" else 1.0
                    )
                except Exception as voice_err:
                    logger.warning(f"Voice generation failed: {voice_err}. Falling back to mock audio.")
                    from app.ai.providers.voice_provider import MockVoiceProvider
                    audio_url = await MockVoiceProvider().generate_audio(
                        text=full_voiceover,
                        language=script.language or request.language or "Hinglish"
                    )

            # -------------------------------------------------------------
            # Stage D: Video Generation with AI Engine or Dynamic Motion
            # -------------------------------------------------------------
            await self._update_job(job_id, {
                "status": "rendering_video",
                "progress": 55,
                "stage": "Generating dynamic video scenes"
            })

            # Formulate the best video prompt from the user prompt or creative plan
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
            video_provider_setting = getattr(settings, "VIDEO_PROVIDER", "mock").lower()

            if video_provider_setting != "mock":
                try:
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
                        "stage": "Rendering realistic video with AI Video Engine",
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
                    logger.info(f"Video engine successfully produced video: {veo_video_url}")

                except (VeoQuotaError, VeoModelError, VeoError) as veo_err:
                    veo_fallback_reason = str(veo_err)
                    logger.warning(f"Video generation note: {veo_fallback_reason}")
                    await self._update_job(job_id, {
                        "provider": "veo_fallback_composer",
                        "provider_status": "quota_exhausted_fallback" if "429" in veo_fallback_reason else "fallback",
                        "provider_error": veo_fallback_reason,
                        "stage": "Rendering cinematic dynamic scenes"
                    })

                except Exception as unk_err:
                    veo_fallback_reason = str(unk_err)
                    logger.warning(f"Video call exception: {unk_err}")
                    await self._update_job(job_id, {
                        "provider": "veo_fallback_composer",
                        "provider_status": "fallback",
                        "provider_error": veo_fallback_reason,
                        "stage": "Rendering cinematic dynamic scenes"
                    })
            else:
                logger.info("VIDEO_PROVIDER is set to 'mock'. Using dynamic cinematic scene composer.")
                await self._update_job(job_id, {
                    "progress": 65,
                    "stage": "Rendering cinematic dynamic scenes",
                    "provider": "veo_fallback_composer",
                    "provider_status": "mock_mode"
                })

            # Assemble visual segments for composition:
            if veo_video_url:
                video_segments = [veo_video_url]
            else:
                await self._update_job(job_id, {"progress": 70, "stage": "Preparing aesthetic scene visuals"})
                video_segments = [
                    product_images[i % len(product_images)]
                    for i in range(len(script.scenes))
                ]

            # -------------------------------------------------------------
            # Stage E: Compose Final 9:16 Video (Audio mixing, captions, BGM)
            # -------------------------------------------------------------
            await self._update_job(job_id, {
                "status": "composing",
                "progress": 85,
                "stage": "Composing final reel with synchronized audio & captions"
            })
            
            b_colors = {
                "primary": brand.get("primary_color", "#7928CA"),
                "secondary": brand.get("secondary_color"),
                "accent": brand.get("accent_color")
            } if use_bk else None
            b_font = (brand.get("heading_font") or brand.get("font")) if use_bk else None
            b_logo = brand.get("logo_url") if use_bk else None

            final_video_url = await self.composer.compose_reel(
                video_segments=video_segments,
                audio_url=audio_url,
                brand_colors=b_colors,
                font_family=b_font,
                logo_url=b_logo,
                script=script,
                product_name=product_name,
                music_style=getattr(request, "music_style", "cinematic"),
                captions_enabled=getattr(request, "captions_enabled", True),
                voiceover_mode=voiceover_mode
            )

            if not final_video_url:
                raise Exception("Failed to compose final video")

            # -------------------------------------------------------------
            # Stage F: Quality Validation & Completion
            # -------------------------------------------------------------
            validation_report = await self.quality_validator.validate_video(
                video_path=final_video_url,
                expected_duration=float(request.duration)
            )
            logger.info(f"Reel job {job_id} quality report: {validation_report}")

            await self._update_job(job_id, {
                "status": "completed",
                "progress": 100,
                "stage": "Completed",
                "video_url": final_video_url,   
                "thumbnail_url": primary_image,      
                "audio_url": audio_url,
                "original_image_url": original_image,
                "enhanced_image_url": enhanced_image,
                "product_name": product_name,
                "product_category": product_category,
                "product_description": product_desc,
                "quality_report": validation_report,
                "motion_classification": validation_report.get("classification"),
                "motion_score": validation_report.get("motion_score"),
                "diversity_score": validation_report.get("diversity_score"),
                "use_brand_kit": use_bk,
                "brand_kit_applied": use_bk,
                "brand": brand if use_bk else None,
            })
            logger.info(f"Reel job {job_id} successfully completed for product: {product_name} (motion: {validation_report.get('classification')}, use_brand_kit={use_bk})")
            
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
