import os
import re
import io
import hmac
import hashlib
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, Tuple
from bson import ObjectId
import httpx
from fastapi import HTTPException, status

from app.core.config import settings
from app.core.billing_config import calculate_plan_gst, PLANS
from app.services.pdf_service import PDFService

logger = logging.getLogger(__name__)

INVOICE_UPLOAD_DIR = os.path.join("uploads", "invoices")
os.makedirs(INVOICE_UPLOAD_DIR, exist_ok=True)


class InvoiceService:
    """
    Production-grade invoice generation and MSG91 email delivery service.
    
    Features:
    - Automatically generates formal branded PDF Tax Invoices / Receipts with 18% GST.
    - Sends invoice notifications via MSG91 Email API v5 with dynamic template variables.
    - Generates secure, tamper-proof download tokens for seamless invoice retrieval.
    - Safe idempotent retries without creating duplicate invoice numbers or records.
    - Enforces strict protection: NEVER sends invoices for unverified, pending, or failed payments.
    """

    @staticmethod
    def generate_invoice_number(transaction: Dict[str, Any]) -> str:
        """
        Returns the existing invoice number or creates a canonical unique invoice number.
        Format: INV-YYYYMM-XXXXXX
        """
        if transaction.get("invoice_number"):
            return str(transaction["invoice_number"])
        
        created_at = transaction.get("completed_at") or transaction.get("created_at") or datetime.now(timezone.utc)
        if isinstance(created_at, str):
            try:
                created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            except Exception:
                created_at = datetime.now(timezone.utc)
        
        prefix = created_at.strftime("%Y%m")
        pub_id = str(transaction.get("transaction_id") or transaction.get("order_id") or "DG").upper().replace("-", "")
        suffix = pub_id[-6:] if len(pub_id) >= 6 else pub_id.ljust(6, "X")
        return f"INV-{prefix}-{suffix}"

    @staticmethod
    def generate_secure_token(transaction_id: str, order_id: str) -> str:
        """Generates an HMAC-SHA256 signature for secure unauthenticated receipt download."""
        secret = getattr(settings, "SECRET_KEY", "dhandagrow-invoice-secret-key")
        raw = f"dg_invoice:{transaction_id}:{order_id}".encode("utf-8")
        return hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()[:32]

    @staticmethod
    def verify_secure_token(token: str, transaction_id: str, order_id: str) -> bool:
        """Verifies an HMAC-SHA256 receipt download token."""
        if not token:
            return False
        expected = InvoiceService.generate_secure_token(transaction_id, order_id)
        return hmac.compare_digest(str(token).strip(), expected)

    @staticmethod
    def build_invoice_download_url(transaction: Dict[str, Any], token: str) -> str:
        """Constructs a fully-qualified public download URL for the invoice PDF."""
        tx_id = transaction.get("transaction_id") or transaction.get("order_id")
        base = (getattr(settings, "BACKEND_URL", None) or "https://api.dhandagrow.com").rstrip("/")
        # Provide the receipt endpoint with the verified download token
        return f"{base}/api/v1/payments/transactions/{tx_id}/receipt?token={token}"

    @classmethod
    async def ensure_invoice_record(cls, db, transaction: Dict[str, Any]) -> Dict[str, Any]:
        """
        Ensures a transaction document has complete invoice metadata, GST breakdown,
        and generated PDF on disk. Idempotent and thread-safe.
        """
        tx = dict(transaction)
        tx_id = tx.get("transaction_id") or tx.get("order_id") or "TXN"
        order_id = tx.get("order_id") or tx_id
        
        invoice_number = cls.generate_invoice_number(tx)
        token = tx.get("invoice_download_token") or cls.generate_secure_token(tx_id, order_id)
        invoice_url = cls.build_invoice_download_url(tx, token)
        
        # Ensure 18% GST calculation consistency
        total_amount = float(tx.get("amount") or tx.get("total_payable") or 0.0)
        base_amount = float(tx.get("base_amount") or 0.0)
        gst_amount = float(tx.get("gst_amount") or 0.0)
        
        if base_amount <= 0.0 and total_amount > 0.0:
            # Back-calculate from total: total = base * 1.18 => base = total / 1.18
            base_amount = round(total_amount / 1.18, 2)
            gst_amount = round(total_amount - base_amount, 2)
        elif gst_amount <= 0.0 and base_amount > 0.0:
            gst_info = calculate_plan_gst(base_amount)
            gst_amount = gst_info["gst_amount"]
            total_amount = gst_info["total_payable"]

        now = datetime.now(timezone.utc)
        update_fields = {
            "invoice_number": invoice_number,
            "invoice_download_token": token,
            "invoice_download_url": invoice_url,
            "base_amount": base_amount,
            "gst_rate": 0.18,
            "gst_percentage": 18.0,
            "gst_amount": gst_amount,
            "total_payable": total_amount,
            "invoice_generated_at": tx.get("invoice_generated_at") or now,
            "updated_at": now
        }

        # Generate and cache PDF to disk
        pdf_path = os.path.join(INVOICE_UPLOAD_DIR, f"{invoice_number}.pdf")
        try:
            tx_for_pdf = {**tx, **update_fields}
            pdf_bytes = PDFService.generate_receipt_pdf(tx_for_pdf)
            with open(pdf_path, "wb") as f:
                f.write(pdf_bytes)
            update_fields["invoice_pdf_path"] = pdf_path
            update_fields["invoice_pdf_generated"] = True
        except Exception as e:
            logger.warning(f"Could not generate invoice PDF on disk for {invoice_number}: {e}")
            update_fields["invoice_pdf_generated"] = False

        # Persist to database
        query = {"order_id": order_id} if tx.get("order_id") else {"transaction_id": tx_id}
        await db["payment_transactions"].update_one(query, {"$set": update_fields}, upsert=True)
        
        # Also store / sync in dedicated invoices audit collection
        invoice_doc = {
            "invoice_number": invoice_number,
            "order_id": order_id,
            "transaction_id": tx_id,
            "user_id": tx.get("user_id"),
            "plan_id": tx.get("plan_id"),
            "plan_name": tx.get("plan_name"),
            "billing_cycle": tx.get("billing_cycle", "monthly"),
            "base_amount": base_amount,
            "gst_percentage": 18.0,
            "gst_amount": gst_amount,
            "total_amount": total_amount,
            "currency": tx.get("currency", "INR"),
            "payment_gateway": tx.get("payment_gateway", "Cashfree"),
            "payment_mode": tx.get("payment_mode", "UPI"),
            "download_url": invoice_url,
            "created_at": tx.get("invoice_generated_at") or now,
            "updated_at": now
        }
        await db["invoices"].update_one(
            {"invoice_number": invoice_number},
            {"$set": invoice_doc},
            upsert=True
        )

        return {**tx, **update_fields}

    @classmethod
    async def send_invoice_email(
        cls,
        db,
        transaction_or_id: Any,
        retry: bool = False
    ) -> Dict[str, Any]:
        """
        Dispatches MSG91 template invoice email for verified successful plan purchases.
        
        Strict Safety Invariants:
        1. Only sends for payment transactions with status == 'success'.
        2. Strictly ignores pending, failed, or cancelled transactions.
        3. Idempotent: Never sends duplicate emails unless explicitly requested with retry=True.
        4. Logs delivery status and audit trail into the transaction/invoice record.
        """
        now = datetime.now(timezone.utc)
        
        # 1. Resolve transaction document
        if isinstance(transaction_or_id, dict):
            tx = transaction_or_id
        else:
            clean_id = str(transaction_or_id).strip()
            query = [
                {"transaction_id": clean_id},
                {"transaction_id": clean_id.upper()},
                {"order_id": clean_id},
                {"order_id": clean_id.upper()}
            ]
            if ObjectId.is_valid(clean_id):
                query.append({"_id": ObjectId(clean_id)})
            tx = await db["payment_transactions"].find_one({"$or": query})

        if not tx:
            logger.error("Transaction not found for invoice email dispatch: %s", transaction_or_id)
            return {"success": False, "status": "NOT_FOUND", "message": "Transaction record not found"}

        order_id = tx.get("order_id") or tx.get("transaction_id")
        pub_tx_id = tx.get("transaction_id") or order_id
        tx_status = str(tx.get("status", "")).lower().strip()

        # 2. Strict Requirement 7: Never send invoice for unverified / pending / failed payments
        if tx_status != "success":
            logger.warning(
                "Refusing invoice email dispatch: Transaction %s has status '%s' (not 'success').",
                order_id, tx_status
            )
            return {
                "success": False,
                "skipped": True,
                "status": "SKIPPED_UNVERIFIED",
                "message": f"Payment is in '{tx_status}' status. Invoices are strictly restricted to verified successful payments."
            }

        # 3. Requirement 6: Idempotency check (prevent duplicate emails)
        if tx.get("invoice_email_sent") is True and not retry:
            logger.info("Invoice email already sent for transaction %s. Skipping duplicate send.", order_id)
            return {
                "success": True,
                "already_sent": True,
                "status": tx.get("invoice_email_status", "SENT"),
                "invoice_number": tx.get("invoice_number"),
                "message": "Invoice email already delivered successfully."
            }

        # 4. Resolve user, business profile, recipient email and name
        user_id = tx.get("user_id")
        user_doc = None
        bus_doc = None

        if user_id:
            try:
                if ObjectId.is_valid(str(user_id)):
                    user_doc = await db["users"].find_one({"_id": ObjectId(user_id)})
                if not user_doc:
                    user_doc = await db["users"].find_one({"_id": str(user_id)})
                if user_id:
                    bus_doc = await db["businesses"].find_one({"$or": [{"owner_id": str(user_id)}, {"ownerId": str(user_id)}]})
            except Exception as ex:
                logger.warning("Error fetching user/business details for transaction %s: %s", order_id, ex)

        recipient_email = tx.get("user_email")
        if (not recipient_email or recipient_email in ["N/A", "null", "none"] or "@" not in str(recipient_email)) and user_doc:
            recipient_email = user_doc.get("email")

        recipient_name = tx.get("user_name")
        if (not recipient_name or recipient_name in ["N/A", "null", "Valued Customer"]) and user_doc:
            recipient_name = user_doc.get("name") or user_doc.get("full_name") or user_doc.get("firstName")
        if not recipient_name or recipient_name in ["N/A", "null", "Valued Customer"]:
            recipient_name = (recipient_email.split("@")[0].capitalize() if recipient_email and "@" in str(recipient_email) else "Valued Customer")

        # If user has no registered email (e.g. phone-only signup without email added yet)
        if not recipient_email or "@" not in str(recipient_email):
            logger.info("No registered email address for transaction %s. Skipping email send gracefully.", order_id)
            await db["payment_transactions"].update_one(
                {"order_id": order_id},
                {
                    "$set": {
                        "invoice_email_status": "SKIPPED_NO_EMAIL",
                        "invoice_email_sent": False,
                        "invoice_email_notes": "User has no registered email address",
                        "updated_at": now
                    }
                }
            )
            return {
                "success": False,
                "skipped": True,
                "status": "SKIPPED_NO_EMAIL",
                "message": "User has no registered email address."
            }

        # 5. Ensure invoice number and download URL are prepared
        tx = await cls.ensure_invoice_record(db, tx)
        invoice_number = tx["invoice_number"]
        invoice_link = tx.get("invoice_download_url") or cls.build_invoice_download_url(
            tx, tx.get("invoice_download_token", "")
        )

        # 6. Resolve plan specifications from centralized billing config
        from app.core.billing_config import PLANS
        raw_plan_id = (tx.get("plan_id") or "STARTER").upper().strip()
        plan_cfg = PLANS.get(raw_plan_id, PLANS.get("STARTER", {}))
        plan_name = tx.get("plan_name") or plan_cfg.get("name") or raw_plan_id.capitalize()

        cycle = str(tx.get("billing_cycle") or "monthly").lower().strip()
        cycle_cfg = plan_cfg.get("billing_cycles", {}).get(cycle, {})
        duration_days = cycle_cfg.get("duration_days", 30 if cycle == "monthly" else (90 if cycle == "quarterly" else 365))

        completed_at = tx.get("completed_at") or tx.get("verified_at") or tx.get("created_at") or now
        if isinstance(completed_at, str):
            try:
                completed_at = datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
            except Exception:
                completed_at = now
        if completed_at.tzinfo is None:
            completed_at = completed_at.replace(tzinfo=timezone.utc)

        end_dt = completed_at + timedelta(days=duration_days)

        # Date formatting
        inv_date_str = completed_at.strftime("%d %b %Y")
        pay_date_str = completed_at.strftime("%d %b %Y, %I:%M %p")
        start_date_str = completed_at.strftime("%d %b %Y")
        end_date_str = end_dt.strftime("%d %b %Y")
        next_billing_date_str = end_dt.strftime("%d %b %Y")

        # Plan feature metrics
        credits_val = str(plan_cfg.get("credits_badge") or f"{plan_cfg.get('credits', 100)} Credits")
        post_limit = plan_cfg.get("post_limit", 30)
        ai_posts_str = f"{post_limit} Posts / month" if post_limit else "Unlimited"
        reel_limit = plan_cfg.get("reel_limit", 10)
        ai_reels_str = f"{reel_limit} Reels / month" if reel_limit else "N/A"
        team_members = plan_cfg.get("team_members", 1)
        team_members_str = f"{team_members} Member{'s' if team_members > 1 else ''}"

        feature_name_map = {
            "ai_caption": "AI Caption",
            "ai_post": "AI Post Generator",
            "ai_photoshoot": "Product Photoshoot",
            "ai_avatar": "AI Avatar Studio",
            "ai_actor": "AI Actor Videos",
            "ai_reel": "AI Reel Maker",
            "content_calendar": "Content Calendar",
            "website_builder": "AI Website Builder",
            "instagram_ai": "Instagram Auto-Publish",
            "analytics": "Marketing Analytics",
            "ads": "AI Ad Creator"
        }
        raw_features = plan_cfg.get("features", [])
        tools_list_str = ", ".join([feature_name_map.get(f, f.replace("_", " ").title()) for f in raw_features]) or "AI Social Posts, Product Photoshoot, Content Calendar"

        # Customer company, phone & address resolution
        customer_phone = (
            tx.get("user_phone")
            or (user_doc.get("phone_number") if user_doc else None)
            or (user_doc.get("phone") if user_doc else None)
            or (user_doc.get("mobile") if user_doc else None)
            or ""
        )
        company_name = (
            (bus_doc.get("business_name") if bus_doc else None)
            or (bus_doc.get("company_name") if bus_doc else None)
            or (bus_doc.get("name") if bus_doc else None)
            or (user_doc.get("businessName") if user_doc else None)
            or tx.get("company_name")
            or f"{recipient_name}'s Business"
        )
        billing_address = (
            (bus_doc.get("address") if bus_doc else None)
            or (bus_doc.get("city") if bus_doc else None)
            or (user_doc.get("city") if user_doc else None)
            or "Registered Business Address, India"
        )
        gstin = (
            (bus_doc.get("gstin") if bus_doc else None)
            or (bus_doc.get("gst_number") if bus_doc else None)
            or tx.get("gstin")
            or ""
        )

        # Payment details
        pay_method = (
            tx.get("payment_method")
            or tx.get("payment_mode")
            or tx.get("mode")
            or "AutoPay Mandate / UPI"
        )
        if "cf_" in str(order_id).lower() or "sub_" in str(order_id).lower():
            pay_method = "Cashfree AutoPay Mandate"

        gateway_ref = (
            tx.get("cf_subscription_id")
            or tx.get("cf_payment_id")
            or tx.get("payment_id")
            or tx.get("bank_reference")
            or tx.get("gateway_reference_id")
            or pub_tx_id
        )

        # Amounts breakdown
        base_amount = float(tx.get("base_amount") or 0.0)
        gst_amount = float(tx.get("gst_amount") or 0.0)
        total_amount = float(tx.get("amount") or tx.get("total_payable") or (base_amount + gst_amount))
        discount_amount = float(tx.get("discount_amount") or 0.0)
        remaining_amount = 0.0
        recurring_amount = total_amount
        frequency_str = f"{cycle.capitalize()} (Auto-renews every {duration_days} days)"

        logo_url = (
            getattr(settings, "DHANDAGROW_LOGO_URL", None)
            or "https://dhandagrow.com/logo.png"
        )
        support_contact = getattr(settings, "SUPPORT_PHONE", "+91 7857889083")
        terms_url = "https://www.dhandagrow.ai/terms"

        # Construct comprehensive template variables (both exact camelCase from mail body & legacy aliases)
        variables = {
            # 1. Exact 38 variables required by auto_pay_templete [[variableName]]
            "customerName": recipient_name,
            "email": recipient_email,
            "phone": customer_phone,
            "companyName": company_name,
            "billingAddress": billing_address,
            "gstin": gstin,
            "invoiceNumber": invoice_number,
            "orderId": order_id,
            "invoiceDate": inv_date_str,
            "paymentDate": pay_date_str,
            "paymentMethod": pay_method,
            "transactionId": pub_tx_id,
            "gatewayRefId": str(gateway_ref),
            "paymentStatus": "PAID",
            "planName": plan_name,
            "billingCycle": cycle.capitalize(),
            "startDate": start_date_str,
            "endDate": end_date_str,
            "credits": credits_val,
            "aiPosts": ai_posts_str,
            "aiReels": ai_reels_str,
            "toolsList": tools_list_str,
            "teamMembers": team_members_str,
            "originalAmount": f"{base_amount:.2f}",
            "discountAmount": f"{discount_amount:.2f}",
            "subTotal": f"{base_amount:.2f}",
            "taxableAmount": f"{base_amount:.2f}",
            "gstAmount": f"{gst_amount:.2f}",
            "totalInvoiceAmount": f"{total_amount:.2f}",
            "amountPaid": f"{total_amount:.2f}",
            "remainingAmount": f"{remaining_amount:.2f}",
            "recurringAmount": f"{recurring_amount:.2f}",
            "billingFrequency": frequency_str,
            "nextBillingDate": next_billing_date_str,
            "DhandagrowLogoURL": logo_url,
            "supportContact": support_contact,
            "termsUrl": terms_url,
            "year": str(now.year),

            # 2. Legacy snake_case and UPPERCASE aliases for backward compatibility
            "customer_name": recipient_name,
            "name": recipient_name,
            "invoice_number": invoice_number,
            "invoice_no": invoice_number,
            "plan_name": plan_name,
            "payment_date": pay_date_str,
            "transaction_id": pub_tx_id,
            "plan": plan_name,
            "base_amount": f"{base_amount:.2f}",
            "amount": f"{base_amount:.2f}",
            "gst": f"{gst_amount:.2f}",
            "gst_amount": f"{gst_amount:.2f}",
            "gst_rate": "18%",
            "gst_percentage": "18%",
            "total_amount": f"{total_amount:.2f}",
            "total": f"{total_amount:.2f}",
            "payment_id": pub_tx_id,
            "date": pay_date_str,
            "invoice_link": invoice_link,
            "invoice_url": invoice_link,
            "CUSTOMER_NAME": recipient_name,
            "INVOICE_NUMBER": invoice_number,
            "PLAN_NAME": plan_name,
            "PLAN": plan_name,
            "BASE_AMOUNT": f"{base_amount:.2f}",
            "GST_AMOUNT": f"{gst_amount:.2f}",
            "TOTAL_AMOUNT": f"{total_amount:.2f}",
            "PAYMENT_ID": pub_tx_id,
            "TRANSACTION_ID": pub_tx_id,
            "PAYMENT_DATE": pay_date_str,
            "INVOICE_LINK": invoice_link,
            "INVOICE_URL": invoice_link
        }

        # 7. Construct MSG91 API payload
        auth_key = settings.get_msg91_email_auth_key()
        api_url = getattr(settings, "MSG91_EMAIL_API_URL", "https://control.msg91.com/api/v5/email/send")
        template_id = getattr(settings, "MSG91_EMAIL_TEMPLATE_ID", "auto_pay_templete")
        domain = getattr(settings, "MSG91_EMAIL_DOMAIN", "dhandagrow.com")
        from_email = getattr(settings, "MSG91_EMAIL_FROM_EMAIL", "no-reply@dhandagrow.com")
        from_name = getattr(settings, "MSG91_EMAIL_FROM_NAME", "dhandagrow")
        reply_to_email = getattr(settings, "MSG91_EMAIL_REPLY_TO", "dhandagrow@dhandagrow.com")

        # Resolve placeholder strings like no-reply@{YOUR_REGISTERED_DOMAIN}
        if "{YOUR_REGISTERED_DOMAIN}" in str(from_email):
            from_email = from_email.replace("{YOUR_REGISTERED_DOMAIN}", domain)
        if "{YOUR_REGISTERED_DOMAIN}" in str(domain):
            domain = "dhandagrow.com"

        # Sanitize double @ typos (e.g. dhandagrow@dhandagrow@dhandagrow.com -> dhandagrow@dhandagrow.com)
        if from_email and from_email.count("@") > 1:
            p = from_email.split("@")
            from_email = f"{p[0]}@{p[-1]}"
        if reply_to_email and reply_to_email.count("@") > 1:
            p = reply_to_email.split("@")
            reply_to_email = f"{p[0]}@{p[-1]}"

        variables.update({
            "from_email": from_email,
            "sender_email": from_email,
            "domain": domain,
            "company_name": from_name,
            "FROM_EMAIL": from_email,
            "DOMAIN": domain,
            "COMPANY_NAME": from_name,
            "reply_to": reply_to_email or from_email,
            "REPLY_TO": reply_to_email or from_email
        })

        if not auth_key:
            logger.error("MSG91 auth key missing in backend environment variables.")
            await db["payment_transactions"].update_one(
                {"order_id": order_id},
                {
                    "$set": {
                        "invoice_email_status": "FAILED",
                        "invoice_email_sent": False,
                        "invoice_email_last_error": "MSG91 auth key unconfigured",
                        "updated_at": now
                    },
                    "$inc": {"invoice_email_attempts": 1}
                }
            )
            return {"success": False, "status": "FAILED", "error": "MSG91 auth key unconfigured"}

        payload = {
            "recipients": [
                {
                    "to": [
                        {
                            "email": recipient_email,
                            "name": recipient_name
                        }
                    ],
                    "variables": variables
                }
            ],
            "from": {
                "name": from_name,
                "email": from_email
            },
            "domain": domain,
            "template_id": template_id
        }

        if reply_to_email and "@" in reply_to_email:
            payload["reply_to"] = [
                {
                    "email": reply_to_email,
                    "name": from_name
                }
            ]

        headers = {
            "Content-Type": "application/json",
            "authkey": auth_key
        }

        # 8. Dispatch request to MSG91 API
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                res = await client.post(api_url, json=payload, headers=headers)
                
            res_json = res.json() if res.headers.get("content-type", "").startswith("application/json") else {}
            has_error = res_json.get("hasError", False) if isinstance(res_json, dict) else False
            is_success = (res.status_code in [200, 202]) and not has_error

            if is_success:
                unique_id = res_json.get("data", {}).get("unique_id") if isinstance(res_json, dict) else None
                logger.info(
                    "MSG91 invoice email dispatched successfully for %s to %s (unique_id: %s)",
                    invoice_number, recipient_email, unique_id
                )
                
                audit_update = {
                    "invoice_email_sent": True,
                    "invoice_email_status": "SENT",
                    "invoice_email_sent_at": now,
                    "invoice_email_recipient": recipient_email,
                    "invoice_email_last_error": None,
                    "invoice_email_response": res_json,
                    "updated_at": now
                }
                await db["payment_transactions"].update_one(
                    {"order_id": order_id},
                    {
                        "$set": audit_update,
                        "$inc": {"invoice_email_attempts": 1}
                    }
                )
                await db["invoices"].update_one(
                    {"invoice_number": invoice_number},
                    {"$set": {**audit_update, "email_delivered": True}}
                )

                return {
                    "success": True,
                    "status": "SENT",
                    "invoice_number": invoice_number,
                    "recipient": recipient_email,
                    "unique_id": unique_id,
                    "message": "Invoice email sent successfully via MSG91"
                }
            else:
                err_msg = res_json.get("message") or f"HTTP {res.status_code}: {res.text}"
                logger.error("MSG91 invoice email delivery failed for %s: %s", invoice_number, err_msg)
                
                fail_update = {
                    "invoice_email_sent": False,
                    "invoice_email_status": "FAILED",
                    "invoice_email_last_attempt_at": now,
                    "invoice_email_last_error": str(err_msg),
                    "invoice_email_response": res_json,
                    "updated_at": now
                }
                await db["payment_transactions"].update_one(
                    {"order_id": order_id},
                    {
                        "$set": fail_update,
                        "$inc": {"invoice_email_attempts": 1}
                    }
                )
                return {
                    "success": False,
                    "status": "FAILED",
                    "invoice_number": invoice_number,
                    "error": str(err_msg),
                    "message": "Failed to send invoice email via MSG91"
                }

        except Exception as e:
            logger.error("Exception occurred while sending invoice email via MSG91 for %s: %s", invoice_number, e)
            fail_update = {
                "invoice_email_sent": False,
                "invoice_email_status": "FAILED",
                "invoice_email_last_attempt_at": now,
                "invoice_email_last_error": str(e),
                "updated_at": now
            }
            await db["payment_transactions"].update_one(
                {"order_id": order_id},
                {
                    "$set": fail_update,
                    "$inc": {"invoice_email_attempts": 1}
                }
            )
            return {
                "success": False,
                "status": "FAILED",
                "invoice_number": invoice_number,
                "error": str(e),
                "message": "Network or internal error during invoice email delivery"
            }

    @classmethod
    async def retry_invoice_email(
        cls,
        db,
        transaction_id_or_order_id: str,
        authenticated_user_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Safely retries sending an invoice email without generating duplicate invoices.
        Validates ownership and verifies payment status is 'success'.
        """
        clean_id = (transaction_id_or_order_id or "").strip()
        query = [
            {"transaction_id": clean_id},
            {"transaction_id": clean_id.upper()},
            {"order_id": clean_id},
            {"order_id": clean_id.upper()}
        ]
        if ObjectId.is_valid(clean_id):
            query.append({"_id": ObjectId(clean_id)})

        tx = await db["payment_transactions"].find_one({"$or": query})
        if not tx:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Transaction '{clean_id}' not found")

        # Authorization check
        if authenticated_user_id and str(tx.get("user_id")) != str(authenticated_user_id):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden: You do not own this transaction")

        if str(tx.get("status", "")).lower() != "success":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot send invoice email: Payment status is '{tx.get('status')}', not 'success'."
            )

        # Trigger safe retry reusing existing invoice_number
        result = await cls.send_invoice_email(db, tx, retry=True)
        return result
