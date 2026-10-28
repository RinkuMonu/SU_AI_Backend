import asyncio
from datetime import datetime, timezone
import io
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, unquote, urljoin, urlparse

from bson import ObjectId
from fastapi import HTTPException, status
import httpx
from PIL import Image

from app.core.config import settings
from app.schemas.google_maps_onboarding import (
    GoogleMapsCategoryRequest,
    GoogleMapsOnboardingCompleteResponse,
    GoogleMapsOnboardingState,
    GoogleMapsPhotoItem,
    GoogleMapsPhotosResponse,
    GoogleMapsPlaceItem,
    GoogleMapsProfileRequest,
    GoogleMapsResolveResponse,
    GoogleMapsSearchResponse,
    GoogleMapsWebsiteRequest,
    SelectGoogleMapsBusinessRequest,
)
from app.utils.url_validator import normalize_website_url

logger = logging.getLogger(__name__)

MAX_PHOTO_SELECTION = 15
MAX_IMAGE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB
ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}

# Simple in-memory LRU cache to reduce provider calls and preserve quota
_SEARCH_CACHE: Dict[str, Tuple[float, Any]] = {}
_DETAILS_CACHE: Dict[str, Tuple[float, Any]] = {}
CACHE_TTL_SECONDS = 3600  # 1 hour


class GoogleMapsOnboardingService:
    """
    Production-ready service orchestrating the Google Maps onboarding workflow:
    1. Business search and place resolution via Google Places API (New)
    2. Google Maps URL resolution (short links, place URLs, coordinate markers)
    3. Multi-collection business persistence (businesses, brand_kits, users)
    4. Optional website step with normalization
    5. Category & subcategory taxonomy validation
    6. Profile customization (promotion goals, USPs, target audience)
    7. Secure logo and photo uploads (up to 15 assets)
    8. Centralized state resumption and transition to Social Connectivity (Step 3)
    """

    @classmethod
    def _get_api_key(cls) -> str:
        """Retrieves and verifies the active Google Maps API key from settings or environment."""
        key = settings.get_google_maps_api_key()
        if not key:
            key = os.getenv("GOOGLE_MAPS_API_KEY") or os.getenv("GOOGLE_MAP_API_KEY") or ""
        return key.strip()

    # -------------------------------------------------------------------------
    # 1. Search and URL Resolution
    # -------------------------------------------------------------------------

    @classmethod
    async def search_businesses(
        cls,
        query: str,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
        radius: float = 50000.0
    ) -> GoogleMapsSearchResponse:
        """
        Searches businesses using Google Places API (New) text search.
        Normalizes input and returns standardized GoogleMapsPlaceItem models.
        """
        clean_query = query.strip()
        if len(clean_query) < 2:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Search query must contain at least 2 characters."
            )

        # If query looks like a Google Maps URL, resolve it directly
        if clean_query.startswith("http://") or clean_query.startswith("https://"):
            resolve_res = await cls.resolve_maps_url(clean_query)
            if resolve_res.success and resolve_res.place:
                return GoogleMapsSearchResponse(
                    success=True,
                    total=1,
                    query=clean_query,
                    places=[resolve_res.place]
                )

        cache_key = f"{clean_query.lower()}_{latitude}_{longitude}_{radius}"
        now = datetime.now(timezone.utc).timestamp()
        if cache_key in _SEARCH_CACHE:
            cached_time, cached_data = _SEARCH_CACHE[cache_key]
            if now - cached_time < CACHE_TTL_SECONDS:
                return cached_data

        api_key = cls._get_api_key()
        if not api_key:
            logger.error("GOOGLE_MAPS_API_KEY is not configured.")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Google Maps service is temporarily unconfigured. Please contact support."
            )

        endpoint = "https://places.googleapis.com/v1/places:searchText"
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": api_key,
            "X-Goog-FieldMask": (
                "places.id,places.displayName,places.formattedAddress,places.addressComponents,"
                "places.location,places.rating,places.userRatingCount,places.websiteUri,"
                "places.nationalPhoneNumber,places.photos,places.types,places.googleMapsUri"
            )
        }

        payload: Dict[str, Any] = {"textQuery": clean_query}
        if latitude is not None and longitude is not None:
            payload["locationBias"] = {
                "circle": {
                    "center": {"latitude": latitude, "longitude": longitude},
                    "radius": float(radius)
                }
            }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(endpoint, headers=headers, json=payload)
                if resp.status_code == 429:
                    raise HTTPException(
                        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                        detail="Google Maps search rate limit reached. Please wait a few moments and try again."
                    )
                elif resp.status_code >= 400:
                    err_body = resp.text
                    logger.warning(f"Google Places API error ({resp.status_code}): {err_body}")
                    # Handle invalid or denied requests gracefully
                    if "REQUEST_DENIED" in err_body or "API_KEY" in err_body:
                        raise HTTPException(
                            status_code=status.HTTP_502_BAD_GATEWAY,
                            detail="Google Maps API credentials error. Please verify project API enablement."
                        )
                    raise HTTPException(
                        status_code=status.HTTP_502_BAD_GATEWAY,
                        detail="Failed to retrieve businesses from Google Maps. Please retry with a shop name."
                    )

                data = resp.json()
                raw_places = data.get("places", [])
                items: List[GoogleMapsPlaceItem] = []
                for p in raw_places:
                    item = cls._format_place_item(p)
                    if item:
                        items.append(item)

                res_model = GoogleMapsSearchResponse(
                    success=True,
                    total=len(items),
                    query=clean_query,
                    places=items
                )
                _SEARCH_CACHE[cache_key] = (now, res_model)
                return res_model

        except HTTPException:
            raise
        except httpx.TimeoutException:
            logger.warning(f"Google Maps search timed out for query '{clean_query}'.")
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="Google Maps search connection timed out. Please check your network and retry."
            )
        except Exception as e:
            logger.error(f"Unexpected error in Google Maps search: {e}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"An error occurred while searching Google Maps: {str(e)}"
            )

    @classmethod
    async def resolve_maps_url(cls, raw_url: str) -> GoogleMapsResolveResponse:
        """
        Resolves short Google Maps URLs (maps.app.goo.gl, goo.gl/maps) or full web place URLs
        into a matching verified Google Place.
        """
        clean_url = raw_url.strip()
        parsed = urlparse(clean_url)
        host = parsed.netloc.lower()

        # Validate that URL belongs to a supported Google Maps domain
        supported_domains = ["maps.google.com", "google.com", "www.google.com", "maps.app.goo.gl", "goo.gl"]
        if not any(host == d or host.endswith(f".{d}") for d in supported_domains):
            return GoogleMapsResolveResponse(
                success=False,
                message="The provided URL is not a recognized Google Maps link. Please enter a valid Google Maps URL or search by business name."
            )

        # 1. Expand shortlinks if necessary
        expanded_url = clean_url
        if any(short in host for short in ["maps.app.goo.gl", "goo.gl"]):
            try:
                headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
                async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
                    resp = await client.get(clean_url, headers=headers)
                    expanded_url = str(resp.url)
            except Exception as e:
                logger.warning(f"Could not expand shortlink '{clean_url}': {e}")

        # 2. Extract Place name and coordinates from expanded URL
        place_name = None
        lat, lng = None, None

        # Pattern: /maps/place/Business+Name/@lat,lng,zoom/data=...
        m_place = re.search(r"/maps/place/([^/@?]+)", expanded_url)
        if m_place:
            place_name = unquote(m_place.group(1)).replace("+", " ").strip()

        # Pattern: Coordinates @26.9485759,75.7362716
        m_coords = re.search(r"@(-?\d+\.\d+),(-?\d+\.\d+)", expanded_url)
        if m_coords:
            try:
                lat, lng = float(m_coords.group(1)), float(m_coords.group(2))
            except Exception:
                pass

        # Query param ?q= or ?query=
        exp_parsed = urlparse(expanded_url)
        qs = parse_qs(exp_parsed.query)
        if not place_name:
            q_val = qs.get("q", [None])[0] or qs.get("query", [None])[0]
            if q_val:
                place_name = unquote(q_val).replace("+", " ").strip()

        if not place_name and not (lat and lng):
            return GoogleMapsResolveResponse(
                success=False,
                message="Could not extract business information from this Google Maps link. Please search by shop or business name instead."
            )

        # 3. Search Google Places with extracted query and coordinates
        search_query = place_name or f"business near {lat},{lng}"
        try:
            search_res = await cls.search_businesses(
                query=search_query,
                latitude=lat,
                longitude=lng,
                radius=1000.0 if (lat and lng) else 50000.0
            )
            if search_res.places:
                top_match = search_res.places[0]
                return GoogleMapsResolveResponse(
                    success=True,
                    message="Business successfully resolved from Google Maps link.",
                    place=top_match,
                    resolved_query=search_query
                )
            else:
                return GoogleMapsResolveResponse(
                    success=False,
                    message=f"No matching business found for '{search_query}'. Please search manually by business name."
                )
        except Exception as e:
            return GoogleMapsResolveResponse(
                success=False,
                message=f"Could not resolve business from link: {str(e)}"
            )

    @classmethod
    async def get_place_details(cls, place_id: str) -> GoogleMapsPlaceItem:
        """
        Fetches detailed information for a specific place_id via Places API (New).
        """
        clean_id = place_id.strip()
        now = datetime.now(timezone.utc).timestamp()
        if clean_id in _DETAILS_CACHE:
            cached_time, cached_item = _DETAILS_CACHE[clean_id]
            if now - cached_time < CACHE_TTL_SECONDS:
                return cached_item

        api_key = cls._get_api_key()
        if not api_key:
            raise HTTPException(status_code=500, detail="Google Maps API key is not configured.")

        endpoint = f"https://places.googleapis.com/v1/places/{clean_id}"
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": api_key,
            "X-Goog-FieldMask": (
                "id,displayName,formattedAddress,addressComponents,location,rating,userRatingCount,"
                "websiteUri,nationalPhoneNumber,internationalPhoneNumber,photos,types,googleMapsUri"
            )
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(endpoint, headers=headers)
                if resp.status_code == 404:
                    raise HTTPException(status_code=404, detail=f"Google Place '{clean_id}' not found.")
                resp.raise_for_status()
                data = resp.json()
                item = cls._format_place_item(data)
                if not item:
                    raise HTTPException(status_code=404, detail="Could not format place details.")

                _DETAILS_CACHE[clean_id] = (now, item)
                return item

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error fetching place details for {clean_id}: {e}")
            raise HTTPException(status_code=502, detail=f"Failed to fetch place details: {str(e)}")

    @classmethod
    def _format_place_item(cls, data: Dict[str, Any]) -> Optional[GoogleMapsPlaceItem]:
        """Maps raw Google Places (New) dictionary to a standardized GoogleMapsPlaceItem model."""
        if not data or not data.get("id"):
            return None

        place_id = data["id"]
        name_obj = data.get("displayName") or {}
        b_name = name_obj.get("text") or data.get("name") or "Unnamed Business"

        formatted_address = data.get("formattedAddress") or ""
        location = data.get("location") or {}
        lat = location.get("latitude")
        lng = location.get("longitude")

        rating = data.get("rating")
        review_count = data.get("userRatingCount")
        website = data.get("websiteUri")
        phone = data.get("nationalPhoneNumber") or data.get("internationalPhoneNumber")
        types = data.get("types") or []
        g_url = data.get("googleMapsUri") or f"https://www.google.com/maps/place/?q=place_id:{place_id}"

        # Parse city, state, country, postal code from addressComponents
        city, state, country, postal_code = None, None, None, None
        components = data.get("addressComponents") or []
        for c in components:
            c_types = c.get("types") or []
            val = c.get("longText") or c.get("shortText")
            if "locality" in c_types or "postal_town" in c_types:
                city = val
            elif "administrative_area_level_1" in c_types:
                state = val
            elif "country" in c_types:
                country = val
            elif "postal_code" in c_types:
                postal_code = val

        # Fallback city extraction from formatted address
        if not city and formatted_address:
            parts = [p.strip() for p in formatted_address.split(",")]
            if len(parts) >= 3:
                city = parts[-3]

        # Extract photo references and build proxy URLs (never exposing API key)
        photo_refs: List[str] = []
        photo_urls: List[str] = []
        raw_photos = data.get("photos") or []
        for p in raw_photos:
            p_name = p.get("name")
            if p_name:
                photo_refs.append(p_name)
                proxy_url = settings.get_public_url(f"/api/v1/onboarding/google-maps/photo?photo_name={p_name}")
                photo_urls.append(proxy_url)

        return GoogleMapsPlaceItem(
            place_id=place_id,
            business_name=b_name,
            formatted_address=formatted_address,
            latitude=lat,
            longitude=lng,
            rating=rating,
            review_count=review_count,
            website=website,
            phone_number=phone,
            city=city,
            state=state,
            country=country,
            postal_code=postal_code,
            types=types,
            photo_references=photo_refs,
            photos=photo_urls,
            google_maps_url=g_url
        )

    # -------------------------------------------------------------------------
    # 2. Multi-Collection Selected Business Persistence
    # -------------------------------------------------------------------------

    @classmethod
    async def select_business(
        cls,
        db,
        user_id: str,
        payload: SelectGoogleMapsBusinessRequest
    ) -> GoogleMapsOnboardingState:
        """
        Stores the selected Google Maps business against the authenticated user's workspace,
        populates the business profile, and advances the flow to Step 2 (Website).
        """
        now = datetime.now(timezone.utc)
        clean_pid = payload.place_id.strip()

        # If full details were not provided in payload, fetch from Google Places
        place_item: Optional[GoogleMapsPlaceItem] = None
        if not payload.business_name or not payload.formatted_address:
            try:
                place_item = await cls.get_place_details(clean_pid)
            except Exception as e:
                logger.warning(f"Could not fetch full details for place {clean_pid}: {e}")

        b_name = payload.business_name or (place_item.business_name if place_item else "My Business")
        addr = payload.formatted_address or (place_item.formatted_address if place_item else "")
        lat = payload.latitude if payload.latitude is not None else (place_item.latitude if place_item else None)
        lng = payload.longitude if payload.longitude is not None else (place_item.longitude if place_item else None)
        rating = payload.rating if payload.rating is not None else (place_item.rating if place_item else None)
        review_count = payload.review_count if payload.review_count is not None else (place_item.review_count if place_item else None)
        website = payload.website or (place_item.website if place_item else None)
        phone = payload.phone_number or (place_item.phone_number if place_item else None)
        city = payload.city or (place_item.city if place_item else None)
        state = payload.state or (place_item.state if place_item else None)
        country = payload.country or (place_item.country if place_item else None)
        postal_code = payload.postal_code or (place_item.postal_code if place_item else None)
        types = payload.types or (place_item.types if place_item else [])
        photos = payload.photos or (place_item.photos if place_item else [])
        maps_url = payload.google_maps_url or (place_item.google_maps_url if place_item else f"https://www.google.com/maps/place/?q=place_id:{clean_pid}")

        # 1. Update businesses collection
        business_updates: Dict[str, Any] = {
            "owner_id": str(user_id),
            "name": b_name,
            "business_name": b_name,
            "google_maps_place_id": clean_pid,
            "google_maps_url": maps_url,
            "formatted_address": addr,
            "address": addr,
            "online_presence": "google_maps",
            "business_type": "google_maps",
            "updated_at": now
        }
        if city:
            business_updates["city"] = city
        if state:
            business_updates["state"] = state
        if country:
            business_updates["country"] = country
        if postal_code:
            business_updates["postal_code"] = postal_code
        if lat is not None and lng is not None:
            business_updates["latitude"] = lat
            business_updates["longitude"] = lng
            business_updates["coordinates"] = {"lat": lat, "lng": lng}
        if rating is not None:
            business_updates["rating"] = rating
        if review_count is not None:
            business_updates["review_count"] = review_count
        if phone:
            business_updates["phone"] = phone
            business_updates["phone_number"] = phone
        if website:
            business_updates["google_maps_website"] = website

        # Do not overwrite existing user-entered website with empty response
        existing_bus = await db["businesses"].find_one({"$or": [{"owner_id": str(user_id)}, {"ownerId": str(user_id)}]}) or {}
        if website and not existing_bus.get("website"):
            business_updates["website"] = website

        business_updates["owner_id"] = str(user_id)
        business_updates["ownerId"] = str(user_id)
        business_updates["user_id"] = str(user_id)
        await db["businesses"].update_one(
            {"$or": [
                {"owner_id": str(user_id)},
                {"ownerId": str(user_id)},
                {"user_id": str(user_id)},
                {"userId": str(user_id)}
            ]},
            {
                "$set": business_updates,
                "$setOnInsert": {
                    "location": city or "India",
                    "created_at": now
                }
            },
            upsert=True
        )

        # 2. Update brand_kits collection
        brand_updates: Dict[str, Any] = {
            "business_id": str(user_id),
            "owner_id": str(user_id),
            "user_id": str(user_id),
            "brand_name": b_name,
            "business_name": b_name,
            "updated_at": now
        }
        if city:
            brand_updates["city"] = city
        if website and not existing_bus.get("website"):
            brand_updates["website"] = website

        await db["brand_kits"].update_one(
            {"$or": [{"owner_id": str(user_id)}, {"user_id": str(user_id)}]},
            {
                "$set": brand_updates,
                "$setOnInsert": {
                    "created_at": now
                }
            },
            upsert=True
        )

        # 3. Update users / pending_users collection - always persist to canonical users collection
        user_updates_map = {
            "online_presence": "google_maps",
            "google_maps_url": maps_url,
            "onboarding_step": 2,
            "onboarding_status": "in_progress",
            "updated_at": now
        }
        if ObjectId.is_valid(user_id):
            await db["users"].update_one(
                {"_id": ObjectId(user_id)},
                {"$set": user_updates_map}
            )
            if await db["pending_users"].find_one({"_id": ObjectId(user_id)}):
                await db["pending_users"].update_one(
                    {"_id": ObjectId(user_id)},
                    {"$set": user_updates_map}
                )

        # 4. Upsert session in google_maps_onboarding_jobs
        photo_models = [
            GoogleMapsPhotoItem(url=u, type="google_maps", source="google_maps", selected=True)
            for u in photos[:15]
        ]
        selected_place = GoogleMapsPlaceItem(
            place_id=clean_pid,
            business_name=b_name,
            formatted_address=addr,
            latitude=lat,
            longitude=lng,
            rating=rating,
            review_count=review_count,
            website=website,
            phone_number=phone,
            city=city,
            state=state,
            country=country,
            postal_code=postal_code,
            types=types,
            photos=photos,
            google_maps_url=maps_url
        )

        job_doc = {
            "user_id": str(user_id),
            "place_id": clean_pid,
            "current_step": "website",
            "onboarding_step_number": 2,
            "is_completed": False,
            "selected_business": selected_place.model_dump(),
            "website": website or existing_bus.get("website"),
            "website_skipped": False,
            "photos": [p.model_dump() for p in photo_models],
            "selected_photo_urls": [p.url for p in photo_models[:4]],
            "updated_at": now
        }

        await db["google_maps_onboarding_jobs"].update_one(
            {"user_id": str(user_id)},
            {"$set": job_doc, "$setOnInsert": {"created_at": now}},
            upsert=True
        )

        return await cls.get_onboarding_state(db, user_id)

    # -------------------------------------------------------------------------
    # 3. Website Step (Save / Skip)
    # -------------------------------------------------------------------------

    @classmethod
    async def save_website(
        cls,
        db,
        user_id: str,
        payload: GoogleMapsWebsiteRequest
    ) -> GoogleMapsOnboardingState:
        """
        Saves user-entered website or records explicit skip choice, and advances to Step 3 (Category).
        """
        now = datetime.now(timezone.utc)
        norm_url = None
        skipped = payload.skip

        if payload.website_url:
            norm_url = normalize_website_url(payload.website_url)
            # Ensure valid scheme
            if not norm_url.startswith("http://") and not norm_url.startswith("https://"):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Please provide a valid website address starting with http:// or https://"
                )
            skipped = False

        # Update businesses & brand_kits if URL provided
        if norm_url:
            await db["businesses"].update_one(
                {"$or": [{"owner_id": str(user_id)}, {"ownerId": str(user_id)}]},
                {"$set": {"owner_id": str(user_id), "website": norm_url, "website_url": norm_url, "updated_at": now}},
                upsert=True
            )
            await db["brand_kits"].update_one(
                {"$or": [{"owner_id": str(user_id)}, {"user_id": str(user_id)}]},
                {"$set": {"owner_id": str(user_id), "website": norm_url, "updated_at": now}},
                upsert=True
            )

        # Update session
        update_set: Dict[str, Any] = {
            "current_step": "category",
            "onboarding_step_number": 3,
            "website_skipped": skipped,
            "updated_at": now
        }
        if norm_url:
            update_set["website"] = norm_url

        await db["google_maps_onboarding_jobs"].update_one(
            {"user_id": str(user_id)},
            {"$set": update_set},
            upsert=True
        )

        return await cls.get_onboarding_state(db, user_id)

    # -------------------------------------------------------------------------
    # 4. Business Category & Subcategory Step
    # -------------------------------------------------------------------------

    @classmethod
    async def save_category(
        cls,
        db,
        user_id: str,
        payload: GoogleMapsCategoryRequest
    ) -> GoogleMapsOnboardingState:
        """
        Persists validated category and subcategory selection, and advances to Step 4 (Profile).
        """
        now = datetime.now(timezone.utc)
        cat_name = (payload.category or "").strip()
        sub_cat = (payload.sub_category or "").strip() or None

        if not cat_name:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Business category is required."
            )

        # Update businesses
        await db["businesses"].update_one(
            {"$or": [{"owner_id": str(user_id)}, {"ownerId": str(user_id)}]},
            {"$set": {
                "owner_id": str(user_id),
                "category": cat_name,
                "business_category": cat_name,
                "sub_category": sub_cat,
                "custom_category": payload.custom_category,
                "custom_subcategory": payload.custom_subcategory,
                "updated_at": now
            }},
            upsert=True
        )

        # Update brand_kits
        await db["brand_kits"].update_one(
            {"$or": [{"owner_id": str(user_id)}, {"user_id": str(user_id)}]},
            {"$set": {
                "owner_id": str(user_id),
                "business_category": cat_name,
                "sub_category": sub_cat,
                "updated_at": now
            }},
            upsert=True
        )

        # Update session
        await db["google_maps_onboarding_jobs"].update_one(
            {"user_id": str(user_id)},
            {"$set": {
                "category": cat_name,
                "sub_category": sub_cat,
                "current_step": "profile",
                "onboarding_step_number": 4,
                "updated_at": now
            }},
            upsert=True
        )

        return await cls.get_onboarding_state(db, user_id)

    # -------------------------------------------------------------------------
    # 5. Business Profile Details Step
    # -------------------------------------------------------------------------

    @classmethod
    async def save_profile_details(
        cls,
        db,
        user_id: str,
        payload: GoogleMapsProfileRequest
    ) -> GoogleMapsOnboardingState:
        """
        Saves required business name, promotion goal, target audience, USPs, and logo reference.
        Supports partial updates without erasing previously saved optional values.
        """
        now = datetime.now(timezone.utc)
        b_name = payload.business_name.strip()
        promo_goal = payload.promotion_goal.strip()

        if not b_name:
            raise HTTPException(status_code=400, detail="Business name is required.")
        if not promo_goal:
            raise HTTPException(status_code=400, detail="What should we promote? is required.")

        # Load existing profile in case optional fields are omitted
        job = await db["google_maps_onboarding_jobs"].find_one({"user_id": str(user_id)}) or {}
        existing_profile = job.get("profile") or {}

        target_aud = payload.target_audience or existing_profile.get("target_audience")
        diffs = payload.differentiators if payload.differentiators is not None else existing_profile.get("differentiators", [])
        logo = payload.logo_url or existing_profile.get("logo_url")
        tagline = payload.tagline or promo_goal or existing_profile.get("tagline")
        prods = payload.products_services if payload.products_services is not None else existing_profile.get("products_services", [])

        profile_dict = {
            "business_name": b_name,
            "promotion_goal": promo_goal,
            "target_audience": target_aud,
            "differentiators": diffs,
            "logo_url": logo,
            "tagline": tagline,
            "products_services": prods
        }

        # Update businesses
        bus_update: Dict[str, Any] = {
            "name": b_name,
            "business_name": b_name,
            "promotion_goal": promo_goal,
            "target_customer": target_aud,
            "differentiators": diffs,
            "tagline": tagline,
            "products_services": prods,
            "updated_at": now
        }
        if logo:
            bus_update["logo_url"] = logo

        await db["businesses"].update_one(
            {"$or": [{"owner_id": str(user_id)}, {"ownerId": str(user_id)}]},
            {"$set": bus_update},
            upsert=True
        )

        # Update brand_kits
        kit_update: Dict[str, Any] = {
            "brand_name": b_name,
            "tagline": tagline,
            "target_audience": target_aud,
            "differentiators": diffs,
            "products_services": prods,
            "updated_at": now
        }
        if logo:
            kit_update["logo_url"] = logo

        await db["brand_kits"].update_one(
            {"$or": [{"owner_id": str(user_id)}, {"user_id": str(user_id)}]},
            {"$set": kit_update},
            upsert=True
        )

        # Update session
        await db["google_maps_onboarding_jobs"].update_one(
            {"user_id": str(user_id)},
            {"$set": {
                "profile": profile_dict,
                "current_step": "photos",
                "onboarding_step_number": 5,
                "updated_at": now
            }},
            upsert=True
        )

        return await cls.get_onboarding_state(db, user_id)

    # -------------------------------------------------------------------------
    # 6. Logo & Photo Management (Upload, Proxy, Selection, Removal)
    # -------------------------------------------------------------------------

    @classmethod
    async def upload_logo(
        cls,
        db,
        user_id: str,
        file_bytes: bytes,
        filename: str,
        content_type: str
    ) -> str:
        """Validates and stores a business logo image, enforcing 10MB limit and format checks."""
        if len(file_bytes) > MAX_IMAGE_SIZE_BYTES:
            raise HTTPException(status_code=400, detail="Logo file exceeds maximum size limit of 10 MB.")

        try:
            img = Image.open(io.BytesIO(file_bytes))
            img.verify()
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid image file: {str(e)}")

        import uuid
        ext = os.path.splitext(filename)[1].lower()
        if ext not in ALLOWED_IMAGE_EXTENSIONS:
            ext = ".png"

        upload_dir = os.path.join("uploads", "business_logos")
        os.makedirs(upload_dir, exist_ok=True)
        unique_name = f"logo_{user_id}_{uuid.uuid4().hex[:10]}{ext}"
        target_path = os.path.join(upload_dir, unique_name)

        with open(target_path, "wb") as f:
            f.write(file_bytes)

        public_url = settings.get_public_url(f"/uploads/business_logos/{unique_name}")

        now = datetime.now(timezone.utc)
        await db["businesses"].update_one(
            {"$or": [{"owner_id": str(user_id)}, {"ownerId": str(user_id)}]},
            {"$set": {"owner_id": str(user_id), "logo_url": public_url, "updated_at": now}},
            upsert=True
        )
        await db["brand_kits"].update_one(
            {"$or": [{"owner_id": str(user_id)}, {"user_id": str(user_id)}]},
            {"$set": {"owner_id": str(user_id), "logo_url": public_url, "updated_at": now}},
            upsert=True
        )
        await db["google_maps_onboarding_jobs"].update_one(
            {"user_id": str(user_id)},
            {"$set": {"profile.logo_url": public_url, "updated_at": now}}
        )

        return public_url

    @classmethod
    async def remove_logo(cls, db, user_id: str) -> None:
        """Removes the saved logo from the user's business profile and brand kit."""
        now = datetime.now(timezone.utc)
        await db["businesses"].update_one(
            {"$or": [{"owner_id": str(user_id)}, {"ownerId": str(user_id)}]},
            {"$set": {"logo_url": None, "updated_at": now}}
        )
        await db["brand_kits"].update_one(
            {"$or": [{"owner_id": str(user_id)}, {"user_id": str(user_id)}]},
            {"$set": {"logo_url": None, "updated_at": now}}
        )
        await db["google_maps_onboarding_jobs"].update_one(
            {"user_id": str(user_id)},
            {"$set": {"profile.logo_url": None, "updated_at": now}}
        )

    @classmethod
    async def upload_photo(
        cls,
        db,
        user_id: str,
        file_bytes: bytes,
        filename: str,
        content_type: str
    ) -> GoogleMapsPhotoItem:
        """Validates and appends a user-uploaded image to the Google Maps photo gallery."""
        if len(file_bytes) > MAX_IMAGE_SIZE_BYTES:
            raise HTTPException(status_code=400, detail="Uploaded file exceeds 10 MB limit.")

        width, height = None, None
        try:
            img = Image.open(io.BytesIO(file_bytes))
            img.verify()
            width, height = img.size
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid image format: {str(e)}")

        import uuid
        ext = os.path.splitext(filename)[1].lower()
        if ext not in ALLOWED_IMAGE_EXTENSIONS:
            ext = ".jpg"

        upload_dir = os.path.join("uploads", "onboarding_photos")
        os.makedirs(upload_dir, exist_ok=True)
        unique_name = f"gmaps_{user_id}_{uuid.uuid4().hex[:10]}{ext}"
        target_path = os.path.join(upload_dir, unique_name)

        with open(target_path, "wb") as f:
            f.write(file_bytes)

        public_url = settings.get_public_url(f"/uploads/onboarding_photos/{unique_name}")
        photo_item = GoogleMapsPhotoItem(
            url=public_url,
            alt=os.path.splitext(filename)[0] or "Business Photo",
            type="user_upload",
            source="user_upload",
            selected=True,
            width=width,
            height=height
        )

        now = datetime.now(timezone.utc)
        await db["google_maps_onboarding_jobs"].update_one(
            {"user_id": str(user_id)},
            {
                "$push": {"photos": photo_item.model_dump()},
                "$addToSet": {"selected_photo_urls": public_url},
                "$set": {"updated_at": now}
            },
            upsert=True
        )

        return photo_item

    @classmethod
    async def get_photos(cls, db, user_id: str) -> GoogleMapsPhotosResponse:
        """Retrieves all photos (Maps references + uploads) and current selection state."""
        job = await db["google_maps_onboarding_jobs"].find_one({"user_id": str(user_id)}) or {}
        raw_photos = job.get("photos") or []
        selected_urls = job.get("selected_photo_urls") or []

        photo_models: List[GoogleMapsPhotoItem] = []
        for p in raw_photos:
            item = GoogleMapsPhotoItem(**p) if isinstance(p, dict) else p
            item.selected = (item.url in selected_urls)
            photo_models.append(item)

        return GoogleMapsPhotosResponse(
            success=True,
            photos=photo_models,
            selected_photo_urls=selected_urls,
            max_selection_limit=MAX_PHOTO_SELECTION,
            total_photos=len(photo_models),
            selected_count=len(selected_urls)
        )

    @classmethod
    async def select_photos(
        cls,
        db,
        user_id: str,
        selected_urls: List[str]
    ) -> GoogleMapsPhotosResponse:
        """Saves chosen photo selections, strictly enforcing the 15 photo limit."""
        if len(selected_urls) > MAX_PHOTO_SELECTION:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"You can select a maximum of {MAX_PHOTO_SELECTION} photos."
            )

        now = datetime.now(timezone.utc)
        await db["google_maps_onboarding_jobs"].update_one(
            {"user_id": str(user_id)},
            {"$set": {"selected_photo_urls": selected_urls, "updated_at": now}},
            upsert=True
        )

        # Update businesses & brand_kits
        await db["businesses"].update_one(
            {"$or": [{"owner_id": str(user_id)}, {"ownerId": str(user_id)}]},
            {"$set": {"selected_photos": selected_urls, "updated_at": now}}
        )
        await db["brand_kits"].update_one(
            {"$or": [{"owner_id": str(user_id)}, {"user_id": str(user_id)}]},
            {"$set": {"selected_photos": selected_urls, "updated_at": now}}
        )

        return await cls.get_photos(db, user_id)

    @classmethod
    async def remove_photo(cls, db, user_id: str, photo_url: str) -> GoogleMapsPhotosResponse:
        """Removes a photo from the gallery and unselects it."""
        now = datetime.now(timezone.utc)
        await db["google_maps_onboarding_jobs"].update_one(
            {"user_id": str(user_id)},
            {
                "$pull": {
                    "photos": {"url": photo_url},
                    "selected_photo_urls": photo_url
                },
                "$set": {"updated_at": now}
            }
        )
        await db["businesses"].update_one(
            {"$or": [{"owner_id": str(user_id)}, {"ownerId": str(user_id)}]},
            {"$pull": {"selected_photos": photo_url}, "$set": {"updated_at": now}}
        )
        await db["brand_kits"].update_one(
            {"$or": [{"owner_id": str(user_id)}, {"user_id": str(user_id)}]},
            {"$pull": {"selected_photos": photo_url}, "$set": {"updated_at": now}}
        )

        return await cls.get_photos(db, user_id)

    @classmethod
    async def proxy_google_photo(cls, photo_name: str, max_width: int = 800) -> Tuple[Optional[str], Optional[bytes], str]:
        """
        Safely proxies Google Places (New) photo media without exposing GOOGLE_MAPS_API_KEY.
        Returns: (redirect_location, image_bytes, content_type)
        """
        api_key = cls._get_api_key()
        if not api_key:
            raise HTTPException(status_code=500, detail="Google Maps API key not configured.")

        # In Places API (New), endpoint is: https://places.googleapis.com/v1/{photo_name}/media?maxWidthPx=...&key=...
        clean_name = photo_name.strip()
        if not clean_name.startswith("places/"):
            clean_name = f"places/{clean_name}"

        url = f"https://places.googleapis.com/v1/{clean_name}/media?maxWidthPx={max_width}&key={api_key}"
        try:
            async with httpx.AsyncClient(timeout=8.0, follow_redirects=False) as client:
                resp = await client.get(url)
                if resp.status_code in (302, 303, 307):
                    loc = resp.headers.get("location")
                    if loc:
                        return loc, None, "text/plain"
                elif resp.status_code == 200:
                    ct = resp.headers.get("content-type", "image/jpeg")
                    return None, resp.content, ct
                raise HTTPException(status_code=resp.status_code, detail="Could not retrieve photo from Google Places.")
        except HTTPException:
            raise
        except Exception as e:
            logger.warning(f"Error fetching photo media for {photo_name}: {e}")
            raise HTTPException(status_code=502, detail="Failed to fetch image from Google Maps.")

    # -------------------------------------------------------------------------
    # 7. Centralized State Resumption and Completion
    # -------------------------------------------------------------------------

    @classmethod
    async def get_onboarding_state(cls, db, user_id: str) -> GoogleMapsOnboardingState:
        """
        Returns full saved Google Maps onboarding state for resuming across refreshes or logins.
        """
        job = await db["google_maps_onboarding_jobs"].find_one({"user_id": str(user_id)}) or {}
        bus = await db["businesses"].find_one({"$or": [{"owner_id": str(user_id)}, {"ownerId": str(user_id)}]}) or {}

        current_step = job.get("current_step") or ("completed" if bus.get("onboarding_status") == "completed" else "business_select")
        step_num = job.get("onboarding_step_number") or 1
        is_comp = bool(job.get("is_completed") or current_step == "completed")

        place_raw = job.get("selected_business")
        place_model = GoogleMapsPlaceItem(**place_raw) if place_raw else None

        # Reconcile website & category from businesses collection if edited
        website = bus.get("website") or job.get("website")
        category = bus.get("category") or job.get("category")
        sub_cat = bus.get("sub_category") or job.get("sub_category")

        # Profile reconciliation
        profile_data = job.get("profile") or {}
        if bus.get("name"):
            profile_data["business_name"] = bus.get("name")
        if bus.get("promotion_goal"):
            profile_data["promotion_goal"] = bus.get("promotion_goal")
        if bus.get("logo_url"):
            profile_data["logo_url"] = bus.get("logo_url")
        if bus.get("target_customer"):
            profile_data["target_audience"] = bus.get("target_customer")
        if bus.get("differentiators"):
            profile_data["differentiators"] = bus.get("differentiators")

        # Photos
        photos_raw = job.get("photos") or []
        selected_urls = job.get("selected_photo_urls") or bus.get("selected_photos") or []
        photo_models = [GoogleMapsPhotoItem(**p) if isinstance(p, dict) else p for p in photos_raw]

        return GoogleMapsOnboardingState(
            success=True,
            current_step=current_step,
            onboarding_step_number=step_num,
            is_completed=is_comp,
            selected_business=place_model,
            website=website,
            website_skipped=bool(job.get("website_skipped")),
            category=category,
            sub_category=sub_cat,
            profile=profile_data if profile_data else None,
            photos=photo_models,
            selected_photo_urls=selected_urls,
            created_at=job.get("created_at"),
            updated_at=job.get("updated_at")
        )

    @classmethod
    async def complete_onboarding(cls, db, user_id: str) -> GoogleMapsOnboardingCompleteResponse:
        """
        Validates required steps (place selected, category assigned, profile filled),
        marks Google Maps onboarding complete, and transitions stepper to Step 3 (Social Connectivity).
        """
        now = datetime.now(timezone.utc)
        state = await cls.get_onboarding_state(db, user_id)

        # Enforce prerequisite validation
        if not state.selected_business or not state.selected_business.place_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Please select your business on Google Maps before completing onboarding."
            )
        if not state.category:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Please select a business category before completing onboarding."
            )
        if not state.profile or not state.profile.get("promotion_goal"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Please complete the 'What should we promote?' profile field before continuing."
            )

        # 1. Update session in google_maps_onboarding_jobs
        await db["google_maps_onboarding_jobs"].update_one(
            {"user_id": str(user_id)},
            {"$set": {
                "current_step": "completed",
                "onboarding_step_number": 5,
                "is_completed": True,
                "updated_at": now
            }}
        )

        # 2. Advance user stepper to Step 3 (Social Connectivity) - always update canonical users collection
        user_step_updates = {
            "onboarding_step": 3,
            "online_presence": "google_maps",
            "onboarding_status": "in_progress",
            "updated_at": now
        }
        if ObjectId.is_valid(user_id):
            await db["users"].update_one(
                {"_id": ObjectId(user_id)},
                {"$set": user_step_updates}
            )
            if await db["pending_users"].find_one({"_id": ObjectId(user_id)}):
                await db["pending_users"].update_one(
                    {"_id": ObjectId(user_id)},
                    {"$set": user_step_updates}
                )

        # 3. Update business record
        await db["businesses"].update_one(
            {"$or": [{"owner_id": str(user_id)}, {"ownerId": str(user_id)}, {"user_id": str(user_id)}]},
            {
                "$set": {
                    "owner_id": str(user_id),
                    "ownerId": str(user_id),
                    "user_id": str(user_id),
                    "online_presence": "google_maps",
                    "onboarding_step": 3,
                    "updated_at": now
                },
                "$setOnInsert": {
                    "name": "My Business",
                    "business_name": "My Business",
                    "created_at": now
                }
            },
            upsert=True
        )

        bus_doc = await db["businesses"].find_one({"$or": [{"owner_id": str(user_id)}, {"ownerId": str(user_id)}]}) or {}
        kit_doc = await db["brand_kits"].find_one({"$or": [{"owner_id": str(user_id)}, {"user_id": str(user_id)}]}) or {}
        bus_doc.pop("_id", None)
        kit_doc.pop("_id", None)

        return GoogleMapsOnboardingCompleteResponse(
            success=True,
            message="Google Maps onboarding completed successfully. Proceed to Social Media Connectivity.",
            next_step="social_connectivity",
            onboarding_route="/onboarding?step=social_connectivity",
            business=bus_doc,
            brand_kit=kit_doc
        )
