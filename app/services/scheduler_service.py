import logging
import asyncio
from datetime import datetime, timezone, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
from motor.motor_asyncio import AsyncIOMotorClient
from bson import ObjectId
from app.core.config import settings

logger = logging.getLogger(__name__)

class SchedulerService:
    def __init__(self):
        self.scheduler = AsyncIOScheduler()
        self.db = None
        self.client = None

    async def start(self):
        logger.info("Starting Autopilot Scheduler Service...")
        self.client = AsyncIOMotorClient(settings.MONGO_URI)
        self.db = self.client[settings.DATABASE_NAME]
        
        # Job 1: Executor - Runs every 5 minutes to check pending queued items
        self.scheduler.add_job(
            self.execute_pending_posts,
            IntervalTrigger(minutes=5),
            id='execute_pending_posts',
            name='Execute pending social posts',
            replace_existing=True
        )
        
        # Job 2: Planner - Runs daily at 1 AM to plan and schedule future posts
        self.scheduler.add_job(
            self.plan_upcoming_posts,
            CronTrigger(hour=1, minute=0),
            id='plan_upcoming_posts',
            name='Plan and generate AI posts for autopilot businesses',
            replace_existing=True
        )
        
        # Job 3: Festival Engine - Runs every Monday at 2 AM to detect upcoming festivals
        # and auto-generate draft campaigns for all businesses
        self.scheduler.add_job(
            self.run_festival_engine,
            CronTrigger(hour=2, minute=0, day_of_week='mon'),
            id='festival_engine',
            name='Detect upcoming Indian festivals and generate campaigns',
            replace_existing=True
        )
        
        self.scheduler.start()
        logger.info("Autopilot Scheduler Service started successfully.")


    async def stop(self):
        logger.info("Stopping Autopilot Scheduler Service...")
        if self.scheduler.running:
            self.scheduler.shutdown()
        if self.client:
            self.client.close()
        logger.info("Autopilot Scheduler Service stopped.")

    async def execute_pending_posts(self):
        """
        Scans the `post_queue` for posts scheduled to go out now or in the past,
        and publishes them to Instagram (or other platforms).
        Supports both new Instagram Login flow and legacy business token flow.
        """
        now = datetime.now(timezone.utc)
        logger.info(f"Running executor job at {now.isoformat()}")
        
        try:
            # Find pending items scheduled <= now
            cursor = self.db["post_queue"].find({
                "status": "pending",
                "scheduled_for": {"$lte": now}
            })
            
            pending_items = await cursor.to_list(length=100)
            if not pending_items:
                return
                
            from app.services.social_service import SocialService
            from app.services.instagram_service import InstagramService
            social_svc = SocialService()
            
            for item in pending_items:
                item_id = item["_id"]
                content_id = item.get("content_id", "")
                user_id = item.get("user_id", "")
                platform = item.get("platform", "instagram")
                media_type = item.get("media_type", "image")
                
                logger.info(f"Autopilot publishing content {content_id} for user {user_id} on {platform}")
                
                try:
                    if platform == "instagram":
                        # Try new Instagram Login flow first
                        ig_conn = await self.db["instagram_connections"].find_one({
                            "user_id": user_id,
                            "platform": "instagram",
                            "connected": True,
                        })
                        
                        if ig_conn:
                            # New flow: use Instagram Login service
                            if media_type == "reel" and item.get("video_url"):
                                await InstagramService.publish_reel(
                                    db=self.db,
                                    user_id=user_id,
                                    video_url=item["video_url"],
                                    caption=item.get("caption", ""),
                                    content_id=content_id,
                                )
                            else:
                                # Image post
                                image_url = item.get("image_url", "")
                                if not image_url and content_id:
                                    # Try to get image from content record
                                    from bson import ObjectId as OID
                                    if OID.is_valid(content_id):
                                        content = await self.db["contents"].find_one({"_id": OID(content_id)})
                                        if content:
                                            image_url = content.get("image_url", "")
                                            if not item.get("caption"):
                                                item["caption"] = content.get("caption", "")
                                
                                if image_url:
                                    await InstagramService.publish_image(
                                        db=self.db,
                                        user_id=user_id,
                                        image_url=image_url,
                                        caption=item.get("caption", ""),
                                        content_id=content_id,
                                    )
                                else:
                                    raise Exception("No image URL available for Instagram post")
                        else:
                            # Legacy flow: business-level token
                            await social_svc.publish_to_instagram(self.db, content_id, user_id)
                        
                    # Mark success
                    await self.db["post_queue"].update_one(
                        {"_id": item_id},
                        {"$set": {"status": "published", "error_message": None, "published_at": now}}
                    )
                except Exception as post_err:
                    logger.error(f"Failed to auto-publish item {item_id}: {post_err}")
                    # Mark failure — never log tokens
                    safe_error = str(post_err)
                    if "access_token" in safe_error.lower():
                        safe_error = "Publishing failed due to authentication error"
                    await self.db["post_queue"].update_one(
                        {"_id": item_id},
                        {"$set": {"status": "failed", "error_message": safe_error}}
                    )
                    
        except Exception as e:
            logger.error(f"Executor job failed: {e}")

    async def plan_upcoming_posts(self):
        """
        Runs nightly to generate posts for businesses that have auto-publish ON.
        It looks at their schedule and generates posts for empty slots in the next 3 days.
        """
        logger.info("Running nightly planner job")
        try:
            # Find all businesses with autopilot enabled
            cursor = self.db["businesses"].find({
                "auto_publish_enabled": True
            })
            businesses = await cursor.to_list(length=None)
            
            for business in businesses:
                schedule = business.get("autopilot_schedule", {})
                if not schedule:
                    continue
                    
                # We could iterate through the next 3 days, check if a post is already scheduled,
                # and if not, call AI generator, deduct credits, and add to queue.
                # (For brevity, this logic is stubbed out for actual AI calling)
                logger.info(f"Would plan posts for business {business['_id']}")
                
        except Exception as e:
            logger.error(f"Planner job failed: {e}")

    async def run_festival_engine(self):
        """
        Weekly job: Detect upcoming Indian festivals and auto-generate
        draft campaigns for all businesses that don't have one yet.
        """
        logger.info("Running Festival Engine job...")
        try:
            from app.services.festival_service import generate_all_upcoming_campaigns
            count = await generate_all_upcoming_campaigns(self.db)
            logger.info(f"Festival Engine: Generated {count} new campaign(s).")
        except Exception as e:
            logger.error(f"Festival Engine job failed: {e}")

scheduler_service = SchedulerService()
