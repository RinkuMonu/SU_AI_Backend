import re
from typing import Optional

class InvalidPhoneNumberException(Exception):
    """Raised when a phone number fails formatting or country-specific validation rules."""
    pass

def normalize_phone_number(raw_phone: str, default_country_code: str = "91") -> str:
    """
    Normalizes a phone number into strict E.164 format (+[country_code][national_number]).
    
    Handles:
      - 10-digit Indian mobile: "9876543210" -> "+919876543210"
      - Leading zero: "09876543210" -> "+919876543210"
      - 12-digit Indian with country code: "919876543210" -> "+919876543210"
      - E.164 already: "+919876543210" -> "+919876543210"
      - Formatted strings with spaces/dashes: "+91 98765-43210" -> "+919876543210"
      - International numbers: "+1 (555) 123-4567" -> "+15551234567"
    """
    if not raw_phone or not isinstance(raw_phone, str):
        raise InvalidPhoneNumberException("Phone number is required.")

    cleaned = raw_phone.strip()
    has_plus = cleaned.startswith("+")

    # Extract digits only
    digits = re.sub(r"\D", "", cleaned)

    if not digits:
        raise InvalidPhoneNumberException("Phone number contains no valid digits.")

    # Handle leading zero for 11 digits (e.g., 09876543210 -> 9876543210)
    if digits.startswith("0") and len(digits) == 11:
        digits = digits[1:]

    # 10 digits: Validate Indian mobile number (must start with 6, 7, 8, or 9)
    if len(digits) == 10:
        if not re.match(r"^[6-9]\d{9}$", digits):
            raise InvalidPhoneNumberException("Invalid 10-digit mobile number. Must start with 6, 7, 8, or 9.")
        return f"+{default_country_code}{digits}"

    # 12 digits starting with '91' (Indian number with country code)
    if len(digits) == 12 and digits.startswith("91"):
        national = digits[2:]
        if not re.match(r"^[6-9]\d{9}$", national):
            raise InvalidPhoneNumberException("Invalid Indian mobile number after country code.")
        return f"+{digits}"

    # International number explicitly prefixed with '+'
    if has_plus:
        if len(digits) < 8 or len(digits) > 15:
            raise InvalidPhoneNumberException("International phone number length must be between 8 and 15 digits.")
        return f"+{digits}"

    # Generic standard 10-15 digit number
    if 10 <= len(digits) <= 15:
        return f"+{digits}"

    raise InvalidPhoneNumberException(f"Invalid phone number format: {raw_phone}")

def get_msg91_recipient(normalized_phone: str) -> str:
    """
    MSG91 API expects the number in format <country_code><number> without '+'.
    Example: +919876543210 -> 919876543210.
    """
    return normalized_phone.lstrip("+")

def mask_phone_number(normalized_phone: str) -> str:
    """
    Safely masks a phone number for user-facing responses and logs.
    Example: +919876543210 -> +91******3210
    """
    if not normalized_phone:
        return ""
    if len(normalized_phone) <= 6:
        return "****"
    return normalized_phone[:3] + "*" * (len(normalized_phone) - 7) + normalized_phone[-4:]
