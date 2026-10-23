import logging
import httpx
from typing import Dict, Any, Optional
from fastapi import HTTPException, status
from app.core.config import settings
from app.utils.phone import get_msg91_recipient, mask_phone_number

logger = logging.getLogger(__name__)

class SMSService:
    """
    Production-grade SMS provider service integrating with MSG91 OTP API (v5).
    Safely dispatches registration, login, and verification OTPs with timeout and error handling.
    """
    MSG91_OTP_URL = "https://control.msg91.com/api/v5/otp"

    @classmethod
    async def send_otp(
        cls,
        phone_number: str,
        otp: str,
        template_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Sends OTP to a normalized E.164 phone number via MSG91.
        
        Parameters:
            phone_number: E.164 formatted number (e.g. "+919876543210")
            otp: 6-digit cryptographically generated OTP
            template_id: Approved DLT/MSG91 template ID (defaults to registration template)
        """
        auth_key = getattr(settings, "MSG91_AUTH_KEY", None)
        tpl_id = template_id or getattr(settings, "MSG91_TEMPLATE_ID_N_REG", None)

        if not auth_key or not tpl_id:
            if settings.ENVIRONMENT == "development":
                logger.warning(
                    f"[DEV MODE] SMS provider unconfigured. Simulated OTP delivery to {mask_phone_number(phone_number)}"
                )
                return {"type": "success", "simulated": True, "request_id": "simulated_dev_id"}
            else:
                logger.error("SMS service is not configured in production (missing MSG91_AUTH_KEY or template ID).")
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="SMS service is currently unavailable. Please contact support."
                )

        recipient = get_msg91_recipient(phone_number)
        headers = {
            "authkey": auth_key,
            "Content-Type": "application/json",
            "accept": "application/json"
        }
        
        # MSG91 SendOTP v5 expects routing parameters as query parameters:
        params = {
            "template_id": tpl_id,
            "mobile": recipient,
            "otp": otp,
            "otp_length": str(len(otp)),
            "otp_expiry": "10",
            "realTimeResponse": "1"
        }
        
        # Pass body variables for DLT template variable replacement (##OTP## / custom placeholders)
        payload = {
            "OTP": otp,
            "otp": otp
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    cls.MSG91_OTP_URL,
                    headers=headers,
                    params=params,
                    json=payload
                )
                
                if response.status_code != 200:
                    logger.error(
                        f"MSG91 API returned HTTP {response.status_code} for {mask_phone_number(phone_number)}"
                    )
                    raise HTTPException(
                        status_code=status.HTTP_502_BAD_GATEWAY,
                        detail="SMS delivery failed via provider."
                    )
                
                res_data = response.json()
                if res_data.get("type") == "error":
                    msg = res_data.get("message", "Provider returned error")
                    logger.error(f"MSG91 error response for {mask_phone_number(phone_number)}: {msg}")
                    raise HTTPException(
                        status_code=status.HTTP_502_BAD_GATEWAY,
                        detail=f"SMS delivery failed: {msg}"
                    )

                logger.info(
                    f"SMS OTP successfully dispatched to {mask_phone_number(phone_number)} (request_id: {res_data.get('request_id')})"
                )
                return res_data

        except httpx.RequestError as exc:
            logger.error(f"Network error contacting MSG91 for {mask_phone_number(phone_number)}: {exc}")
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="SMS gateway timeout. Please try again."
            )
