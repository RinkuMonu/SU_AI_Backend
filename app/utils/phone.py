import re
from typing import Optional, Tuple

class InvalidPhoneNumberException(Exception):
    """Raised when a phone number fails formatting or country-specific validation rules."""
    pass

# Known international country calling codes and their national significant number (NSN) lengths
KNOWN_COUNTRY_CONFIGS = {
    # 3-digit calling codes
    "971": {"name": "UAE", "min_len": 9, "max_len": 9, "starts": ()},
    "966": {"name": "Saudi Arabia", "min_len": 9, "max_len": 9, "starts": ()},
    # 2-digit calling codes
    "91": {"name": "India", "min_len": 10, "max_len": 10, "starts": ("6", "7", "8", "9")},
    "44": {"name": "United Kingdom", "min_len": 10, "max_len": 10, "starts": ()},
    "61": {"name": "Australia", "min_len": 9, "max_len": 9, "starts": ()},
    "65": {"name": "Singapore", "min_len": 8, "max_len": 8, "starts": ()},
    "49": {"name": "Germany", "min_len": 10, "max_len": 11, "starts": ()},
    "33": {"name": "France", "min_len": 9, "max_len": 9, "starts": ()},
    # 1-digit calling codes
    "1": {"name": "United States / Canada", "min_len": 10, "max_len": 10, "starts": ()},
}

def split_country_and_national(phone: str, default_cc: str = "91") -> Tuple[str, str]:
    """
    Splits an E.164 or digits string into (country_code_with_plus, national_number).
    Example: '+916261234655' -> ('+91', '6261234655')
             '+15551234567'  -> ('+1', '5551234567')
             '+971501234567' -> ('+971', '501234567')
    """
    if not phone:
        return f"+{default_cc.lstrip('+')}", ""

    cleaned = phone.strip()
    digits = re.sub(r"\D", "", cleaned)

    if not digits:
        return f"+{default_cc.lstrip('+')}", ""

    # Check 3-digit, then 2-digit, then 1-digit known country calling codes
    for cc_len in (3, 2, 1):
        candidate_cc = digits[:cc_len]
        if candidate_cc in KNOWN_COUNTRY_CONFIGS:
            national_part = digits[cc_len:]
            return f"+{candidate_cc}", national_part

    # Fallback for other standard country codes
    clean_default = default_cc.lstrip("+")
    if digits.startswith(clean_default) and len(digits) > len(clean_default):
        return f"+{clean_default}", digits[len(clean_default):]

    return f"+{digits[:2]}", digits[2:]

def normalize_phone_number(
    raw_phone: str,
    country_code: Optional[str] = None,
    default_country_code: str = "91"
) -> str:
    """
    Normalizes a phone number into strict E.164 format (+[country_code][national_number]).
    
    Guarantees:
      - Validates and preserves all national digits without alteration.
      - Deduplicates inadvertently doubled country codes (e.g. +91916261234655 -> +916261234655).
      - Strips formatting artifacts (spaces, dashes, parentheses, dots).
      - Handles leading zero for national dialing (06261234655 -> +916261234655).
      - Correctly supports Indian numbers (+91, exactly 10 digits starting with 6, 7, 8, or 9).
      - Supports international calling codes (+1, +44, +971, +61, +65, etc.) without applying Indian-only rules.
      - Rejects invalid or malformed numbers with descriptive InvalidPhoneNumberException.
    """
    if not raw_phone or not isinstance(raw_phone, str):
        raise InvalidPhoneNumberException("Phone number is required.")

    cleaned = raw_phone.strip()
    has_plus = cleaned.startswith("+")

    # Extract digits only
    digits = re.sub(r"\D", "", cleaned)

    if not digits:
        raise InvalidPhoneNumberException("Phone number contains no valid digits.")

    # Clean country code if explicitly supplied
    effective_cc = default_country_code.lstrip("+")
    if country_code and isinstance(country_code, str):
        extracted_cc = re.sub(r"\D", "", country_code)
        if extracted_cc:
            effective_cc = extracted_cc

    # 1. Detect and repair duplicated country code (e.g. +91916261234655 or 91916261234655)
    if digits.startswith("9191") and len(digits) == 14 and digits[4] in "6789":
        digits = digits[2:]

    # 2. Handle leading trunk zero (e.g. 09876543210 -> 9876543210)
    if digits.startswith("0") and len(digits) in (11, 10):
        digits = digits[1:]

    # 3. Exactly 10 digits without leading '+' or country code prefix
    if len(digits) == 10 and not has_plus:
        if effective_cc == "91":
            if digits[0] not in "6789":
                raise InvalidPhoneNumberException(
                    "Invalid 10-digit mobile number. Must start with 6, 7, 8, or 9."
                )
        return f"+{effective_cc}{digits}"

    # 4. Check for 12-digit Indian number starting with 91
    if len(digits) == 12 and digits.startswith("91"):
        national = digits[2:]
        if national[0] not in "6789":
            raise InvalidPhoneNumberException(
                "Invalid Indian mobile number after country code."
            )
        return f"+{digits}"

    # 5. Check against known international country calling codes
    for cc_len in (3, 2, 1):
        cc = digits[:cc_len]
        if cc in KNOWN_COUNTRY_CONFIGS:
            config = KNOWN_COUNTRY_CONFIGS[cc]
            national = digits[cc_len:]

            # Validate starts rule if defined
            starts_rule = config.get("starts", ())
            if starts_rule and national:
                if national[0] not in starts_rule:
                    raise InvalidPhoneNumberException(
                        f"Invalid {config['name']} mobile number. Must start with one of {', '.join(starts_rule)}."
                    )

            # Validate national digit length
            if len(national) < config["min_len"] or len(national) > config["max_len"]:
                raise InvalidPhoneNumberException(
                    f"Invalid {config['name']} mobile number length: expected {config['min_len']} digits, got {len(national)}."
                )

            return f"+{cc}{national}"

    # 6. Generic ITU-T E.164 international numbers with '+'
    if has_plus:
        if len(digits) < 8 or len(digits) > 15:
            raise InvalidPhoneNumberException(
                "International phone number length must be between 8 and 15 digits."
            )
        return f"+{digits}"

    # 7. Generic standard 10-15 digit number
    if 10 <= len(digits) <= 15:
        return f"+{digits}"

    raise InvalidPhoneNumberException(f"Invalid phone number format: '{raw_phone}'.")

def get_msg91_recipient(normalized_phone: str) -> str:
    """
    MSG91 API expects the number in format <country_code><number> without '+'.
    Example: +919876543210 -> 919876543210.
    """
    return normalized_phone.lstrip("+")

def mask_phone_number(normalized_phone: str) -> str:
    """
    Safely masks a phone number for user-facing responses and logs.
    Preserves calling code and national head/tail while masking intermediate digits.
    Example:
      +916261234655 -> +91 626*** **655
      +919876543210 -> +91 987*** **210
      +15551234567  -> +1 555*** **567
    """
    if not normalized_phone:
        return ""

    cc, national = split_country_and_national(normalized_phone)
    if len(national) <= 4:
        return f"{cc} {national}"
    if len(national) >= 9:
        return f"{cc} {national[:3]}*** **{national[-3:]}"
    return f"{cc} {national[:2]}*** **{national[-3:]}"
