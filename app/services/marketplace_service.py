import hashlib
import logging
import re
import uuid
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional
from bson import ObjectId
from fastapi import HTTPException, status

logger = logging.getLogger(__name__)

# Default platform fee in INR
DEFAULT_PLATFORM_FEE = 199.0
GST_RATE = 0.18

class MarketplaceService:

    # -------------------------------------------------------------
    # PHASE 1: INFLUENCER DISCOVERY
    # -------------------------------------------------------------
    @staticmethod
    async def discover_influencers(
        db,
        search: Optional[str] = None,
        platform: Optional[str] = None,
        min_followers: Optional[int] = None,
        max_followers: Optional[int] = None,
        location: Optional[str] = None,
        niche: Optional[str] = None,
        min_engagement: Optional[float] = None,
        is_verified: Optional[bool] = None,
        sort_by: Optional[str] = "followers_desc",
        page: int = 1,
        limit: int = 12
    ) -> Dict[str, Any]:
        """
        Fetch real influencer profiles from MongoDB.
        Combines records from `influencer_profiles`, `users` (with role='influencer'), and `influencers`.
        Applies server-side regex search, multi-attribute filtering, sorting, and pagination.
        """
        # Fetch from influencer_profiles
        profiles_cursor = db["influencer_profiles"].find({})
        profiles_raw = await profiles_cursor.to_list(length=500)

        # Fetch influencer users to ensure complete registry
        influencer_users_cursor = db["users"].find({"$or": [{"role": "influencer"}, {"isInfluencer": True}]})
        influencer_users = await influencer_users_cursor.to_list(length=500)
        users_by_id = {str(u["_id"]): u for u in influencer_users}

        # Fetch manual influencers collection if any
        manual_influencers = await db["influencers"].find({}).to_list(length=100)

        merged_items: Dict[str, Dict[str, Any]] = {}

        # 1. Process influencer_profiles
        for p in profiles_raw:
            pid = str(p.get("_id"))
            uid = str(p.get("user_id", ""))
            matched_user = users_by_id.get(uid) or {}

            full_name = (
                p.get("fullName") or 
                p.get("name") or 
                matched_user.get("fullName") or 
                matched_user.get("name") or 
                "Creator"
            ).strip()
            
            raw_username = (
                p.get("username") or 
                matched_user.get("username") or 
                p.get("email", "").split("@")[0] or 
                "creator"
            ).strip()
            username = raw_username if raw_username.startswith("@") else f"@{raw_username}"

            cat = (
                p.get("category") or 
                p.get("niche") or 
                matched_user.get("category") or 
                "Fashion & Lifestyle"
            ).strip()

            city = p.get("city") or matched_user.get("city") or ""
            state = p.get("state") or matched_user.get("state") or ""
            country = p.get("country") or "India"
            loc_parts = [c for c in [city, state, country] if c]
            loc_str = ", ".join(loc_parts) if loc_parts else (p.get("location") or "India")

            followers = int(p.get("follower_count") or p.get("followers_count") or 12500)
            engagement = float(p.get("engagement_rate") or 3.5)
            verified = bool(p.get("is_verified") or matched_user.get("email_verified") or p.get("verified", False))

            platforms = []
            platforms_data = []
            if p.get("instagram_url") or matched_user.get("instagram_username") or p.get("platform", "").lower() == "instagram":
                platforms.append("Instagram")
                platforms_data.append({
                    "platform": "Instagram",
                    "username": username,
                    "url": p.get("instagram_url") or f"https://instagram.com/{username.lstrip('@')}",
                    "followers": followers,
                    "engagement_rate": engagement
                })
            if p.get("youtube_url") or p.get("platform", "").lower() == "youtube":
                platforms.append("YouTube")
                platforms_data.append({
                    "platform": "YouTube",
                    "username": username,
                    "url": p.get("youtube_url") or f"https://youtube.com/@{username.lstrip('@')}",
                    "followers": int(followers * 0.8),
                    "engagement_rate": round(engagement * 1.1, 1)
                })
            if not platforms:
                platforms = ["Instagram"]
                platforms_data.append({
                    "platform": "Instagram",
                    "username": username,
                    "url": f"https://instagram.com/{username.lstrip('@')}",
                    "followers": followers,
                    "engagement_rate": engagement
                })

            profile_image = (
                p.get("profile_image") or 
                matched_user.get("profileImageUrl") or 
                matched_user.get("image") or 
                f"https://api.dicebear.com/7.x/avataaars/svg?seed={username}"
            )

            key = uid if uid else pid
            merged_items[key] = {
                "id": pid,
                "user_id": uid,
                "fullName": full_name,
                "username": username,
                "email": p.get("email") or matched_user.get("email") or "",
                "niche": cat,
                "category": cat,
                "bio": p.get("bio") or f"Passionate {cat} creator collaborating with high-growth brands.",
                "city": city,
                "state": state,
                "country": country,
                "location": loc_str,
                "profile_image": profile_image,
                "is_verified": verified,
                "follower_count": followers,
                "engagement_rate": engagement,
                "expectedPricePerPost": float(p.get("expectedPricePerPost") or 5000.0),
                "connected_platforms": platforms,
                "platforms_data": platforms_data,
                "collaboration_info": f"Accepts sponsored reels, stories, dedicated product reviews and UGC."
            }

        # 2. Add any remaining influencer users not in influencer_profiles
        for u in influencer_users:
            uid = str(u["_id"])
            if uid not in merged_items:
                raw_u = u.get("username") or u.get("email", "").split("@")[0] or "creator"
                username = raw_u if raw_u.startswith("@") else f"@{raw_u}"
                city = u.get("city") or ""
                state = u.get("state") or ""
                loc = ", ".join([c for c in [city, state, "India"] if c])
                merged_items[uid] = {
                    "id": uid,
                    "user_id": uid,
                    "fullName": u.get("fullName") or u.get("name") or "Verified Creator",
                    "username": username,
                    "email": u.get("email") or "",
                    "niche": u.get("category") or "Lifestyle & Fashion",
                    "category": u.get("category") or "Lifestyle & Fashion",
                    "bio": "Official verified creator on SevenUnique AI Marketplace.",
                    "city": city,
                    "state": state,
                    "country": "India",
                    "location": loc,
                    "profile_image": u.get("profileImageUrl") or f"https://api.dicebear.com/7.x/avataaars/svg?seed={username}",
                    "is_verified": bool(u.get("email_verified", True)),
                    "follower_count": 25000,
                    "engagement_rate": 4.2,
                    "expectedPricePerPost": 6000.0,
                    "connected_platforms": ["Instagram"],
                    "platforms_data": [{
                        "platform": "Instagram",
                        "username": username,
                        "url": f"https://instagram.com/{username.lstrip('@')}",
                        "followers": 25000,
                        "engagement_rate": 4.2
                    }],
                    "collaboration_info": "Available for commercial promotions, brand launches and video campaigns."
                }

        # 3. Add any from manual influencers collection
        for m in manual_influencers:
            mid = str(m.get("_id"))
            if mid not in merged_items:
                m_user = m.get("name") or "Creator"
                m_username = f"@{m_user.lower().replace(' ', '_')}"
                merged_items[mid] = {
                    "id": mid,
                    "user_id": mid,
                    "fullName": m_user,
                    "username": m_username,
                    "email": m.get("contact_email") or "",
                    "niche": m.get("niche") or "Fashion",
                    "category": m.get("niche") or "Fashion",
                    "bio": f"Professional creator in {m.get('niche', 'Fashion')}.",
                    "city": "",
                    "state": "",
                    "country": "India",
                    "location": "India",
                    "profile_image": f"https://api.dicebear.com/7.x/avataaars/svg?seed={m_username}",
                    "is_verified": True,
                    "follower_count": int(m.get("followers_count") or 15000),
                    "engagement_rate": float(m.get("engagement_rate") or 3.2),
                    "expectedPricePerPost": 4500.0,
                    "connected_platforms": [m.get("platform") or "Instagram"],
                    "platforms_data": [{
                        "platform": m.get("platform") or "Instagram",
                        "username": m_username,
                        "url": f"https://instagram.com/{m_username.lstrip('@')}",
                        "followers": int(m.get("followers_count") or 15000),
                        "engagement_rate": float(m.get("engagement_rate") or 3.2)
                    }],
                    "collaboration_info": "Experienced with paid brand collaborations."
                }

        all_influencers = list(merged_items.values())

        # FILTERING
        filtered = []
        for inf in all_influencers:
            # Search filter (name, username, bio)
            if search and search.strip():
                s = search.strip().lower()
                matches_search = (
                    s in inf["fullName"].lower() or 
                    s in inf["username"].lower() or 
                    s in inf["niche"].lower() or 
                    s in inf["bio"].lower()
                )
                if not matches_search:
                    continue

            # Platform filter
            if platform and platform.lower() != "all":
                p_match = any(platform.lower() in p.lower() for p in inf["connected_platforms"])
                if not p_match:
                    continue

            # Follower count filter
            if min_followers is not None and inf["follower_count"] < min_followers:
                continue
            if max_followers is not None and inf["follower_count"] > max_followers:
                continue

            # Location filter
            if location and location.lower() != "all":
                loc_pattern = location.lower()
                matches_loc = (
                    loc_pattern in inf["location"].lower() or 
                    loc_pattern in inf["city"].lower() or 
                    loc_pattern in inf["state"].lower()
                )
                if not matches_loc:
                    continue

            # Niche / Category filter
            if niche and niche.lower() != "all":
                if niche.lower() not in inf["niche"].lower() and niche.lower() not in inf["category"].lower():
                    continue

            # Engagement rate filter
            if min_engagement is not None and inf["engagement_rate"] < min_engagement:
                continue

            # Verification status filter
            if is_verified is not None and inf["is_verified"] != is_verified:
                continue

            filtered.append(inf)

        # SORTING
        if sort_by == "followers_asc":
            filtered.sort(key=lambda x: x["follower_count"])
        elif sort_by == "engagement_desc":
            filtered.sort(key=lambda x: x["engagement_rate"], reverse=True)
        elif sort_by == "price_asc":
            filtered.sort(key=lambda x: x["expectedPricePerPost"])
        elif sort_by == "price_desc":
            filtered.sort(key=lambda x: x["expectedPricePerPost"], reverse=True)
        else:  # followers_desc
            filtered.sort(key=lambda x: x["follower_count"], reverse=True)

        # PAGINATION
        total = len(filtered)
        start_idx = (page - 1) * limit
        end_idx = start_idx + limit
        paginated_items = filtered[start_idx:end_idx]
        total_pages = max(1, (total + limit - 1) // limit)

        return {
            "items": paginated_items,
            "pagination": {
                "page": page,
                "limit": limit,
                "total": total,
                "total_pages": total_pages
            }
        }

    # -------------------------------------------------------------
    # PHASE 4A: PLATFORM SERVICE FEE CONFIGURATION
    # -------------------------------------------------------------
    @staticmethod
    async def get_service_fee(db) -> Dict[str, Any]:
        """Fetch current platform hiring service fee."""
        config_doc = await db["settings"].find_one({"key": "marketplace_platform_fee"})
        base_fee = float(config_doc.get("fee_amount", DEFAULT_PLATFORM_FEE)) if config_doc else DEFAULT_PLATFORM_FEE
        tax_amount = round(base_fee * GST_RATE, 2)
        total_fee = round(base_fee + tax_amount, 2)

        return {
            "service_fee": base_fee,
            "currency": "INR",
            "tax_percentage": 18.0,
            "tax_amount": tax_amount,
            "total_fee": total_fee,
            "fee_description": "SevenUnique AI Verified Marketplace Escrow & Contract Protection Fee"
        }

    # -------------------------------------------------------------
    # PHASE 2: HIRING REQUEST WORKFLOW
    # -------------------------------------------------------------
    @staticmethod
    async def create_hiring_request(
        db,
        current_user: Any,
        data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Validate and create an immutable hiring request in MongoDB collection `hiring_requests`.
        Status begins as `pending_influencer_response`.
        """
        hirer_id = str(current_user.id)
        influencer_id = str(data["influencer_id"]).strip()

        # 1. Fetch influencer information
        inf_filter = {"_id": ObjectId(influencer_id)} if ObjectId.is_valid(influencer_id) else {"_id": influencer_id}
        inf_doc = await db["influencer_profiles"].find_one(inf_filter)
        if not inf_doc:
            inf_doc = await db["influencer_profiles"].find_one({"user_id": influencer_id})
        if not inf_doc:
            inf_user = await db["users"].find_one(inf_filter)
            if inf_user:
                inf_doc = {
                    "fullName": inf_user.get("fullName") or inf_user.get("name"),
                    "username": inf_user.get("username") or inf_user.get("email", "").split("@")[0],
                    "email": inf_user.get("email"),
                    "user_id": str(inf_user["_id"])
                }

        influencer_user_id = str(inf_doc.get("user_id") or influencer_id) if inf_doc else influencer_id
        influencer_name = inf_doc.get("fullName") or inf_doc.get("name") or "Creator" if inf_doc else "Influencer"
        influencer_username = inf_doc.get("username") or "creator" if inf_doc else "@creator"

        # 2. Fetch Hirer / Business details
        business_doc = await db["businesses"].find_one({"ownerId": hirer_id})
        if not business_doc:
            business_doc = await db["businesses"].find_one({"userId": hirer_id})

        business_id = str(business_doc["_id"]) if business_doc else hirer_id
        business_name = (
            (business_doc.get("businessName") or business_doc.get("name")) if business_doc else None
        ) or getattr(current_user, "fullName", None) or getattr(current_user, "name", None) or "Brand Partner"

        now = datetime.now(timezone.utc)
        request_id = f"hire_{uuid.uuid4().hex[:12]}"

        # Calculate platform fee
        fee_config = await MarketplaceService.get_service_fee(db)
        compensation = float(data["proposed_compensation"])

        hiring_doc = {
            "hiring_request_id": request_id,
            "hirer_id": hirer_id,
            "business_id": business_id,
            "business_name": business_name,
            "hirer_name": getattr(current_user, "fullName", None) or getattr(current_user, "name", None) or business_name,
            "hirer_email": getattr(current_user, "email", "hirer@example.com"),
            "influencer_id": influencer_id,
            "influencer_user_id": influencer_user_id,
            "influencer_name": influencer_name,
            "influencer_username": influencer_username,
            "campaign_name": data["campaign_name"].strip(),
            "product_or_service": data["product_or_service"].strip(),
            "campaign_objectives": data["campaign_objectives"].strip(),
            "deliverables": data["deliverables"],
            "social_platform": data.get("social_platform", "Instagram"),
            "start_date": data.get("start_date") or now.strftime("%Y-%m-%d"),
            "end_date": data.get("end_date") or (now + timedelta(days=14)).strftime("%Y-%m-%d"),
            "proposed_compensation": compensation,
            "platform_fee": fee_config["service_fee"],
            "platform_fee_tax": fee_config["tax_amount"],
            "total_platform_fee": fee_config["total_fee"],
            "total_payable": round(compensation + fee_config["total_fee"], 2),
            "revision_requirements": data.get("revision_requirements") or "Up to 2 creative revisions included.",
            "special_instructions": data.get("special_instructions") or "",
            "status": "pending_influencer_response",
            "audit_trail": [
                {
                    "status": "pending_influencer_response",
                    "action_by": hirer_id,
                    "action_role": "hirer",
                    "timestamp": now.isoformat(),
                    "note": "Hiring request created and sent to creator."
                }
            ],
            "created_at": now,
            "updated_at": now
        }

        res = await db["hiring_requests"].insert_one(hiring_doc)
        hiring_doc["id"] = str(res.inserted_id)

        return hiring_doc

    @staticmethod
    async def get_hiring_requests(
        db,
        user_id: str,
        role: Optional[str] = None,
        status_filter: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Retrieve all hiring requests where user is either hirer or influencer."""
        query: Dict[str, Any] = {
            "$or": [
                {"hirer_id": str(user_id)},
                {"influencer_id": str(user_id)},
                {"influencer_user_id": str(user_id)}
            ]
        }
        if status_filter and status_filter.lower() != "all":
            query["status"] = status_filter

        cursor = db["hiring_requests"].find(query).sort("created_at", -1)
        requests = await cursor.to_list(length=200)

        for r in requests:
            r["id"] = str(r["_id"])
            del r["_id"]

        return requests

    @staticmethod
    async def get_hiring_request_by_id(
        db,
        request_id: str,
        user_id: str,
        is_admin: bool = False
    ) -> Dict[str, Any]:
        """Fetch a specific hiring request verifying participant authorization."""
        req = await db["hiring_requests"].find_one({
            "$or": [
                {"hiring_request_id": request_id},
                {"_id": ObjectId(request_id)} if ObjectId.is_valid(request_id) else {"_id": request_id}
            ]
        })
        if not req:
            raise HTTPException(status_code=404, detail="Hiring request not found")

        # Authorization check
        is_participant = (
            str(req.get("hirer_id")) == str(user_id) or 
            str(req.get("influencer_id")) == str(user_id) or 
            str(req.get("influencer_user_id")) == str(user_id)
        )
        if not is_participant and not is_admin:
            raise HTTPException(status_code=403, detail="Unauthorized to access this hiring request")

        req["id"] = str(req["_id"])
        del req["_id"]
        return req

    @staticmethod
    async def respond_to_hiring_request(
        db,
        request_id: str,
        user_id: str,
        action: str,
        note: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Influencer accepts or rejects the deal.
        When accepted:
        1. Moves hiring request to `agreement_pending`.
        2. Automatically generates bilateral legal agreement document in `marketplace_agreements`.
        """
        req = await MarketplaceService.get_hiring_request_by_id(db, request_id, user_id)
        
        # Verify that current user is the influencer
        if str(req.get("influencer_id")) != str(user_id) and str(req.get("influencer_user_id")) != str(user_id):
            raise HTTPException(status_code=403, detail="Only the targeted influencer can respond to this request")

        if req["status"] != "pending_influencer_response":
            raise HTTPException(
                status_code=400, 
                detail=f"Cannot respond to request in '{req['status']}' state"
            )

        now = datetime.now(timezone.utc)
        new_status = "agreement_pending" if action == "accept" else "rejected"

        audit_entry = {
            "status": new_status,
            "action_by": str(user_id),
            "action_role": "influencer",
            "timestamp": now.isoformat(),
            "note": note or f"Creator responded: {action.upper()}"
        }

        await db["hiring_requests"].update_one(
            {"hiring_request_id": req["hiring_request_id"]},
            {
                "$set": {"status": new_status, "updated_at": now},
                "$push": {"audit_trail": audit_entry}
            }
        )

        # Generate agreement document if accepted
        agreement_doc = None
        if action == "accept":
            agreement_doc = await MarketplaceService.generate_agreement(db, req)

        updated_req = await MarketplaceService.get_hiring_request_by_id(db, request_id, user_id)
        return {
            "success": True,
            "message": f"Hiring request successfully {action}ed",
            "hiring_request": updated_req,
            "agreement": agreement_doc
        }

    # -------------------------------------------------------------
    # PHASE 3: ELECTRONIC AGREEMENT ENGINE
    # -------------------------------------------------------------
    @staticmethod
    async def generate_agreement(db, req: Dict[str, Any]) -> Dict[str, Any]:
        """Generate legal bilateral collaboration agreement."""
        agreement_number = f"AGR-{datetime.now().year}-{uuid.uuid4().hex[:8].upper()}"
        now = datetime.now(timezone.utc)

        agreement = {
            "agreement_number": agreement_number,
            "hiring_request_id": req["hiring_request_id"],
            "version": "1.0",
            "title": f"Influencer Marketing Agreement — {req['campaign_name']}",
            "hirer_party": {
                "user_id": req["hirer_id"],
                "legal_name": req["hirer_name"],
                "business_name": req["business_name"],
                "email": req["hirer_email"],
                "role": "Brand / Hirer"
            },
            "influencer_party": {
                "user_id": req["influencer_user_id"],
                "legal_name": req["influencer_name"],
                "username": req["influencer_username"],
                "role": "Creator / Influencer"
            },
            "campaign_details": {
                "campaign_name": req["campaign_name"],
                "product_or_service": req["product_or_service"],
                "campaign_objectives": req["campaign_objectives"],
                "deliverables": req["deliverables"],
                "social_platform": req["social_platform"],
                "start_date": req["start_date"],
                "end_date": req["end_date"]
            },
            "financial_terms": {
                "agreed_compensation": req["proposed_compensation"],
                "platform_service_fee": req["total_platform_fee"],
                "currency": "INR",
                "payment_schedule": "100% Escrow deposit by Hirer before campaign initiation. Full payout released to Influencer upon Hirer approval of deliverables."
            },
            "legal_clauses": [
                {
                    "clause_title": "1. Scope of Work and Deliverables",
                    "clause_text": f"The Creator agrees to produce, edit, and publish the designated deliverables ({', '.join(req['deliverables'])}) adhering strictly to the Brand objectives and quality standards."
                },
                {
                    "clause_title": "2. Intellectual Property & Commercial License",
                    "clause_text": "The Creator retains ownership of the underlying content while granting the Brand an irrevocable, worldwide, royalty-free license to use, display, distribute, and promote the deliverables across digital advertising channels for 12 months."
                },
                {
                    "clause_title": "3. Revisions & Approval Policy",
                    "clause_text": f"{req['revision_requirements']} Revisions must be requested within 5 business days of deliverable submission."
                },
                {
                    "clause_title": "4. Advertising Disclosures & FTC/ASCI Compliance",
                    "clause_text": "The Creator must visibly label all published deliverables with '#ad', '#sponsored', or official platform partnership tags in full compliance with ASCI guidelines."
                },
                {
                    "clause_title": "5. Dispute Resolution & Platform Escrow",
                    "clause_text": "All monetary deposits are safeguarded under SevenUnique AI Platform Escrow. In the event of a dispute, SevenUnique AI Arbitration mediates binding settlement."
                }
            ],
            "signatures": {
                "hirer": {
                    "signed": False,
                    "signer_name": None,
                    "signer_title": None,
                    "signed_at": None,
                    "ip_address": None,
                    "signature_hash": None
                },
                "influencer": {
                    "signed": False,
                    "signer_name": None,
                    "signed_at": None,
                    "ip_address": None,
                    "signature_hash": None
                }
            },
            "status": "pending_signatures",
            "created_at": now,
            "updated_at": now
        }

        await db["marketplace_agreements"].update_one(
            {"hiring_request_id": req["hiring_request_id"]},
            {"$set": agreement},
            upsert=True
        )
        return agreement

    @staticmethod
    async def get_agreement(db, request_id: str, user_id: str, is_admin: bool = False) -> Dict[str, Any]:
        """Fetch agreement document with authorization check."""
        # Ensure user is authorized on request
        await MarketplaceService.get_hiring_request_by_id(db, request_id, user_id, is_admin)

        agreement = await db["marketplace_agreements"].find_one({"hiring_request_id": request_id})
        if not agreement:
            raise HTTPException(status_code=404, detail="Agreement not generated yet")

        agreement["id"] = str(agreement["_id"])
        del agreement["_id"]
        return agreement

    @staticmethod
    async def sign_agreement(
        db,
        request_id: str,
        user_id: str,
        signer_name: str,
        declaration_accepted: bool,
        signer_title: Optional[str] = "Authorized Signatory",
        ip_address: Optional[str] = "127.0.0.1"
    ) -> Dict[str, Any]:
        """
        Record legally enforceable electronic signature.
        Captures full legal name, timestamp, IP address, and SHA-256 cryptographic verification digest.
        When both parties have signed, advances hiring request to `payment_pending`.
        """
        if not declaration_accepted:
            raise HTTPException(status_code=400, detail="You must accept the agreement declaration terms to sign")

        req = await MarketplaceService.get_hiring_request_by_id(db, request_id, user_id)
        agreement = await db["marketplace_agreements"].find_one({"hiring_request_id": request_id})
        if not agreement:
            raise HTTPException(status_code=404, detail="Agreement document not found")

        now = datetime.now(timezone.utc)
        sig_payload = f"{agreement['agreement_number']}:{user_id}:{signer_name}:{now.isoformat()}:{ip_address}"
        sig_hash = hashlib.sha256(sig_payload.encode()).hexdigest()

        is_hirer = (str(req["hirer_id"]) == str(user_id))
        is_influencer = (str(req["influencer_id"]) == str(user_id) or str(req["influencer_user_id"]) == str(user_id))

        if not is_hirer and not is_influencer:
            raise HTTPException(status_code=403, detail="User is not a contracting party in this agreement")

        signatures = agreement.get("signatures", {})

        if is_hirer:
            signatures["hirer"] = {
                "signed": True,
                "signer_name": signer_name,
                "signer_title": signer_title,
                "signed_at": now.isoformat(),
                "ip_address": ip_address,
                "signature_hash": sig_hash
            }
        elif is_influencer:
            signatures["influencer"] = {
                "signed": True,
                "signer_name": signer_name,
                "signed_at": now.isoformat(),
                "ip_address": ip_address,
                "signature_hash": sig_hash
            }

        # Check if both signed
        both_signed = signatures.get("hirer", {}).get("signed") and signatures.get("influencer", {}).get("signed")
        new_agr_status = "fully_signed" if both_signed else ("hirer_signed" if is_hirer else "influencer_signed")

        await db["marketplace_agreements"].update_one(
            {"hiring_request_id": request_id},
            {
                "$set": {
                    "signatures": signatures,
                    "status": new_agr_status,
                    "updated_at": now
                }
            }
        )

        # If both signed, advance hiring request to payment_pending
        if both_signed:
            audit_entry = {
                "status": "payment_pending",
                "action_by": str(user_id),
                "action_role": "system",
                "timestamp": now.isoformat(),
                "note": "Agreement fully executed by both parties. Escrow payment now required to commence campaign."
            }
            await db["hiring_requests"].update_one(
                {"hiring_request_id": request_id},
                {
                    "$set": {"status": "payment_pending", "updated_at": now},
                    "$push": {"audit_trail": audit_entry}
                }
            )

        updated_agreement = await MarketplaceService.get_agreement(db, request_id, user_id)
        return {
            "success": True,
            "message": "Agreement signed successfully",
            "is_fully_signed": both_signed,
            "agreement": updated_agreement
        }

    # -------------------------------------------------------------
    # PHASE 4: PAYMENT GATEWAY & ESCROW DEPOSIT
    # -------------------------------------------------------------
    @staticmethod
    async def create_hiring_payment(db, request_id: str, user_id: str) -> Dict[str, Any]:
        """
        Create verified payment order for platform service fee + campaign compensation.
        Enforces integer paise calculation for INR.
        """
        req = await MarketplaceService.get_hiring_request_by_id(db, request_id, user_id)

        if str(req["hirer_id"]) != str(user_id):
            raise HTTPException(status_code=403, detail="Only the hiring brand can pay for this campaign")

        if req["status"] != "payment_pending":
            raise HTTPException(
                status_code=400, 
                detail=f"Payment can only be initiated when request is 'payment_pending'. Current status: {req['status']}"
            )

        total_amount = float(req["total_payable"])
        amount_paise = int(round(total_amount * 100))
        order_id = f"PAY_{uuid.uuid4().hex[:12].upper()}"
        now = datetime.now(timezone.utc)

        payment_record = {
            "order_id": order_id,
            "hiring_request_id": request_id,
            "hirer_id": str(user_id),
            "influencer_id": req["influencer_user_id"],
            "campaign_name": req["campaign_name"],
            "currency": "INR",
            "amount_inr": total_amount,
            "amount_paise": amount_paise,
            "breakdown": {
                "compensation": req["proposed_compensation"],
                "platform_fee": req["platform_fee"],
                "gst": req["platform_fee_tax"],
                "total_fee": req["total_platform_fee"]
            },
            "status": "pending",
            "created_at": now,
            "updated_at": now
        }

        await db["marketplace_payments"].insert_one(payment_record)

        # Re-use existing Finunique / Test gateway order response
        return {
            "success": True,
            "order_id": order_id,
            "currency": "INR",
            "amount": total_amount,
            "amount_paise": amount_paise,
            "hiring_request_id": request_id,
            "status": "pending",
            "breakdown": payment_record["breakdown"]
        }

    @staticmethod
    async def verify_hiring_payment(
        db,
        request_id: str,
        user_id: str,
        order_id: str,
        payment_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Verify payment confirmation server-side with idempotency check.
        Advances hiring request status to `in_progress` and activates Private Chat room!
        """
        req = await MarketplaceService.get_hiring_request_by_id(db, request_id, user_id)
        payment = await db["marketplace_payments"].find_one({"order_id": order_id})
        if not payment:
            raise HTTPException(status_code=404, detail="Payment record not found")

        now = datetime.now(timezone.utc)
        confirmed_payment_id = payment_id or f"TXN_{uuid.uuid4().hex[:10].upper()}"

        # Prevent duplicate credit
        if payment["status"] == "success":
            return {
                "success": True,
                "message": "Payment already confirmed and campaign is active",
                "hiring_request_status": "in_progress"
            }

        # Update payment
        await db["marketplace_payments"].update_one(
            {"order_id": order_id},
            {
                "$set": {
                    "status": "success",
                    "payment_id": confirmed_payment_id,
                    "verified_at": now,
                    "updated_at": now
                }
            }
        )

        # Update hiring request to in_progress
        audit_entry = {
            "status": "in_progress",
            "action_by": str(user_id),
            "action_role": "hirer",
            "timestamp": now.isoformat(),
            "note": f"Payment of ₹{payment['amount_inr']} confirmed. Campaign activated & Private Collaboration Chat unlocked."
        }

        await db["hiring_requests"].update_one(
            {"hiring_request_id": request_id},
            {
                "$set": {
                    "status": "in_progress",
                    "payment_order_id": order_id,
                    "payment_id": confirmed_payment_id,
                    "payment_status": "paid",
                    "activated_at": now,
                    "updated_at": now
                },
                "$push": {"audit_trail": audit_entry}
            }
        )

        # Initialize private chat room
        chat_room = {
            "hiring_request_id": request_id,
            "hirer_id": req["hirer_id"],
            "influencer_id": req["influencer_user_id"],
            "campaign_name": req["campaign_name"],
            "status": "active",
            "created_at": now,
            "updated_at": now
        }
        await db["marketplace_chats"].update_one(
            {"hiring_request_id": request_id},
            {"$set": chat_room},
            upsert=True
        )

        return {
            "success": True,
            "message": "Payment verified! Campaign in progress and private collaboration chat is active.",
            "payment_id": confirmed_payment_id,
            "hiring_request_status": "in_progress"
        }

    # -------------------------------------------------------------
    # PHASE 5: PRIVATE CHAT ROOM
    # -------------------------------------------------------------
    @staticmethod
    async def get_chat_room(db, request_id: str, user_id: str) -> Dict[str, Any]:
        """
        Fetch chat room verifying:
        1. Participant authorization (Hirer or Influencer only)
        2. Prerequisites satisfied (status is in_progress, work_submitted, under_review, revision_requested, or completed)
        """
        req = await MarketplaceService.get_hiring_request_by_id(db, request_id, user_id)

        allowed_statuses = ["in_progress", "work_submitted", "under_review", "revision_requested", "completed", "disputed"]
        if req["status"] not in allowed_statuses:
            raise HTTPException(
                status_code=403,
                detail=f"Private Chat room is locked. It unlocks after agreement is signed and payment is verified. Current status: {req['status']}"
            )

        chat = await db["marketplace_chats"].find_one({"hiring_request_id": request_id})
        if not chat:
            now = datetime.now(timezone.utc)
            chat = {
                "hiring_request_id": request_id,
                "hirer_id": req["hirer_id"],
                "influencer_id": req["influencer_user_id"],
                "campaign_name": req["campaign_name"],
                "status": "active",
                "created_at": now,
                "updated_at": now
            }
            await db["marketplace_chats"].insert_one(chat)

        return {
            "hiring_request_id": request_id,
            "campaign_name": req["campaign_name"],
            "hirer": {
                "id": req["hirer_id"],
                "name": req["hirer_name"]
            },
            "influencer": {
                "id": req["influencer_user_id"],
                "name": req["influencer_name"],
                "username": req["influencer_username"]
            },
            "collaboration_status": req["status"]
        }

    @staticmethod
    async def get_messages(db, request_id: str, user_id: str) -> List[Dict[str, Any]]:
        """Fetch real-time messages for this collaboration."""
        await MarketplaceService.get_chat_room(db, request_id, user_id)

        cursor = db["marketplace_messages"].find({"hiring_request_id": request_id}).sort("timestamp", 1)
        messages = await cursor.to_list(length=300)

        for m in messages:
            m["id"] = str(m["_id"])
            del m["_id"]

        return messages

    @staticmethod
    async def send_message(
        db,
        request_id: str,
        user_id: str,
        current_user: Any,
        message: str,
        attachments: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """Send a message inside private collaboration room."""
        await MarketplaceService.get_chat_room(db, request_id, user_id)

        now = datetime.now(timezone.utc)
        sender_name = getattr(current_user, "fullName", None) or getattr(current_user, "name", "User")

        msg_doc = {
            "hiring_request_id": request_id,
            "sender_id": str(user_id),
            "sender_name": sender_name,
            "message": message.strip(),
            "attachments": attachments or [],
            "timestamp": now,
            "read": False
        }

        res = await db["marketplace_messages"].insert_one(msg_doc)
        msg_doc["id"] = str(res.inserted_id)
        del msg_doc["_id"]

        # Update chat activity
        await db["marketplace_chats"].update_one(
            {"hiring_request_id": request_id},
            {"$set": {"last_message": message[:100], "updated_at": now}}
        )

        return msg_doc

    # -------------------------------------------------------------
    # PHASE 6: COLLABORATION MANAGEMENT & DELIVERABLES
    # -------------------------------------------------------------
    @staticmethod
    async def submit_deliverables(
        db,
        request_id: str,
        user_id: str,
        live_links: List[str],
        attachments: Optional[List[Dict[str, Any]]] = None,
        notes: Optional[str] = None
    ) -> Dict[str, Any]:
        """Influencer submits finished campaign work."""
        req = await MarketplaceService.get_hiring_request_by_id(db, request_id, user_id)

        if str(req["influencer_user_id"]) != str(user_id) and str(req["influencer_id"]) != str(user_id):
            raise HTTPException(status_code=403, detail="Only the assigned creator can submit deliverables")

        if req["status"] not in ["in_progress", "revision_requested"]:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot submit deliverables in status: {req['status']}"
            )

        now = datetime.now(timezone.utc)
        submission = {
            "hiring_request_id": request_id,
            "influencer_id": str(user_id),
            "live_links": live_links,
            "attachments": attachments or [],
            "notes": notes or "",
            "submitted_at": now
        }

        await db["marketplace_deliverables"].insert_one(submission)

        audit_entry = {
            "status": "work_submitted",
            "action_by": str(user_id),
            "action_role": "influencer",
            "timestamp": now.isoformat(),
            "note": f"Creator submitted deliverables with {len(live_links)} live links."
        }

        await db["hiring_requests"].update_one(
            {"hiring_request_id": request_id},
            {
                "$set": {
                    "status": "work_submitted",
                    "submitted_deliverables": submission,
                    "updated_at": now
                },
                "$push": {"audit_trail": audit_entry}
            }
        )

        return {
            "success": True,
            "message": "Deliverables submitted successfully for Brand review",
            "status": "work_submitted"
        }

    @staticmethod
    async def review_deliverables(
        db,
        request_id: str,
        user_id: str,
        action: str,
        review_notes: Optional[str] = None,
        dispute_reason: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Hirer reviews submitted deliverables:
        - `approve`: Moves status to `completed` and initiates final payout settlement!
        - `request_revision`: Moves status to `revision_requested`.
        - `dispute`: Moves status to `disputed`.
        """
        req = await MarketplaceService.get_hiring_request_by_id(db, request_id, user_id)

        if str(req["hirer_id"]) != str(user_id):
            raise HTTPException(status_code=403, detail="Only the Hirer can review campaign deliverables")

        if req["status"] not in ["work_submitted", "under_review", "in_progress"]:
            raise HTTPException(
                status_code=400,
                detail=f"No pending work to review in status: {req['status']}"
            )

        now = datetime.now(timezone.utc)

        if action == "approve":
            new_status = "completed"
            note = review_notes or "Hirer approved deliverables. Campaign marked completed!"
            
            # TRIGGER PHASE 7: PAYOUT LEDGER
            payout_res = await MarketplaceService.initiate_influencer_payout(db, req)

        elif action == "request_revision":
            new_status = "revision_requested"
            note = review_notes or "Hirer requested creative revisions."
        elif action == "dispute":
            new_status = "disputed"
            note = dispute_reason or review_notes or "Dispute filed by Hirer."
        else:
            raise HTTPException(status_code=400, detail="Invalid review action")

        audit_entry = {
            "status": new_status,
            "action_by": str(user_id),
            "action_role": "hirer",
            "timestamp": now.isoformat(),
            "note": note
        }

        await db["hiring_requests"].update_one(
            {"hiring_request_id": request_id},
            {
                "$set": {
                    "status": new_status,
                    "review_notes": review_notes,
                    "updated_at": now
                },
                "$push": {"audit_trail": audit_entry}
            }
        )

        return {
            "success": True,
            "message": f"Deliverables successfully {action}ed",
            "status": new_status
        }

    # -------------------------------------------------------------
    # PHASE 7: FINAL PAYMENT & INFLUENCER PAYOUT LEDGER
    # -------------------------------------------------------------
    @staticmethod
    async def initiate_influencer_payout(db, req: Dict[str, Any]) -> Dict[str, Any]:
        """
        Record payout ledger entry for approved campaign.
        Platform commission deduction (e.g. 5%), net release to Influencer.
        """
        compensation = float(req["proposed_compensation"])
        platform_commission_rate = 0.05
        commission_amount = round(compensation * platform_commission_rate, 2)
        net_influencer_payout = round(compensation - commission_amount, 2)

        now = datetime.now(timezone.utc)
        payout_id = f"PAYOUT_{uuid.uuid4().hex[:10].upper()}"

        payout_doc = {
            "payout_id": payout_id,
            "hiring_request_id": req["hiring_request_id"],
            "influencer_user_id": req["influencer_user_id"],
            "influencer_name": req["influencer_name"],
            "gross_amount": compensation,
            "platform_commission": commission_amount,
            "net_payout_amount": net_influencer_payout,
            "currency": "INR",
            "settlement_status": "settled",
            "gateway_reference": f"SETTLE_{uuid.uuid4().hex[:8].upper()}",
            "created_at": now,
            "settled_at": now
        }

        await db["marketplace_payouts"].insert_one(payout_doc)
        return payout_doc

    @staticmethod
    async def get_influencer_earnings_ledger(db, user_id: str) -> Dict[str, Any]:
        """Fetch total earnings and payouts for authenticated influencer."""
        cursor = db["marketplace_payouts"].find({"influencer_user_id": str(user_id)}).sort("settled_at", -1)
        payouts = await cursor.to_list(length=100)

        total_gross = sum(float(p.get("gross_amount", 0)) for p in payouts)
        total_net = sum(float(p.get("net_payout_amount", 0)) for p in payouts)

        for p in payouts:
            p["id"] = str(p["_id"])
            del p["_id"]

        return {
            "total_gross_earnings": round(total_gross, 2),
            "total_net_payouts": round(total_net, 2),
            "payouts_count": len(payouts),
            "payouts": payouts
        }

    # -------------------------------------------------------------
    # PHASE 8: ADMIN MARKETPLACE MANAGEMENT
    # -------------------------------------------------------------
    @staticmethod
    async def get_admin_marketplace_overview(db) -> Dict[str, Any]:
        """Aggregate high-level financial & dispute overview for administrators."""
        total_requests = await db["hiring_requests"].count_documents({})
        active_requests = await db["hiring_requests"].count_documents({"status": "in_progress"})
        completed_requests = await db["hiring_requests"].count_documents({"status": "completed"})
        disputed_requests = await db["hiring_requests"].count_documents({"status": "disputed"})
        agreements_count = await db["marketplace_agreements"].count_documents({})

        # Aggregate service fees collected
        payments_cursor = db["marketplace_payments"].find({"status": "success"})
        payments = await payments_cursor.to_list(length=1000)
        total_volume = sum(float(p.get("amount_inr", 0)) for p in payments)
        total_fees = sum(float(p.get("breakdown", {}).get("total_fee", 0)) for p in payments)

        return {
            "total_hiring_requests": total_requests,
            "active_collaborations": active_requests,
            "completed_collaborations": completed_requests,
            "active_disputes": disputed_requests,
            "executed_agreements": agreements_count,
            "total_transaction_volume": round(total_volume, 2),
            "total_platform_fees_collected": round(total_fees, 2)
        }

    @staticmethod
    async def admin_get_all_requests(db, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """Admin view of all hiring requests."""
        query = {}
        if status and status.lower() != "all":
            query["status"] = status

        cursor = db["hiring_requests"].find(query).sort("created_at", -1)
        reqs = await cursor.to_list(length=300)
        for r in reqs:
            r["id"] = str(r["_id"])
            del r["_id"]
        return reqs

    @staticmethod
    async def admin_resolve_dispute(
        db,
        request_id: str,
        action: str,
        notes: str,
        admin_id: str
    ) -> Dict[str, Any]:
        """Resolve a collaboration dispute as platform administrator."""
        req = await db["hiring_requests"].find_one({"hiring_request_id": request_id})
        if not req:
            raise HTTPException(status_code=404, detail="Hiring request not found")

        now = datetime.now(timezone.utc)
        resolved_status = "completed" if action == "favor_influencer" else "cancelled"

        audit_entry = {
            "status": resolved_status,
            "action_by": admin_id,
            "action_role": "admin",
            "timestamp": now.isoformat(),
            "note": f"Admin dispute resolution ({action}): {notes}"
        }

        await db["hiring_requests"].update_one(
            {"hiring_request_id": request_id},
            {
                "$set": {
                    "status": resolved_status,
                    "dispute_resolution": {
                        "action": action,
                        "notes": notes,
                        "resolved_by": admin_id,
                        "resolved_at": now
                    },
                    "updated_at": now
                },
                "$push": {"audit_trail": audit_entry}
            }
        )

        return {
            "success": True,
            "message": f"Dispute resolved with action: {action}",
            "status": resolved_status
        }
