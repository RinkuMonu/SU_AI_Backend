import httpx
import logging
import re
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, List, Tuple
from bson import ObjectId

from app.core.config import settings
from app.core.database import get_database

logger = logging.getLogger(__name__)

class Msg91EmailService:
    """
    Centralized, production-grade MSG91 Email API service.
    Integrates with MSG91 v5 Email API (https://control.msg91.com/api/v5/email/send).

    Supports exactly three template-based emails:
    1. Auto Debit Initiated Email ('autopay_debit_initiated')
    2. Payment Failed Email Notification ('payment_failed_28')
    3. Login Notification Email ('login_notification_template_2')
    """
    API_URL = "https://control.msg91.com/api/v5/email/send"

    @classmethod
    def get_auth_key(cls) -> Optional[str]:
        return (
            getattr(settings, "MSG91_AUTHKEY", None)
            or getattr(settings, "MSG91_EMAIL_AUTH_KEY", None)
            or getattr(settings, "MSG91_AUTH_KEY", None)
        )

    @classmethod
    def get_registered_domain(cls) -> str:
        domain = (
            getattr(settings, "MSG91_REGISTERED_DOMAIN", None)
            or getattr(settings, "MSG91_EMAIL_DOMAIN", None)
            or "dhandagrow.com"
        )
        return domain.strip()

    @classmethod
    def get_from_name(cls) -> str:
        name = (
            getattr(settings, "MSG91_FROM_NAME", None)
            or getattr(settings, "MSG91_EMAIL_FROM_NAME", None)
            or "DhandaGrow"
        )
        return str(name).strip()

    @classmethod
    def get_from_email(cls) -> str:
        domain = cls.get_registered_domain()
        from_email = (
            getattr(settings, "MSG91_FROM_EMAIL", None)
            or getattr(settings, "MSG91_EMAIL_FROM_EMAIL", None)
            or f"DhandaGrow@{domain}"
        )
        if "{YOUR_REGISTERED_DOMAIN}" in str(from_email):
            from_email = from_email.replace("{YOUR_REGISTERED_DOMAIN}", domain)
        return from_email.strip()

    @classmethod
    async def _send_msg91_api(
        cls,
        template_id: str,
        to_email: str,
        to_name: str,
        variables: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Internal low-level sender to MSG91 Email API v5.
        Strictly formats headers and payload according to the CURL specification.
        Never exposes the authkey in application logs.
        """
        auth_key = cls.get_auth_key()
        if not auth_key:
            logger.error("MSG91 Email dispatch aborted: authkey is missing in configuration.")
            return {
                "success": False,
                "status": "FAILED",
                "error": "MSG91_AUTHKEY not configured"
            }

        domain = cls.get_registered_domain()
        from_email = cls.get_from_email()
        from_name = cls.get_from_name()

        payload = {
            "recipients": [
                {
                    "to": [
                        {
                            "email": to_email,
                            "name": to_name
                        }
                    ],
                    "variables": {k: str(v) for k, v in variables.items()}
                }
            ],
            "from": {
                "name": from_name,
                "email": from_email
            },
            "domain": domain,
            "template_id": template_id
        }

        headers = {
            "Content-Type": "application/json",
            "authkey": auth_key
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                res = await client.post(cls.API_URL, json=payload, headers=headers)
                status_code = res.status_code
                try:
                    res_json = res.json()
                except Exception:
                    res_json = {"raw": res.text}

                # MSG91 v5 returns 200 or {"status": "success"} on dispatch
                if status_code == 200 and (res_json.get("status") == "success" or res_json.get("type") == "success" or not res_json.get("error")):
                    logger.info(
                        "MSG91 email dispatched successfully [template=%s, to=%s, status=%s]",
                        template_id, to_email, status_code
                    )
                    return {
                        "success": True,
                        "status": "SENT",
                        "status_code": status_code,
                        "response": res_json
                    }
                else:
                    err_detail = res_json.get("message") or res_json.get("error") or res.text
                    logger.warning(
                        "MSG91 email rejected [template=%s, to=%s, code=%s, err=%s]",
                        template_id, to_email, status_code, str(err_detail)[:200]
                    )
                    return {
                        "success": False,
                        "status": "FAILED",
                        "status_code": status_code,
                        "response": res_json,
                        "error": str(err_detail)
                    }

        except httpx.TimeoutException as e:
            logger.error("Timeout dispatching MSG91 email [template=%s, to=%s]", template_id, to_email)
            return {"success": False, "status": "FAILED", "error": "MSG91 connection timed out"}
        except Exception as e:
            logger.error("Exception dispatching MSG91 email [template=%s, to=%s]: %s", template_id, to_email, e)
            return {"success": False, "status": "FAILED", "error": str(e)}

    # =========================================================================
    # 1. AUTO DEBIT INITIATED EMAIL ('autopay_debit_initiated')
    # =========================================================================

    @classmethod
    async def send_auto_debit_initiated_email(
        cls,
        db,
        transaction_or_subscription: Dict[str, Any],
        user_data: Optional[Dict[str, Any]] = None,
        retry: bool = False
    ) -> Dict[str, Any]:
        """
        Dispatches 'autopay_debit_initiated' email notification when an auto-debit
        or recurring subscription mandate is initiated.
        Prevents duplicate notifications for the same transaction event.
        """
        now = datetime.now(timezone.utc)
        tx = transaction_or_subscription
        order_id = str(tx.get("order_id") or tx.get("subscription_id") or tx.get("transaction_id") or "")

        # 1. Duplicate prevention check
        if tx.get("auto_debit_email_sent") is True and not retry:
            logger.info("Auto-debit email already sent for order %s. Skipping duplicate.", order_id)
            return {"success": True, "skipped": True, "status": "ALREADY_SENT", "message": "Email already sent"}

        if order_id:
            existing_log = await db["msg91_email_logs"].find_one({
                "template_id": "autopay_debit_initiated",
                "event_id": order_id,
                "status": "SENT"
            })
            if existing_log and not retry:
                logger.info("Auto-debit log exists for %s. Skipping duplicate send.", order_id)
                return {"success": True, "skipped": True, "status": "ALREADY_SENT", "message": "Email already sent"}

        # 2. Resolve recipient email & name
        recipient_email = tx.get("user_email") or tx.get("customer_email")
        user_doc = user_data
        if not recipient_email and tx.get("user_id"):
            u_id = tx.get("user_id")
            if ObjectId.is_valid(u_id):
                user_doc = await db["users"].find_one({"_id": ObjectId(u_id)})
            if not user_doc:
                user_doc = await db["users"].find_one({"$or": [{"_id": u_id}, {"id": u_id}]})
            if user_doc:
                recipient_email = user_doc.get("email")

        if not recipient_email or "@" not in str(recipient_email) or any(bad in str(recipient_email).lower() for bad in ["null", "none", "n/a"]):
            logger.info("No registered customer email for auto-debit %s. Skipping gracefully.", order_id)
            if order_id:
                await db["payment_transactions"].update_one(
                    {"order_id": order_id},
                    {"$set": {"auto_debit_email_sent": False, "auto_debit_email_status": "SKIPPED_NO_EMAIL", "updated_at": now}}
                )
            return {"success": False, "skipped": True, "status": "SKIPPED_NO_EMAIL", "message": "No customer email"}

        customer_name = (
            tx.get("user_name")
            or tx.get("customer_name")
            or (user_doc.get("name") if user_doc else None)
            or (user_doc.get("fullName") if user_doc else None)
            or recipient_email.split("@")[0].capitalize()
        )

        amount_val = float(tx.get("amount") or tx.get("recurring_amount") or tx.get("auth_amount") or 0.0)
        amount_display = f"₹{amount_val:,.2f}" if amount_val > 0 else "₹0.00"
        payment_method = tx.get("payment_mode") or tx.get("payment_method") or "AutoPay Mandate"

        # 3. Dynamic variables matching MSG91 template specification
        variables = {
            "customer_name": customer_name,
            "amount": amount_display,
            "payment_method": payment_method,
            "support_url": "https://dhandagrow.ai/support",
            "support_email": "support@dhandagrow.ai",
            "website_url": "https://dhandagrow.ai"
        }

        template_id = getattr(settings, "MSG91_AUTO_DEBIT_TEMPLATE", "autopay_debit_initiated")

        # 4. Dispatch request to MSG91
        res = await cls._send_msg91_api(
            template_id=template_id,
            to_email=recipient_email,
            to_name=customer_name,
            variables=variables
        )

        # 5. Persist audit log & update transaction/subscription records
        is_sent = res.get("success", False)
        audit_status = "SENT" if is_sent else "FAILED"

        log_doc = {
            "template_id": template_id,
            "template_type": "auto_debit_initiated",
            "event_id": order_id,
            "recipient_email": recipient_email,
            "recipient_name": customer_name,
            "variables": variables,
            "status": audit_status,
            "response": res.get("response"),
            "error": res.get("error"),
            "created_at": now
        }
        await db["msg91_email_logs"].insert_one(log_doc)

        if order_id:
            await db["payment_transactions"].update_one(
                {"order_id": order_id},
                {
                    "$set": {
                        "auto_debit_email_sent": is_sent,
                        "auto_debit_email_status": audit_status,
                        "auto_debit_email_sent_at": now if is_sent else None,
                        "auto_debit_email_last_error": res.get("error"),
                        "updated_at": now
                    }
                }
            )
            await db["payment_subscriptions"].update_one(
                {"subscription_id": order_id},
                {
                    "$set": {
                        "auto_debit_email_sent": is_sent,
                        "auto_debit_email_status": audit_status,
                        "auto_debit_email_sent_at": now if is_sent else None,
                        "updated_at": now
                    }
                }
            )

        return res

    # =========================================================================
    # 2. PAYMENT FAILED EMAIL NOTIFICATION ('payment_failed_28')
    # =========================================================================

    @classmethod
    async def send_payment_failed_email(
        cls,
        db,
        transaction_or_order_id: Any,
        failure_reason: Optional[str] = None,
        retry: bool = False
    ) -> Dict[str, Any]:
        """
        Dispatches 'payment_failed_28' email notification when an existing payment flow
        confirms a transaction has failed.
        Never sends for pending, processing, or successful transactions.
        Prevents duplicate failure emails for the same transaction event.
        """
        now = datetime.now(timezone.utc)

        # 1. Resolve transaction document
        if isinstance(transaction_or_order_id, dict):
            tx = transaction_or_order_id
            order_id = str(tx.get("order_id") or tx.get("transaction_id") or tx.get("subscription_id") or "")
        else:
            order_id = str(transaction_or_order_id)
            tx = await db["payment_transactions"].find_one({
                "$or": [{"order_id": order_id}, {"transaction_id": order_id}, {"subscription_id": order_id}]
            })
            if not tx:
                tx = await db["payment_subscriptions"].find_one({"subscription_id": order_id})

        if not tx:
            logger.warning("Transaction %s not found for payment failed email dispatch.", order_id)
            return {"success": False, "status": "NOT_FOUND", "message": "Transaction not found"}

        # 2. Strict status check: NEVER send failure notification for successful or pending payments
        current_status = str(tx.get("status", "")).lower().strip()
        if current_status in ["success", "active", "completed", "verified"]:
            logger.info("Transaction %s is successful (%s). Refusing payment failed email.", order_id, current_status)
            return {"success": False, "skipped": True, "status": "SKIPPED_SUCCESSFUL", "message": "Transaction was successful"}

        if current_status in ["pending", "processing", "initialized", "approval_pending"] and not failure_reason:
            logger.info("Transaction %s is currently in-progress (%s). Refusing payment failed email.", order_id, current_status)
            return {"success": False, "skipped": True, "status": "SKIPPED_PENDING", "message": "Transaction is pending"}

        # 3. Duplicate prevention check
        if tx.get("payment_failed_email_sent") is True and not retry:
            logger.info("Payment failed email already sent for %s. Skipping duplicate.", order_id)
            return {"success": True, "skipped": True, "status": "ALREADY_SENT", "message": "Failure email already sent"}

        if order_id:
            existing_log = await db["msg91_email_logs"].find_one({
                "template_id": "payment_failed_28",
                "event_id": order_id,
                "status": "SENT"
            })
            if existing_log and not retry:
                logger.info("Payment failed email log exists for %s. Skipping duplicate send.", order_id)
                return {"success": True, "skipped": True, "status": "ALREADY_SENT", "message": "Failure email already sent"}

        # 4. Resolve customer details
        recipient_email = tx.get("user_email") or tx.get("customer_email")
        user_doc = None
        if not recipient_email and tx.get("user_id"):
            u_id = tx.get("user_id")
            if ObjectId.is_valid(u_id):
                user_doc = await db["users"].find_one({"_id": ObjectId(u_id)})
            if not user_doc:
                user_doc = await db["users"].find_one({"$or": [{"_id": u_id}, {"id": u_id}]})
            if user_doc:
                recipient_email = user_doc.get("email")

        if not recipient_email or "@" not in str(recipient_email) or any(bad in str(recipient_email).lower() for bad in ["null", "none", "n/a"]):
            logger.info("No registered email for failed payment %s. Skipping gracefully.", order_id)
            if order_id:
                await db["payment_transactions"].update_one(
                    {"order_id": order_id},
                    {"$set": {"payment_failed_email_sent": False, "payment_failed_email_status": "SKIPPED_NO_EMAIL", "updated_at": now}}
                )
            return {"success": False, "skipped": True, "status": "SKIPPED_NO_EMAIL", "message": "No customer email"}

        customer_name = (
            tx.get("user_name")
            or tx.get("customer_name")
            or (user_doc.get("name") if user_doc else None)
            or (user_doc.get("fullName") if user_doc else None)
            or recipient_email.split("@")[0].capitalize()
        )

        amount_val = float(tx.get("amount") or tx.get("recurring_amount") or tx.get("auth_amount") or 0.0)
        amount_display = f"₹{amount_val:,.2f}" if amount_val > 0 else "₹0.00"
        payment_method = tx.get("payment_mode") or tx.get("payment_method") or "Online Payment"
        tx_id_display = str(tx.get("transaction_id") or order_id)

        fail_reason_text = (
            failure_reason
            or tx.get("failure_reason")
            or tx.get("error_description")
            or "Payment was declined or cancelled by the payment gateway."
        )

        # Construct payment retry URL using the existing checkout / pricing route
        plan_id = tx.get("plan_id", "PRO")
        cycle = tx.get("billing_cycle", "monthly")
        payment_retry_url = (
            tx.get("payment_url")
            or f"https://dhandagrow.ai/pricing?retry_order={order_id}&plan={plan_id}&cycle={cycle}"
        )

        # 5. Dynamic variables matching MSG91 template specification
        variables = {
            "customer_name": customer_name,
            "amount": amount_display,
            "payment_method": payment_method,
            "transaction_id": tx_id_display,
            "failure_reason": fail_reason_text,
            "payment_retry_url": payment_retry_url,
            "support_email": "support@dhandagrow.ai",
            "website_url": "https://dhandagrow.ai",
            "support_url": "https://dhandagrow.ai/support"
        }

        template_id = getattr(settings, "MSG91_PAYMENT_FAILED_TEMPLATE", "payment_failed_28")

        # 6. Dispatch to MSG91
        res = await cls._send_msg91_api(
            template_id=template_id,
            to_email=recipient_email,
            to_name=customer_name,
            variables=variables
        )

        # 7. Persist audit log & update transaction records
        is_sent = res.get("success", False)
        audit_status = "SENT" if is_sent else "FAILED"

        log_doc = {
            "template_id": template_id,
            "template_type": "payment_failed",
            "event_id": order_id,
            "recipient_email": recipient_email,
            "recipient_name": customer_name,
            "variables": variables,
            "status": audit_status,
            "response": res.get("response"),
            "error": res.get("error"),
            "created_at": now
        }
        await db["msg91_email_logs"].insert_one(log_doc)

        if order_id:
            await db["payment_transactions"].update_one(
                {"order_id": order_id},
                {
                    "$set": {
                        "payment_failed_email_sent": is_sent,
                        "payment_failed_email_status": audit_status,
                        "payment_failed_email_sent_at": now if is_sent else None,
                        "payment_failed_email_last_error": res.get("error"),
                        "updated_at": now
                    }
                }
            )

        return res

    # =========================================================================
    # 3. LOGIN NOTIFICATION EMAIL ('login_notification_template_2')
    # =========================================================================

    @classmethod
    def parse_device_and_os(cls, user_agent: str, custom_device: Optional[str] = None) -> Tuple[str, str]:
        """Parses human-friendly device & browser name and OS from User-Agent or custom header."""
        if custom_device:
            return custom_device.strip(), "Mobile App"

        if not user_agent:
            return "Web Browser", "Unknown OS"

        ua = user_agent.lower()
        browser = "Web Browser"
        os_name = "Desktop OS"

        # OS detection
        if "windows nt 10.0" in ua:
            os_name = "Windows 10/11"
        elif "windows nt 6.3" in ua:
            os_name = "Windows 8.1"
        elif "windows" in ua:
            os_name = "Windows"
        elif "android" in ua:
            os_name = "Android"
        elif "iphone" in ua:
            os_name = "iOS (iPhone)"
        elif "ipad" in ua:
            os_name = "iPadOS (iPad)"
        elif "macintosh" in ua or "mac os" in ua:
            os_name = "macOS"
        elif "linux" in ua:
            os_name = "Linux"
        elif "cros" in ua:
            os_name = "Chrome OS"

        # Browser / Device detection
        if "edg/" in ua or "edge" in ua:
            browser = "Microsoft Edge"
        elif "chrome" in ua and "crios" not in ua and "android" not in ua:
            browser = "Google Chrome"
        elif "crios" in ua:
            browser = "Chrome Mobile"
        elif "android" in ua and "chrome" in ua:
            browser = "Chrome Mobile (Android)"
        elif "safari" in ua and "chrome" not in ua:
            browser = "Apple Safari"
        elif "firefox" in ua or "fxios" in ua:
            browser = "Mozilla Firefox"
        elif "opera" in ua or "opr/" in ua:
            browser = "Opera"
        elif "okhttp" in ua or "dart" in ua:
            browser = "Mobile App"
        elif "mobile" in ua:
            browser = "Mobile Browser"

        return browser, os_name

    @classmethod
    def extract_request_context(cls, request: Any) -> Dict[str, Any]:
        """Extracts client IP, device, OS, and location headers if available."""
        if not request:
            return {
                "ip": "127.0.0.1",
                "ipAddress": "127.0.0.1",
                "device": "Web Browser",
                "deviceName": "Web Browser",
                "os": "Unknown OS",
                "location": "Location unavailable",
                "deviceLocation": "Location unavailable",
                "lat": "",
                "long": "",
                "pincode": ""
            }

        headers = getattr(request, "headers", {}) or {}

        # 1. Client IP address
        ip = (
            headers.get("cf-connecting-ip")
            or headers.get("x-real-ip")
            or (headers.get("x-forwarded-for").split(",")[0].strip() if headers.get("x-forwarded-for") else None)
            or (getattr(request.client, "host", None) if hasattr(request, "client") and request.client else None)
            or "127.0.0.1"
        )

        # 2. User Agent / Device Name & OS
        user_agent = headers.get("user-agent", "")
        custom_device = headers.get("x-device-name") or headers.get("x-device-model") or headers.get("x-platform")
        device_name, os_name = cls.parse_device_and_os(user_agent, custom_device)

        # 3. Location from verified headers if present
        city = headers.get("cf-ipcity") or headers.get("x-geo-city") or ""
        country = headers.get("cf-ipcountry") or headers.get("x-geo-country") or ""
        region = headers.get("cf-region") or headers.get("x-geo-region") or ""
        lat = headers.get("cf-iplatitude") or headers.get("x-geo-latitude") or ""
        lon = headers.get("cf-iplongitude") or headers.get("x-geo-longitude") or ""
        pincode = headers.get("cf-postal-code") or headers.get("x-geo-postal-code") or ""

        if city and country:
            location_str = f"{city}, {country}"
        elif region and country:
            location_str = f"{region}, {country}"
        elif country:
            location_str = "India" if str(country).upper() == "IN" else country
        elif ip.startswith("127.") or ip.startswith("192.168.") or ip.startswith("10.") or ip == "::1":
            location_str = "Local Network"
        else:
            location_str = "Location unavailable"

        return {
            "ip": ip,
            "ipAddress": ip,
            "device": device_name,
            "deviceName": f"{device_name} on {os_name}",
            "os": os_name,
            "location": location_str,
            "deviceLocation": location_str,
            "lat": lat,
            "long": lon,
            "pincode": pincode
        }

    @classmethod
    async def send_login_notification_email(
        cls,
        db,
        user_or_id: Any,
        request: Optional[Any] = None,
        location_data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Dispatches 'login_templete' email notification after a successful login.
        Throttles duplicate login notifications from the same IP within 60 seconds.
        Variables sent match the user MSG91 template specification:
        - company_name, variable, name, device, os, location, ip, time, secure_link, support_email, year
        """
        now = datetime.now(timezone.utc)

        # 1. Resolve user record
        if isinstance(user_or_id, dict):
            user_doc = user_or_id
            user_id = str(user_doc.get("_id") or user_doc.get("id") or "")
        else:
            user_id = str(user_or_id)
            user_doc = None
            if ObjectId.is_valid(user_id):
                user_doc = await db["users"].find_one({"_id": ObjectId(user_id)})
            if not user_doc:
                user_doc = await db["users"].find_one({"$or": [{"_id": user_id}, {"id": user_id}]})

        if not user_doc:
            logger.warning("User %s not found for login notification email.", user_id)
            return {"success": False, "status": "NOT_FOUND", "message": "User not found"}

        recipient_email = user_doc.get("email")
        if not recipient_email or "@" not in str(recipient_email) or any(bad in str(recipient_email).lower() for bad in ["null", "none", "n/a"]):
            logger.info("User %s has no registered email. Skipping login notification gracefully.", user_id)
            return {"success": False, "skipped": True, "status": "SKIPPED_NO_EMAIL", "message": "No registered email"}

        user_name = (
            user_doc.get("name")
            or user_doc.get("fullName")
            or user_doc.get("username")
            or recipient_email.split("@")[0].capitalize()
        )

        # 2. Extract request metadata
        req_meta = cls.extract_request_context(request)
        if location_data and isinstance(location_data, dict):
            req_meta.update({k: str(v) for k, v in location_data.items() if v is not None})

        ip_addr = req_meta.get("ip") or req_meta.get("ipAddress") or "127.0.0.1"
        device_name = req_meta.get("device") or req_meta.get("deviceName") or "Web Browser"
        os_name = req_meta.get("os") or "Desktop OS"
        location_str = req_meta.get("location") or req_meta.get("deviceLocation") or "Location unavailable"

        template_id = getattr(settings, "MSG91_LOGIN_TEMPLATE", None) or "login_templete"

        # 3. Duplicate prevention: throttle multiple login emails within 60s for the same user & IP
        one_min_ago = now - timedelta(seconds=60)
        recent_log = await db["msg91_email_logs"].find_one({
            "template_id": template_id,
            "user_id": user_id,
            "ip_address": ip_addr,
            "status": "SENT",
            "created_at": {"$gte": one_min_ago}
        })
        if recent_log:
            logger.info("Recent login email already sent to user %s from IP %s. Skipping duplicate.", user_id, ip_addr)
            return {"success": True, "skipped": True, "status": "ALREADY_SENT", "message": "Throttled duplicate login email"}

        # 4. Dynamic variables matching MSG91 'login_templete' specification:
        # company_name, variable, name, device, os, location, ip, time, secure_link, support_email, year
        ist_time = now + timedelta(hours=5, minutes=30)
        login_time_str = ist_time.strftime("%d %b %Y, %I:%M %p IST")
        current_year_str = str(now.year)
        company_name = getattr(settings, "COMPANY_NAME", "DhandaGrow")
        support_email = getattr(settings, "SUPPORT_EMAIL", "help@dhandagrow.com")
        secure_link = getattr(settings, "SECURITY_URL", "https://dhandagrow.com/settings")

        variables = {
            "company_name": company_name,
            "variable": "Account Login Alert",
            "name": user_name,
            "device": device_name,
            "os": os_name,
            "location": location_str,
            "ip": ip_addr,
            "time": login_time_str,
            "secure_link": secure_link,
            "support_email": support_email,
            "year": current_year_str,
            # Backward-compatibility aliases
            "userName": user_name,
            "loginTime": login_time_str,
            "deviceLocation": location_str,
            "deviceName": f"{device_name} on {os_name}",
            "ipAddress": ip_addr,
            "currentYear": current_year_str,
        }

        # 5. Dispatch request to MSG91
        res = await cls._send_msg91_api(
            template_id=template_id,
            to_email=recipient_email,
            to_name=user_name,
            variables=variables
        )

        # 6. Persist audit log in MongoDB
        is_sent = res.get("success", False)
        audit_status = "SENT" if is_sent else "FAILED"

        log_doc = {
            "template_id": template_id,
            "template_type": "login_notification",
            "user_id": user_id,
            "ip_address": ip_addr,
            "recipient_email": recipient_email,
            "recipient_name": user_name,
            "variables": variables,
            "status": audit_status,
            "response": res.get("response"),
            "error": res.get("error"),
            "created_at": now
        }
        await db["msg91_email_logs"].insert_one(log_doc)

        return res

