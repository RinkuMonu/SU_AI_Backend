import json
import re
import uuid
import logging
import urllib.parse
from datetime import datetime, timezone
from typing import Any, Optional, Tuple

from bson import ObjectId
from fastapi import HTTPException

from app.core.database import get_database
from app.models.website_builder import WebsiteProject, WebsiteBuilderSession
from app.services.business_service import BusinessService
from app.services.brand_service import get_brand_kit
from app.ai.factory import AIProviderFactory

logger = logging.getLogger(__name__)


class WebsiteBuilderService:

    # ---------------------------------------------------------
    # MULTI-LANGUAGE & LOCALIZATION ENGINE
    # ---------------------------------------------------------

    @staticmethod
    def detect_language_mode(text: str, current_lang: str = "en") -> str:
        """
        Detects user language preference:
        - 'hi': Pure Hindi (Devanagari script)
        - 'hinglish': Conversational Hinglish (Hindi written in Latin script)
        - 'en': English
        """
        if not text:
            return current_lang or "en"

        # Check for Devanagari Unicode block (\u0900-\u097F)
        if re.search(r"[\u0900-\u097F]", text):
            return "hi"

        # Hinglish conversational triggers
        hinglish_markers = {
            "mera", "meri", "mere", "hai", "hain", "hoon", "hum", "humara", "humari",
            "bana", "banao", "banado", "kardo", "karo", "karna", "chahiye", "dukaan",
            "dost", "bhai", "naam", "kya", "kaise", "nahi", "haan", "theek", "accha",
            "acha", "yeh", "woh", "wala", "wali", "wale", "kripya", "aap", "tum",
            "lekin", "batao", "bhej", "chalega", "aur", "pe", "mein", "se", "sirf",
            "korean", "mithai", "shuru", "kaam", "badhiya", "sundar", "rang", "badal",
            "badlo", "ka", "ki", "ke", "karo"
        }

        words = set(re.findall(r"[a-zA-Z]+", text.lower()))
        if len(words.intersection(hinglish_markers)) >= 1:
            return "hinglish"

        # Preserve previously selected language if message is short or ambiguous
        if current_lang in ["hi", "hinglish"] and len(words) <= 3:
            return current_lang

        return "en"

    @staticmethod
    def get_localized_text(key: str, lang: str = "en", **kwargs) -> str:
        lang = lang or "en"
        MESSAGES = {
            "initial_greeting": {
                "en": "Hi! What type of business do you run, and what products or services do you offer?",
                "hinglish": "Namaste! Aap kis type ka business chalate hain aur kaun se products ya services offer karte hain?",
                "hi": "नमस्ते! आप किस प्रकार का व्यवसाय चलाते हैं और कौन से उत्पाद या सेवाएँ प्रदान करते हैं?"
            },
            "ask_category": {
                "en": "Please tell me what type of business you run. For example, a farm house, stationery shop, sweet shop, gym, clinic, or restaurant.",
                "hinglish": "Kripya batayein aap kis type ka business chalate hain? Jaise ki farm house, stationery shop, sweet shop, gym, clinic ya restaurant.",
                "hi": "कृपया बताएं कि आप किस प्रकार का व्यवसाय चलाते हैं? जैसे कि फार्म हाउस, स्टेशनरी शॉप, मिठाई की दुकान, जिम, क्लीनिक या रेस्टोरेंट।"
            },
            "got_category_ask_products": {
                "en": "Got it! You run a {category}. What products or services do you offer?",
                "hinglish": "Samajh gaya! Aapka {category} ka business hai. Aap kaun se products ya services offer karte hain?",
                "hi": "समझ गया! आपका {category} का व्यवसाय है। आप कौन से उत्पाद या सेवाएँ प्रदान करते हैं?"
            },
            "ask_name": {
                "en": "Great! What is the name of your business or shop?",
                "hinglish": "Bahut badiya! Aapki dukaan ya business ka kya naam hai?",
                "hi": "बहुत बढ़िया! आपकी दुकान या व्यवसाय का क्या नाम है?"
            },
            "ask_name_retry": {
                "en": "Please enter the name you want to display on your website.",
                "hinglish": "Kripya apni dukaan ya business ka naam batayein jo website par dikhana hai.",
                "hi": "कृपया वह नाम दर्ज करें जो आप अपनी वेबसाइट पर प्रदर्शित करना चाहते हैं।"
            },
            "nice_to_meet": {
                "en": "Nice to meet you, {name}! Would you like me to recommend three designs or build directly?",
                "hinglish": "Aapse milkar accha laga, {name}! Kya aap 3 design options dekhna chahenge ya direct website banayein?",
                "hi": "आपसे मिलकर खुशी हुई, {name}! क्या आप 3 डिज़ाइन विकल्प देखना चाहेंगे या सीधे वेबसाइट बनाएं?"
            },
            "templates_intro": {
                "en": "Here are three designs created for your {category}. Select one to continue.",
                "hinglish": "Yeh rahe aapke {category} ke liye 3 sundar designs. Aage badhne ke liye koi ek select karein ya batayein.",
                "hi": "ये रहे आपके {category} के लिए 3 बेहतरीन डिज़ाइन। आगे बढ़ने के लिए कोई एक चुनें।"
            },
            "ask_industry_default": {
                "en": "What makes your business special, or what are the key highlights you want customers to see on your website?",
                "hinglish": "Aapke business ki kya khaasiyat hai, ya website par aap kya mukhya highlights dikhana chahenge?",
                "hi": "आपके व्यवसाय की क्या खासियत है, या वेबसाइट पर आप मुख्य रूप से क्या दिखाना चाहेंगे?"
            },
            "ask_logo": {
                "en": "Do you have an existing logo for {name}, or would you like me to auto-generate a custom logo for you?",
                "hinglish": "Kya aapke paas {name} ka logo hai, ya hum aapke liye ek stylish AI logo generate kar dein?",
                "hi": "क्या आपके पास {name} का लोगो है, या हम आपके लिए एक नया आकर्षक लोगो बना दें?"
            },
            "summary": {
                "en": (
                    "Here is your website information:\n\n"
                    "• Business: {name}\n"
                    "• Category: {category}\n"
                    "• Offerings: {offerings}\n"
                    "• Design: {design}\n"
                    "• Logo: {logo_info}\n\n"
                    "Would you like me to build your website now?"
                ),
                "hinglish": (
                    "Aapki website ki details taiyar hain:\n\n"
                    "• Business: {name}\n"
                    "• Category: {category}\n"
                    "• Offerings: {offerings}\n"
                    "• Design: {design}\n"
                    "• Logo: {logo_info}\n\n"
                    "Kya hum abhi aapki website bana dein?"
                ),
                "hi": (
                    "आपकी वेबसाइट की जानकारी तैयार है:\n\n"
                    "• व्यवसाय: {name}\n"
                    "• श्रेणी: {category}\n"
                    "• उत्पाद/सेवाएँ: {offerings}\n"
                    "• डिज़ाइन: {design}\n"
                    "• लोगो: {logo_info}\n\n"
                    "क्या हम अभी आपकी वेबसाइट बनाएं?"
                )
            },
            "generating": {
                "en": "Creating your website. Preparing your layout, content, and images...",
                "hinglish": "Aapki website ban rahi hai. Layout, content aur images taiyar kiye ja rahe hain...",
                "hi": "आपकी वेबसाइट बनाई जा रही है। लेआउट, सामग्री और तस्वीरें तैयार की जा रही हैं..."
            },
            "generated_ready": {
                "en": "Your website for {name} has been generated! You can now preview and edit it.",
                "hinglish": "Aapki {name} ki website ban chuki hai! Ab aap ise preview aur edit kar sakte hain.",
                "hi": "आपकी {name} की वेबसाइट बन चुकी है! अब आप इसका पूर्वावलोकन और संपादन कर सकते हैं।"
            }
        }
        tmpl = MESSAGES.get(key, {}).get(lang) or MESSAGES.get(key, {}).get("en", "")
        return tmpl.format(**kwargs) if tmpl else ""

    # ---------------------------------------------------------
    # GREETING & INTENT HELPERS
    # ---------------------------------------------------------

    @staticmethod
    def is_greeting(text: str) -> bool:
        """
        Detects if user input is simply a conversational greeting.
        Prevents greetings (e.g. 'hii', 'hellooo', 'namaste') from ever being
        misidentified as a business category.
        """
        if not text:
            return False
        clean = text.lower().strip()
        clean_punct = re.sub(r"[^\w\s]", "", clean)
        collapsed = re.sub(r"(.)\1+", r"\1", clean_punct)
        reduced = re.sub(r"([a-z])\1{2,}", r"\1", clean_punct)
        reduced_two = re.sub(r"([a-z])\1{2,}", r"\1\1", clean_punct)
        greetings = {
            "hi", "hii", "hello", "helo", "hey", "hlo", "yo", "sup", "namaste", "pranam",
            "good morning", "good evening", "good afternoon", "halo", "kese ho", "kaise ho",
            "kya haal", "ram ram", "radhe radhe", "salaam", "adaab", "ola", "ciao", "hola"
        }
        return any(cand in greetings for cand in [clean, clean_punct, collapsed, reduced, reduced_two])

    # ---------------------------------------------------------
    # DYNAMIC LOGO GENERATOR
    # ---------------------------------------------------------

    @staticmethod
    def generate_dynamic_logo(business_name: str, category: str = "", primary_color: str = "#0284C7") -> str:
        """
        Generates an authentic, category-specific SVG vector logo (e.g. medical cross for medical/clinic,
        dumbbell for gym, flower for florist, books for stationery) with the business initials and colors.
        Returns a self-contained SVG data URI that renders reliably in all browsers.
        """
        clean_name = (business_name or "Business").strip()
        words = clean_name.split()
        initials = "".join([w[0].upper() for w in words[:2]]) if words else "B"
        color = primary_color if (primary_color and primary_color.startswith("#")) else "#0284C7"
        cat_lower = (category or "").lower()

        # Category-tailored vector motifs
        if any(w in cat_lower for w in ["medical", "clinic", "pharmacy", "chemist", "doctor", "hospital", "dawa", "dawai"]):
            icon_svg = (
                f'<circle cx="50" cy="50" r="46" fill="{color}" />'
                f'<circle cx="50" cy="50" r="41" fill="none" stroke="#ffffff" stroke-width="2.5" opacity="0.4" />'
                f'<path d="M42 26 H58 V42 H74 V58 H58 V74 H42 V58 H26 V42 H42 Z" fill="#ffffff" />'
                f'<circle cx="50" cy="50" r="6" fill="{color}" />'
            )
        elif any(w in cat_lower for w in ["gym", "fitness", "workout", "crossfit", "yoga"]):
            icon_svg = (
                f'<rect width="100" height="100" rx="24" fill="{color}" />'
                f'<rect x="20" y="44" width="60" height="12" rx="6" fill="#ffffff" />'
                f'<rect x="14" y="32" width="12" height="36" rx="5" fill="#ffffff" />'
                f'<rect x="74" y="32" width="12" height="36" rx="5" fill="#ffffff" />'
                f'<rect x="26" y="37" width="6" height="26" rx="3" fill="#ffffff" opacity="0.85" />'
                f'<rect x="68" y="37" width="6" height="26" rx="3" fill="#ffffff" opacity="0.85" />'
            )
        elif any(w in cat_lower for w in ["flower", "florist", "floral", "bloom"]):
            icon_svg = (
                f'<circle cx="50" cy="50" r="46" fill="{color}" />'
                f'<circle cx="50" cy="34" r="14" fill="#ffffff" opacity="0.9" />'
                f'<circle cx="66" cy="50" r="14" fill="#ffffff" opacity="0.9" />'
                f'<circle cx="50" cy="66" r="14" fill="#ffffff" opacity="0.9" />'
                f'<circle cx="34" cy="50" r="14" fill="#ffffff" opacity="0.9" />'
                f'<circle cx="50" cy="50" r="11" fill="#FBBF24" />'
            )
        elif any(w in cat_lower for w in ["sweet", "mithai", "bakery", "cafe", "korean sweet", "dessert"]):
            icon_svg = (
                f'<rect width="100" height="100" rx="24" fill="{color}" />'
                f'<path d="M30 40 Q50 20 70 40 Q80 60 70 75 Q50 85 30 75 Q20 60 30 40 Z" fill="#ffffff" opacity="0.95" />'
                f'<circle cx="50" cy="30" r="6" fill="#EF4444" />'
                f'<text x="50" y="66" font-family="Arial, sans-serif" font-size="18" font-weight="bold" fill="{color}" text-anchor="middle">{initials}</text>'
            )
        elif any(w in cat_lower for w in ["stationery", "book", "scholar", "pen"]):
            icon_svg = (
                f'<rect width="100" height="100" rx="24" fill="{color}" />'
                f'<path d="M22 32 Q50 26 50 72 Q50 26 78 32 V74 Q50 68 50 74 Q50 68 22 74 Z" fill="#ffffff" />'
                f'<line x1="50" y1="30" x2="50" y2="72" stroke="{color}" stroke-width="3" />'
            )
        elif any(w in cat_lower for w in ["server", "cloud", "host", "hosting", "data center", "datacenter", "vps"]):
            icon_svg = (
                f'<rect width="100" height="100" rx="24" fill="{color}" />'
                f'<rect x="22" y="24" width="56" height="14" rx="4" fill="#ffffff" />'
                f'<circle cx="30" cy="31" r="2.5" fill="{color}" />'
                f'<circle cx="38" cy="31" r="2.5" fill="{color}" />'
                f'<rect x="22" y="43" width="56" height="14" rx="4" fill="#ffffff" />'
                f'<circle cx="30" cy="50" r="2.5" fill="{color}" />'
                f'<circle cx="38" cy="50" r="2.5" fill="{color}" />'
                f'<rect x="22" y="62" width="56" height="14" rx="4" fill="#ffffff" />'
                f'<circle cx="30" cy="69" r="2.5" fill="{color}" />'
                f'<circle cx="38" cy="69" r="2.5" fill="{color}" />'
            )
        elif any(w in cat_lower for w in ["farm", "resort", "nature", "villa"]):
            icon_svg = (
                f'<rect width="100" height="100" rx="24" fill="{color}" />'
                f'<circle cx="70" cy="30" r="12" fill="#FBBF24" />'
                f'<path d="M30 75 L50 35 L70 75 Z" fill="#ffffff" opacity="0.9" />'
                f'<rect x="47" y="65" width="6" height="15" fill="#ffffff" />'
            )
        else:
            icon_svg = (
                f'<rect width="100" height="100" rx="24" fill="{color}" />'
                f'<rect x="8" y="8" width="84" height="84" rx="18" fill="none" stroke="#ffffff" stroke-width="3" opacity="0.35" />'
                f'<text x="50" y="63" font-family="Arial, sans-serif" font-size="34" font-weight="bold" fill="#ffffff" text-anchor="middle">{initials}</text>'
            )

        svg_data = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" width="100" height="100">{icon_svg}</svg>'
        encoded_svg = urllib.parse.quote(svg_data)
        return f"data:image/svg+xml;utf8,{encoded_svg}"

    # ---------------------------------------------------------
    # BUSINESS CATEGORY DETECTION & EXTRACTION
    # ---------------------------------------------------------

    CATEGORY_KEYWORDS = {
        "Servers & Cloud Hosting": [
            "सर्वर", "क्लाउड", "होस्टिंग", "डेटा सेंटर", "servers", "server", "cloud servers", "dedicated servers",
            "cloud hosting", "web hosting", "vps", "data center", "datacenter", "bare metal", "hosting services",
            "server hosting", "linux servers", "windows servers", "cloud storage", "domain hosting"
        ],
        "Farm House & Resort": [
            "फार्म हाउस", "फार्महाउस", "रिसॉर्ट", "farm house", "farmhouse", "farm stay", "resort", "agro tourism",
            "dairy farm", "poultry farm", "agriculture", "homestay", "villa", "cottage"
        ],
        "Stationery & Books": [
            "स्टेशनरी", "किताब", "किताबें", "बुक्स", "stationery", "stationery shop", "stationery store", "books",
            "book shop", "bookstore", "office supplies", "photocopy", "printing",
            "gift shop", "novelty shop", "paper craft", "notebook", "pens", "pencils", "art supplies"
        ],
        "Korean Sweet Shop": [
            "कोरियन", "कोरियन मिठाई", "korean sweet", "korean sweets", "korean sweet shop", "bingsu",
            "mochi", "korean bakery", "korean cafe", "asian dessert", "taiyaki",
            "k-sweet", "korean dessert"
        ],
        "Indian Sweet Shop": [
            "मिठाई", "स्वीट शॉप", "हलवाई", "लड्डू", "बर्फी", "indian sweet shop", "sweet shop", "indian sweet", "mithai", "mithai shop",
            "sweets", "ladoo", "laddu", "barfi", "jalebi",
            "gulab jamun", "rasgulla", "kaju katli"
        ],
        "Flower Shop": [
            "फूल", "फूलों", "बुके", "flower shop", "florist", "flowers", "bouquets",
            "roses", "tulips", "floral arrangements", "flower stall"
        ],
        "Gym & Fitness": [
            "जिम", "फिटनेस", "व्यायाम", "gym", "fitness center", "fitness centre",
            "workout", "personal training", "fitness studio", "yoga", "pilates",
            "crossfit", "bodybuilding"
        ],
        "Restaurant & Cafe": [
            "रेस्टोरेंट", "होटल", "ढाबा", "कैफे", "बेकरी", "restaurant", "cafe", "food shop", "eatery",
            "diner", "bakery", "pizza", "burger", "dhaba", "fast food", "bistro", "coffee shop"
        ],
        "Clothing & Fashion": [
            "कपड़े", "साड़ी", "गारमेंट्स", "बुटीक", "clothing store", "fashion store", "boutique",
            "clothes", "apparel", "garments", "saree", "lehenga", "tailor", "menswear", "womenswear"
        ],
        "Beauty Salon & Spa": [
            "सैलून", "पार्लर", "ब्यूटी पार्लर", "स्पा", "salon", "beauty parlour", "beauty parlor",
            "hair salon", "spa", "makeup studio", "barber shop", "nail salon"
        ],
        "Jewellery Store": [
            "ज्वेलरी", "गहने", "सोने", "चांदी", "jewellery", "jewelry", "gold shop", "diamond store", "silver shop", "jeweller"
        ],
        "Grocery & Kirana": [
            "किराना", "राशन", "जनरल स्टोर", "grocery", "kirana", "supermarket", "general store", "provisions", "mart", "departmental store"
        ],
        "Medical & Clinic": [
            "मेडिकल", "दवा", "दवाई", "दवाइयों", "औषधि", "क्लीनिक", "डॉक्टर", "अस्पताल", "फार्मेसी", "इलाज",
            "medical", "medicals", "medical shop", "medical store", "pharmacy", "chemist", "chemist shop",
            "clinic", "dental clinic", "doctor", "hospital", "physiotherapy", "pathology", "diagnostic center",
            "treatment", "medicine", "medicines", "healthcare"
        ],
        "Automotive & Garage": [
            "गैराज", "मैकेनिक", "सर्विसिंग", "car repair", "garage", "mechanic", "auto repair", "bike repair", "car wash", "tyres", "auto garage"
        ],
        "Education & Coaching": [
            "कोचिंग", "ट्यूशन", "स्कूल", "एकेडमी", "coaching", "tuition", "classes", "institute", "school", "academy", "training institute"
        ],
        "Real Estate": [
            "प्रॉपर्टी", "रियल एस्टेट", "बिल्डर", "real estate", "property dealer", "property business", "realty", "construction", "builder"
        ],
        "Technology Business": [
            "सॉफ्टवेयर", "आईटी", "software company", "it company", "technology company",
            "web development", "digital agency", "software agency", "tech startup"
        ],
        "Photography & Studio": [
            "फोटोग्राफी", "स्टूडियो", "photography", "photo studio", "videography", "photographer", "camera studio"
        ],
        "Handicrafts & Gifts": [
            "हस्तशिल्प", "गिफ्ट", "handicrafts", "gift store", "handmade items", "pottery", "art store"
        ]
    }

    @staticmethod
    def detect_business_category(message: str) -> Optional[str]:
        text = message.lower().strip()
        if not text:
            return None

        # Ignore conversational greetings
        if WebsiteBuilderService.is_greeting(text):
            return None

        # 1. Match against known category keywords.
        # Check longer phrases first so "medical shop" matches before "shop"
        scored_matches = []
        for category, keywords in WebsiteBuilderService.CATEGORY_KEYWORDS.items():
            for kw in keywords:
                if re.search(r"\b" + re.escape(kw) + r"\b", text) or kw in text:
                    scored_matches.append((len(kw), category))

        if scored_matches:
            scored_matches.sort(key=lambda x: x[0], reverse=True)
            return scored_matches[0][1]

        # 2. Dynamic natural language patterns for ANY business in English, Hinglish, or Hindi
        patterns = [
            r"(?:i have|i run|i ran|we have|we run|owner of|managing|dealing in|start|starting|make|making|create|creating)\s+(?:an?|the|my)?\s*(?:business of|shop of|store of|work of|service of)?\s*([a-zA-Z\u0900-\u097F\s]{2,35}?)(?:\s+shop|\s+store|\s+business|\s+center|\s+centre|\s+clinic|\s+services|\s+solutions)?$",
            r"(?:i have|i run|i ran|we have|we run)\s+(?:an?|the)?\s*(?:business of|shop of|store of)?\s*([a-zA-Z\u0900-\u097F\s]{2,35})",
            r"(?:mera|meri|humara|humari|मेरी|मेरा|हमारा|हमारी)\s+(?:ek\s+|एक\s+)?([a-zA-Z\u0900-\u097F\s]{2,35}?)(?:\s+hai|\s+ka business|\s+ki dukaan|\s+dukaan|\s+की\s+दुकान|\s+का\s+बिजनेस|\s+है)",
            r"(?:website for|website chahiye|वेबसाइट चाहिए)\s+(?:an?|my|meri|मेरी)?\s*([a-zA-Z\u0900-\u097F\s]{2,35})",
            r"^(?:an?|the)?\s*([a-zA-Z\u0900-\u097F\s]{2,30})$"
        ]

        stopwords = {
            "hi", "hii", "hello", "hey", "yes", "no", "ok", "okay", "thanks", "website",
            "build", "build website", "build the website", "told you already",
            "already told", "help me", "please", "kripya", "generate", "shuru",
            "build directly", "direct", "direct website", "recommend", "recommend designs",
            "नमस्ते", "हाँ", "नहीं", "वेबसाइट"
        }

        if text in stopwords or WebsiteBuilderService.is_greeting(text):
            return None

        for pat in patterns:
            match = re.search(pat, text, re.IGNORECASE)
            if match:
                candidate = match.group(1).strip(" .")
                cand_lower = candidate.lower()
                if cand_lower not in stopwords and not WebsiteBuilderService.is_greeting(cand_lower) and len(cand_lower) >= 2 and len(cand_lower) <= 35:
                    cleaned = re.sub(
                        r"^(a|an|the|my|meri|mera|humara|humari|our|ek|एक|मेरी|मेरा|हमारे|हमारी)\s+",
                        "",
                        cand_lower
                    ).strip()
                    cleaned = re.sub(
                        r"^(business of|shop of|store of|work of|service of|services of|trading of|dealing in|company of|agency of)\s+",
                        "",
                        cleaned
                    ).strip()
                    cleaned = re.sub(
                        r"\s+(ka business|ki dukaan|dukaan|shop|store|center|centre|services|का बिजनेस|की दुकान|दुकान)$",
                        "",
                        cleaned
                    ).strip()
                    if cleaned and cleaned not in stopwords and not WebsiteBuilderService.is_greeting(cleaned):
                        for category, keywords in WebsiteBuilderService.CATEGORY_KEYWORDS.items():
                            for kw in keywords:
                                if kw == cleaned or re.search(r"\b" + re.escape(kw) + r"\b", cleaned):
                                    return category
                        return cleaned.title()

        return None

    @staticmethod
    def extract_business_details(message: str, existing: dict) -> dict:
        """
        Deterministic extraction for business details.
        Supports seamless category corrections (e.g., 'no i ran a korean sweet shop').
        """
        result = {}
        msg_lower = message.lower().strip()

        # Check if user is clarifying or correcting their category
        is_correction = any(
            w in msg_lower for w in [
                "no", "not", "nahi", "actually", "wrong", "galat", "badal do", "instead", "nahi balki", "i meant"
            ]
        ) or any(
            msg_lower.startswith(p) for p in [
                "i run a", "i have a", "we run a", "meri dukaan", "mera business", "humara business"
            ]
        )

        category = WebsiteBuilderService.detect_business_category(message)
        existing_cat = existing.get("Business Category")
        is_bad_existing = existing_cat in ["Hii", "Hi", "Hello", "Hey", "Hlo", "None", "", None]

        if category and (is_correction or not existing_cat or is_bad_existing):
            result["Business Category"] = category

        text = message.strip()

        # Extract products/services from explicit phrases
        patterns = [
            r"(?:i sell|we sell|selling|products are|we offer|i offer|services include|we provide|i provide|hum bechte hain|hamare paas)\s+(.+)",
            r"(?:everything related to|everything related)\s+(.+)"
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                result["Products/Services"] = match.group(1).strip(" .")
                break

        # Extract shop name only when user explicitly provides it
        name_patterns = [
            r"(?:my business name is|business name is|shop name is|store name is|dukaan ka naam hai|dukaan ka naam|business ka naam|naam hai)\s+(.+?)(?:\s+hai|\s+he|\.|$)",
            r"(?:my shop is called|my store is called|my business is called|called)\s+(.+?)(?:\s+hai|\s+he|\.|$)"
        ]

        for pattern in name_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                result["Business Name"] = match.group(1).strip(" .")
                break

        return result

    @staticmethod
    def normalize_text(value: Any) -> str:
        if value is None:
            return ""
        return str(value).strip()

    # ---------------------------------------------------------
    # IMAGE RESOLUTION
    # ---------------------------------------------------------

    @staticmethod
    def resolve_curated_image(
        category: str = "",
        prompt: str = "",
        index: int = 0,
        is_hero: bool = False
    ) -> str:
        import re

        text = f"{category} {prompt}".lower().strip()

        # Specific item-level keywords mapping
        # 1. MAKEUP & COSMETICS
        is_makeup = any(re.search(rf"\b{w}\b", text) for w in [
            "makeup", "make up", "cosmetic", "cosmetics", "beauty", "glam",
            "lipstick", "foundation", "eyeshadow", "skincare", "mascara",
            "blush", "eyeliner", "lipgloss", "facial", "fifa"
        ])

        if is_makeup:
            if any(w in text for w in ["tutorial", "workshop", "class", "session", "course", "lesson", "artist", "training"]):
                return "https://images.unsplash.com/photo-1487412720507-e7ab37603c6f?auto=format&fit=crop&w=900&q=85"
            if any(w in text for w in ["foundation", "base", "primer", "concealer"]):
                return "https://images.unsplash.com/photo-1631729371254-42c2892f0e6e?auto=format&fit=crop&w=900&q=85"
            if any(w in text for w in ["lipstick", "lip", "gloss", "balm"]):
                return "https://images.unsplash.com/photo-1586495777744-4413f21062fa?auto=format&fit=crop&w=900&q=85"
            if any(w in text for w in ["eye", "palette", "shadow", "mascara", "liner", "brow"]):
                return "https://images.unsplash.com/photo-1512496015851-a90fb38ba796?auto=format&fit=crop&w=900&q=85"
            if any(w in text for w in ["skin", "serum", "cream", "moisturizer", "lotion", "glow"]):
                return "https://images.unsplash.com/photo-1570172619644-dfd03ed5d881?auto=format&fit=crop&w=900&q=85"
            if any(w in text for w in ["brush", "tool", "sponge", "kit", "applicator"]):
                return "https://images.unsplash.com/photo-1596462502278-27bfdc403348?auto=format&fit=crop&w=900&q=85"
            if any(w in text for w in ["perfume", "fragrance", "scent"]):
                return "https://images.unsplash.com/photo-1547887537-6158d64c35b3?auto=format&fit=crop&w=900&q=85"
            if is_hero:
                return "https://images.unsplash.com/photo-1522337360788-8b13dee7a37e?auto=format&fit=crop&w=1200&q=85"
            makeup_defaults = [
                "https://images.unsplash.com/photo-1522337360788-8b13dee7a37e?auto=format&fit=crop&w=1200&q=85",
                "https://images.unsplash.com/photo-1631729371254-42c2892f0e6e?auto=format&fit=crop&w=900&q=85",
                "https://images.unsplash.com/photo-1586495777744-4413f21062fa?auto=format&fit=crop&w=900&q=85",
                "https://images.unsplash.com/photo-1512496015851-a90fb38ba796?auto=format&fit=crop&w=900&q=85",
                "https://images.unsplash.com/photo-1570172619644-dfd03ed5d881?auto=format&fit=crop&w=900&q=85",
                "https://images.unsplash.com/photo-1596462502278-27bfdc403348?auto=format&fit=crop&w=900&q=85"
            ]
            return makeup_defaults[index % len(makeup_defaults)]

        # 2. SHOES & FOOTWEAR
        is_shoes = any(re.search(rf"\b{w}\b", text) for w in [
            "shoe", "shoes", "sneaker", "sneakers", "footwear", "boots", "heels", "sandals", "loafers"
        ])
        if is_shoes:
            if any(w in text for w in ["sneaker", "sport", "trainer", "athletic"]):
                return "https://images.unsplash.com/photo-1552346154-21d32810aba3?auto=format&fit=crop&w=900&q=85"
            if any(w in text for w in ["formal", "leather", "oxford", "derby", "dress"]):
                return "https://images.unsplash.com/photo-1614252235316-8c857d38b5f4?auto=format&fit=crop&w=900&q=85"
            if any(w in text for w in ["heel", "pump", "women", "stilettos"]):
                return "https://images.unsplash.com/photo-1543163521-1bf539c55dd2?auto=format&fit=crop&w=900&q=85"
            if is_hero:
                return "https://images.unsplash.com/photo-1549298916-b41d501d3772?auto=format&fit=crop&w=1200&q=85"
            shoe_defaults = [
                "https://images.unsplash.com/photo-1549298916-b41d501d3772?auto=format&fit=crop&w=1200&q=85",
                "https://images.unsplash.com/photo-1552346154-21d32810aba3?auto=format&fit=crop&w=900&q=85",
                "https://images.unsplash.com/photo-1614252235316-8c857d38b5f4?auto=format&fit=crop&w=900&q=85",
                "https://images.unsplash.com/photo-1542291026-7eec264c27ff?auto=format&fit=crop&w=900&q=85",
                "https://images.unsplash.com/photo-1543163521-1bf539c55dd2?auto=format&fit=crop&w=900&q=85"
            ]
            return shoe_defaults[index % len(shoe_defaults)]

        # 3. BAKERY & SWEETS (Strict matching, never generic shop)
        is_bakery = any(re.search(rf"\b{w}\b", text) for w in [
            "bakery", "cake", "cakes", "pastry", "pastries", "mithai", "dessert", "cupcake", "cookies", "baker"
        ])
        if is_bakery:
            if any(w in text for w in ["cake", "birthday", "frosting", "wedding"]):
                return "https://images.unsplash.com/photo-1578985545062-69928b1d9587?auto=format&fit=crop&w=900&q=85"
            if any(w in text for w in ["mithai", "halwa", "laddu", "gulab", "rasgulla"]):
                return "https://images.unsplash.com/photo-1601050690597-df0568f70950?auto=format&fit=crop&w=900&q=85"
            if is_hero:
                return "https://images.unsplash.com/photo-1509440159596-0249088772ff?auto=format&fit=crop&w=1200&q=85"
            bakery_defaults = [
                "https://images.unsplash.com/photo-1509440159596-0249088772ff?auto=format&fit=crop&w=1200&q=85",
                "https://images.unsplash.com/photo-1578985545062-69928b1d9587?auto=format&fit=crop&w=900&q=85",
                "https://images.unsplash.com/photo-1587314168485-3236d6710814?auto=format&fit=crop&w=900&q=85",
                "https://images.unsplash.com/photo-1499636136210-6f4ee915583e?auto=format&fit=crop&w=900&q=85"
            ]
            return bakery_defaults[index % len(bakery_defaults)]

        # 4. CLOTHING & FASHION
        is_clothing = any(re.search(rf"\b{w}\b", text) for w in [
            "clothing", "clothes", "apparel", "boutique", "fashion", "dress", "garment", "garments", "wear", "suit"
        ])
        if is_clothing:
            if is_hero:
                return "https://images.unsplash.com/photo-1441986300917-64674bd600d8?auto=format&fit=crop&w=1200&q=85"
            clothing_defaults = [
                "https://images.unsplash.com/photo-1441986300917-64674bd600d8?auto=format&fit=crop&w=1200&q=85",
                "https://images.unsplash.com/photo-1490481651871-ab68de25d43d?auto=format&fit=crop&w=900&q=85",
                "https://images.unsplash.com/photo-1445205170230-053b83016050?auto=format&fit=crop&w=900&q=85",
                "https://images.unsplash.com/photo-1489987707025-afc232f7ea0f?auto=format&fit=crop&w=900&q=85"
            ]
            return clothing_defaults[index % len(clothing_defaults)]

        # 5. RESTAURANT & CAFE
        is_restaurant = any(re.search(rf"\b{w}\b", text) for w in [
            "restaurant", "dining", "cuisine", "cafe", "coffee", "bistro", "pizza", "burger", "food", "chef"
        ])
        if is_restaurant:
            if is_hero:
                return "https://images.unsplash.com/photo-1517248135467-4c7edcad34c4?auto=format&fit=crop&w=1200&q=85"
            rest_defaults = [
                "https://images.unsplash.com/photo-1517248135467-4c7edcad34c4?auto=format&fit=crop&w=1200&q=85",
                "https://images.unsplash.com/photo-1504674900247-0877df9cc836?auto=format&fit=crop&w=900&q=85",
                "https://images.unsplash.com/photo-1565299624946-b28f40a0ae38?auto=format&fit=crop&w=900&q=85",
                "https://images.unsplash.com/photo-1501339847302-ac426a4a7cbb?auto=format&fit=crop&w=900&q=85"
            ]
            return rest_defaults[index % len(rest_defaults)]

        # 6. FLOWERS & FLORIST
        is_flower = any(re.search(rf"\b{w}\b", text) for w in [
            "flower", "flowers", "florist", "bouquet", "bouquets", "rose", "roses", "blossom"
        ])
        if is_flower:
            if is_hero:
                return "https://images.unsplash.com/photo-1490750967868-88aa4486c946?auto=format&fit=crop&w=1200&q=85"
            flower_defaults = [
                "https://images.unsplash.com/photo-1490750967868-88aa4486c946?auto=format&fit=crop&w=1200&q=85",
                "https://images.unsplash.com/photo-1520763185298-1b434c919102?auto=format&fit=crop&w=900&q=85",
                "https://images.unsplash.com/photo-1494972308805-463bc619d34e?auto=format&fit=crop&w=900&q=85",
                "https://images.unsplash.com/photo-1525310072745-f49212b5ac6d?auto=format&fit=crop&w=900&q=85"
            ]
            return flower_defaults[index % len(flower_defaults)]

        # 7. GYM & FITNESS
        is_gym = any(re.search(rf"\b{w}\b", text) for w in [
            "gym", "fitness", "workout", "crossfit", "training", "exercise", "trainer"
        ])
        if is_gym:
            if is_hero:
                return "https://images.unsplash.com/photo-1534438327276-14e5300c3a48?auto=format&fit=crop&w=1200&q=85"
            gym_defaults = [
                "https://images.unsplash.com/photo-1534438327276-14e5300c3a48?auto=format&fit=crop&w=1200&q=85",
                "https://images.unsplash.com/photo-1517836357463-d25dfeac3438?auto=format&fit=crop&w=900&q=85",
                "https://images.unsplash.com/photo-1518611012118-696072aa579a?auto=format&fit=crop&w=900&q=85",
                "https://images.unsplash.com/photo-1571019613454-1cb2f99b2d8b?auto=format&fit=crop&w=900&q=85"
            ]
            return gym_defaults[index % len(gym_defaults)]

        # 8. TECH, SERVERS & CLOUD
        is_tech = any(re.search(rf"\b{w}\b", text) for w in [
            "server", "servers", "cloud", "hosting", "datacenter", "data center", "devops", "software", "tech", "technology", "it services"
        ])
        if is_tech:
            if is_hero:
                return "https://images.unsplash.com/photo-1558494949-ef010cbdcc31?auto=format&fit=crop&w=1200&q=85"
            tech_defaults = [
                "https://images.unsplash.com/photo-1558494949-ef010cbdcc31?auto=format&fit=crop&w=1200&q=85",
                "https://images.unsplash.com/photo-1544197150-b99a580bb7a8?auto=format&fit=crop&w=900&q=85",
                "https://images.unsplash.com/photo-1562774053-701939374585?auto=format&fit=crop&w=900&q=85",
                "https://images.unsplash.com/photo-1587560699334-cc4ff634909a?auto=format&fit=crop&w=900&q=85"
            ]
            return tech_defaults[index % len(tech_defaults)]

        # 9. MEDICAL & CLINIC
        is_medical = any(re.search(rf"\b{w}\b", text) for w in [
            "medical", "clinic", "doctor", "health", "hospital", "pharma", "pharmacy", "medicine", "medicines"
        ])
        if is_medical:
            if is_hero:
                return "https://images.unsplash.com/photo-1519494026892-80bbd2d6fd0d?auto=format&fit=crop&w=1200&q=85"
            med_defaults = [
                "https://images.unsplash.com/photo-1519494026892-80bbd2d6fd0d?auto=format&fit=crop&w=1200&q=85",
                "https://images.unsplash.com/photo-1629909613654-28e377c37b09?auto=format&fit=crop&w=900&q=85",
                "https://images.unsplash.com/photo-1584515979956-d9f6e5d09982?auto=format&fit=crop&w=900&q=85"
            ]
            return med_defaults[index % len(med_defaults)]

        # 10. JEWELLERY
        is_jewel = any(re.search(rf"\b{w}\b", text) for w in [
            "jewellery", "jewelry", "ring", "necklace", "diamond", "gold", "earrings", "watches"
        ])
        if is_jewel:
            if is_hero:
                return "https://images.unsplash.com/photo-1515562141207-7a88fb7ce338?auto=format&fit=crop&w=1200&q=85"
            jewel_defaults = [
                "https://images.unsplash.com/photo-1515562141207-7a88fb7ce338?auto=format&fit=crop&w=1200&q=85",
                "https://images.unsplash.com/photo-1535632066927-ab7c9ab60908?auto=format&fit=crop&w=900&q=85",
                "https://images.unsplash.com/photo-1599643478518-a784e5dc4c8f?auto=format&fit=crop&w=900&q=85"
            ]
            return jewel_defaults[index % len(jewel_defaults)]

        # 11. AUTOMOTIVE
        is_auto = any(re.search(rf"\b{w}\b", text) for w in [
            "automotive", "car", "cars", "garage", "mechanic", "vehicle", "detailing"
        ])
        if is_auto:
            if is_hero:
                return "https://images.unsplash.com/photo-1486006920555-c77dce18193b?auto=format&fit=crop&w=1200&q=85"
            auto_defaults = [
                "https://images.unsplash.com/photo-1486006920555-c77dce18193b?auto=format&fit=crop&w=1200&q=85",
                "https://images.unsplash.com/photo-1517524008697-84bbe3c3fd98?auto=format&fit=crop&w=900&q=85",
                "https://images.unsplash.com/photo-1520340356584-f9917d1eea6f?auto=format&fit=crop&w=900&q=85"
            ]
            return auto_defaults[index % len(auto_defaults)]

        # 12. REAL ESTATE
        is_re = any(re.search(rf"\b{w}\b", text) for w in [
            "real estate", "property", "apartment", "villa", "homes", "interior"
        ])
        if is_re:
            if is_hero:
                return "https://images.unsplash.com/photo-1600585154340-be6161a56a0c?auto=format&fit=crop&w=1200&q=85"
            re_defaults = [
                "https://images.unsplash.com/photo-1600585154340-be6161a56a0c?auto=format&fit=crop&w=1200&q=85",
                "https://images.unsplash.com/photo-1600596542815-ffad4c1539a9?auto=format&fit=crop&w=900&q=85",
                "https://images.unsplash.com/photo-1512917774080-9991f1c4c750?auto=format&fit=crop&w=900&q=85"
            ]
            return re_defaults[index % len(re_defaults)]

        # 13. EDUCATION & BOOKS
        is_edu = any(re.search(rf"\b{w}\b", text) for w in [
            "education", "coaching", "academy", "school", "course", "tutoring", "books", "study"
        ])
        if is_edu:
            if is_hero:
                return "https://images.unsplash.com/photo-1523240795612-9a054b0db644?auto=format&fit=crop&w=1200&q=85"
            edu_defaults = [
                "https://images.unsplash.com/photo-1523240795612-9a054b0db644?auto=format&fit=crop&w=1200&q=85",
                "https://images.unsplash.com/photo-1509062522246-3755977927d7?auto=format&fit=crop&w=900&q=85",
                "https://images.unsplash.com/photo-1456735190827-d1262f71b8a3?auto=format&fit=crop&w=900&q=85"
            ]
            return edu_defaults[index % len(edu_defaults)]

        # 14. ELECTRONICS & GADGETS
        is_electronics = any(re.search(rf"\b{w}\b", text) for w in [
            "electronic", "electronics", "gadget", "gadgets", "phone", "phones",
            "mobile", "smartphone", "laptop", "computer", "tv", "television",
            "headphone", "audio", "speaker", "camera", "tablet", "shyam"
        ])
        if is_electronics:
            if any(w in text for w in ["phone", "mobile", "smartphone", "iphone", "android"]):
                return "https://images.unsplash.com/photo-1511707171634-5f897ff02aa9?auto=format&fit=crop&w=900&q=85"
            if any(w in text for w in ["laptop", "computer", "pc", "macbook", "desktop"]):
                return "https://images.unsplash.com/photo-1496181133206-80ce9b88a853?auto=format&fit=crop&w=900&q=85"
            if any(w in text for w in ["tv", "television", "screen", "display", "monitor"]):
                return "https://images.unsplash.com/photo-1593359677879-a4bb92f829d1?auto=format&fit=crop&w=900&q=85"
            if any(w in text for w in ["audio", "headphone", "earphone", "speaker", "sound", "earbuds"]):
                return "https://images.unsplash.com/photo-1505740420928-5e560c06d30e?auto=format&fit=crop&w=900&q=85"
            if any(w in text for w in ["camera", "dslr", "lens", "photo"]):
                return "https://images.unsplash.com/photo-1516035069371-29a1b244cc32?auto=format&fit=crop&w=900&q=85"
            if any(w in text for w in ["watch", "smartwatch", "wearable"]):
                return "https://images.unsplash.com/photo-1523275335684-37898b6baf30?auto=format&fit=crop&w=900&q=85"
            if is_hero:
                return "https://images.unsplash.com/photo-1550009158-9ebf69173e03?auto=format&fit=crop&w=1200&q=85"
            elec_defaults = [
                "https://images.unsplash.com/photo-1550009158-9ebf69173e03?auto=format&fit=crop&w=1200&q=85",
                "https://images.unsplash.com/photo-1511707171634-5f897ff02aa9?auto=format&fit=crop&w=900&q=85",
                "https://images.unsplash.com/photo-1496181133206-80ce9b88a853?auto=format&fit=crop&w=900&q=85",
                "https://images.unsplash.com/photo-1505740420928-5e560c06d30e?auto=format&fit=crop&w=900&q=85",
                "https://images.unsplash.com/photo-1593359677879-a4bb92f829d1?auto=format&fit=crop&w=900&q=85",
                "https://images.unsplash.com/photo-1526738549149-8e07eca6c147?auto=format&fit=crop&w=900&q=85"
            ]
            return elec_defaults[index % len(elec_defaults)]

        # Default fallback
        if is_hero:
            return "https://images.unsplash.com/photo-1497366216548-37526070297c?auto=format&fit=crop&w=1200&q=80"
        general_defaults = [
            "https://images.unsplash.com/photo-1497366216548-37526070297c?auto=format&fit=crop&w=1200&q=80",
            "https://images.unsplash.com/photo-1486406146926-c627a92ad1ab?auto=format&fit=crop&w=900&q=85",
            "https://images.unsplash.com/photo-1497215728101-856f4ea42174?auto=format&fit=crop&w=900&q=85"
        ]
        return general_defaults[index % len(general_defaults)]

    # ---------------------------------------------------------
    # BRAND COLORS
    # ---------------------------------------------------------

    @staticmethod
    def resolve_palette(
        text: str = "",
        category: str = "",
        brand_guidelines: dict = None
    ) -> dict:

        brand = brand_guidelines or {}

        primary = brand.get("primary_color")
        secondary = brand.get("secondary_color")
        accent = brand.get("accent_color")

        if primary and str(primary).startswith("#"):
            return {
                "primary": primary,
                "secondary": secondary or primary,
                "accent": accent or "#F59E0B",
                "font": brand.get("font") or "outfit"
            }

        category_lower = category.lower()

        palettes = {
            "servers & cloud hosting": ("#0284C7", "#0F172A", "#38BDF8"),
            "servers": ("#0284C7", "#0F172A", "#38BDF8"),
            "cloud": ("#0284C7", "#0F172A", "#38BDF8"),
            "farm house & resort": ("#15803D", "#14532D", "#F59E0B"),
            "farm house": ("#15803D", "#14532D", "#F59E0B"),
            "farmhouse": ("#15803D", "#14532D", "#F59E0B"),
            "stationery & books": ("#4338CA", "#1E1B4B", "#06B6D4"),
            "stationery": ("#4338CA", "#1E1B4B", "#06B6D4"),
            "korean sweet shop": ("#EC4899", "#9D174D", "#FCD34D"),
            "grocery & kirana": ("#059669", "#065F46", "#F97316"),
            "medical & clinic": ("#0284C7", "#0369A1", "#10B981"),
            "automotive & garage": ("#374151", "#111827", "#EF4444"),
            "education & coaching": ("#2563EB", "#1E40AF", "#F59E0B"),
            "indian sweet shop": ("#9A3412", "#7C2D12", "#F59E0B"),
            "flower shop": ("#BE185D", "#166534", "#F9A8D4"),
            "gym & fitness": ("#EA580C", "#111827", "#10B981"),
            "restaurant": ("#991B1B", "#451A03", "#F59E0B"),
            "clothing store": ("#1E293B", "#334155", "#DB2777"),
            "clothing & fashion": ("#1E293B", "#334155", "#DB2777"),
            "beauty salon": ("#BE185D", "#831843", "#F9A8D4"),
            "beauty salon & spa": ("#BE185D", "#831843", "#F9A8D4"),
            "jewellery store": ("#92400E", "#451A03", "#FBBF24"),
            "real estate": ("#0F766E", "#134E4A", "#38BDF8"),
            "technology business": ("#1D4ED8", "#111827", "#06B6D4"),
        }

        matched_pal = None
        for k, v in palettes.items():
            if k in category_lower or category_lower in k:
                matched_pal = v
                break

        primary, secondary, accent = matched_pal or ("#4F46E5", "#312E81", "#F59E0B")

        return {
            "primary": primary,
            "secondary": secondary,
            "accent": accent,
            "font": "outfit"
        }

    # ---------------------------------------------------------
    # RICH HOMEPAGE SECTION GENERATORS
    # ---------------------------------------------------------

    @staticmethod
    def get_default_stats_section(category: str = "") -> dict:
        cat_lower = (category or "").lower()
        if any(w in cat_lower for w in ["server", "cloud", "host", "datacenter"]):
            items = [
                {"label": "Uptime Guarantee", "value": "99.99%", "description": "Enterprise grade reliability"},
                {"label": "Active Deployments", "value": "5,000+", "description": "High-performance servers"},
                {"label": "Network Speed", "value": "10 Gbps", "description": "Ultra-low latency connectivity"},
                {"label": "Support Availability", "value": "24/7/365", "description": "Dedicated technical team"}
            ]
        elif any(w in cat_lower for w in ["flower", "florist", "bouquet", "bloom"]):
            items = [
                {"label": "Fresh Daily Blooms", "value": "100%", "description": "Handpicked fresh morning blossoms"},
                {"label": "Arrangements Delivered", "value": "15,000+", "description": "Crafted with love & elegance"},
                {"label": "Express Delivery", "value": "Same-Day", "description": "Guaranteed on-time arrival"},
                {"label": "Customer Satisfaction", "value": "4.9 ★", "description": "Top-rated florist in town"}
            ]
        elif any(w in cat_lower for w in ["sweet", "mithai", "bakery", "cake", "confectionery"]):
            items = [
                {"label": "Pure Ingredients", "value": "100%", "description": "Authentic preparation & pure ghee"},
                {"label": "Signature Varieties", "value": "60+", "description": "Traditional & contemporary delicacies"},
                {"label": "Happy Foodies", "value": "25,000+", "description": "Celebrations made sweeter"},
                {"label": "Daily Preparation", "value": "Fresh Batch", "description": "Crafted daily without preservatives"}
            ]
        elif any(w in cat_lower for w in ["medical", "clinic", "pharma", "doctor", "health"]):
            items = [
                {"label": "Certified Medicines", "value": "100%", "description": "Genuine & verified healthcare products"},
                {"label": "Trusted Experience", "value": "15+ Years", "description": "Dedicated patient wellness"},
                {"label": "Support & Consultation", "value": "24/7", "description": "Always ready to assist you"},
                {"label": "Families Served", "value": "20,000+", "description": "Your neighborhood health partner"}
            ]
        elif any(w in cat_lower for w in ["farm", "resort", "hotel", "villa"]):
            items = [
                {"label": "Private Estate", "value": "10+ Acres", "description": "Lush green natural sanctuary"},
                {"label": "Successful Events", "value": "650+", "description": "Weddings, parties & retreats"},
                {"label": "Hospitality Rating", "value": "5 ★", "description": "Premium luxury & tranquility"},
                {"label": "Private Bookings", "value": "100%", "description": "Exclusive access & complete privacy"}
            ]
        elif any(w in cat_lower for w in ["stationery", "book", "office", "paper"]):
            items = [
                {"label": "Quality Supplies", "value": "10,000+", "description": "School, art & office essentials"},
                {"label": "Genuine Brands", "value": "100%", "description": "Authentic tools for creators & learners"},
                {"label": "Institutions Supplied", "value": "200+", "description": "Reliable bulk procurement"},
                {"label": "Customer Rating", "value": "4.9 ★", "description": "Top rated community stationer"}
            ]
        else:
            items = [
                {"label": "Quality Guarantee", "value": "100%", "description": "Uncompromised standards in every detail"},
                {"label": "Satisfied Clients", "value": "10,000+", "description": "Delivering happiness consistently"},
                {"label": "Speed of Service", "value": "Prompt", "description": "Reliable & fast response times"},
                {"label": "Verified Rating", "value": "4.9 ★", "description": "Top-rated by our valued customers"}
            ]

        return {
            "type": "stats",
            "title": "Key Highlights & Trust",
            "subtitle": f"Why thousands rely on our {category or 'business'} every single day",
            "items": items
        }

    @staticmethod
    def get_default_testimonials_section(business_name: str, category: str = "") -> dict:
        cat_lower = (category or "").lower()
        if any(w in cat_lower for w in ["server", "cloud", "host"]):
            items = [
                {"name": "Vikram Malhotra", "role": "CTO, CloudScale", "rating": 5, "quote": f"{business_name} delivered incredible stability with zero downtime. Deployment was instant and network speeds exceeded all expectations."},
                {"name": "Sneha Sen", "role": "Lead Architect", "rating": 5, "quote": "Rock-solid infrastructure and responsive 24/7 technical support. Truly enterprise grade service."},
                {"name": "Rohan Mehra", "role": "Startup Founder", "rating": 5, "quote": f"Migrating to {business_name} reduced our latency dramatically. Highly recommended for production workloads."}
            ]
        elif any(w in cat_lower for w in ["flower", "florist"]):
            items = [
                {"name": "Pooja Sharma", "role": "Verified Customer", "rating": 5, "quote": f"The floral arrangement from {business_name} was breathtaking! Fresh blooms that stayed vibrant for over a week."},
                {"name": "Amit Verma", "role": "Anniversary Order", "rating": 5, "quote": "Flawless same-day delivery and gorgeous presentation. My wife absolutely loved the bouquet!"},
                {"name": "Kavita Rao", "role": "Event Coordinator", "rating": 5, "quote": f"{business_name} handled our venue floral decor with such artistry and elegance. Truly spectacular."}
            ]
        elif any(w in cat_lower for w in ["sweet", "mithai", "bakery"]):
            items = [
                {"name": "Rajesh Gupta", "role": "Regular Patron", "rating": 5, "quote": f"Authentic taste, rich aroma of pure ghee, and heavenly sweets. {business_name} is our family's favorite for every celebration."},
                {"name": "Neha Kapoor", "role": "Festival Shopper", "rating": 5, "quote": "Ordered custom gift boxes for Diwali and every guest called to compliment the extraordinary flavors."},
                {"name": "Manish Joshi", "role": "Sweet Lover", "rating": 5, "quote": f"Freshness you can taste in every single bite. The craftsmanship at {business_name} is truly unmatched."}
            ]
        elif any(w in cat_lower for w in ["medical", "clinic", "pharma"]):
            items = [
                {"name": "Suresh Singhal", "role": "Local Resident", "rating": 5, "quote": f"{business_name} is our most trusted pharmacy. They always have genuine medicines in stock and provide caring assistance."},
                {"name": "Dr. Sunita Nair", "role": "Healthcare Professional", "rating": 5, "quote": "Reliable, hygienic, and extremely helpful staff. Emergency prescriptions are fulfilled promptly without delay."},
                {"name": "Arjun Saxena", "role": "Caregiver", "rating": 5, "quote": f"Doorstep delivery and patient guidance from {business_name} have been an absolute blessing for our family."}
            ]
        else:
            items = [
                {"name": "Priya Sharma", "role": "Verified Client", "rating": 5, "quote": f"The experience with {business_name} has been phenomenal. Top quality, attentive staff, and outstanding professionalism."},
                {"name": "Rahul Verma", "role": "Repeat Customer", "rating": 5, "quote": "Super impressed by their consistency and attention to detail. Would recommend to anyone without hesitation."},
                {"name": "Ananya Patel", "role": "Community Member", "rating": 5, "quote": f"Fast, friendly, and dependable every time. {business_name} sets the gold standard in {category or 'service'}."}
            ]

        return {
            "type": "testimonials",
            "title": "What Our Customers Say",
            "subtitle": f"Genuine praise from people who experience {business_name} firsthand",
            "items": items
        }

    @staticmethod
    def get_default_faq_section(business_name: str, category: str = "") -> dict:
        cat_lower = (category or "").lower()
        if any(w in cat_lower for w in ["server", "cloud", "host"]):
            items = [
                {"question": "How quickly are dedicated and cloud servers deployed?", "answer": "Most standard server instances are provisioned instantly within 5 to 15 minutes following order confirmation."},
                {"question": "Is DDoS protection and firewall security included?", "answer": "Yes, automated enterprise multi-layer DDoS mitigation and advanced firewall filtering are standard on all servers."},
                {"question": "Do I receive full root and IPMI / KVM access?", "answer": "Absolutely. You get 100% root/administrator access and out-of-band management console control."},
                {"question": "What level of customer and technical support is provided?", "answer": "Our dedicated system engineers provide round-the-clock 24/7/365 assistance via ticket and priority chat."}
            ]
        elif any(w in cat_lower for w in ["flower", "florist"]):
            items = [
                {"question": "How fresh are your flowers and arrangements?", "answer": "We hand-select fresh morning blossoms directly from verified growers every single day to ensure lasting vibrancy."},
                {"question": "Can I place custom orders for specific bouquets or events?", "answer": f"Yes! {business_name} specializes in custom designed bouquets, festive hampers, and full event floral styling."},
                {"question": "Do you provide same-day flower delivery?", "answer": "Yes, we offer express same-day doorstep delivery for orders placed before our afternoon cutoff."},
                {"question": "How can I keep my flowers fresh for longer?", "answer": "Trim stems slightly at an angle, change the vase water every two days, and keep flowers away from direct sunlight."}
            ]
        elif any(w in cat_lower for w in ["sweet", "mithai", "bakery"]):
            items = [
                {"question": "Are your sweets prepared fresh daily?", "answer": "Yes, all our sweets and delicacies are freshly prepared every morning using pure ingredients and traditional recipes."},
                {"question": "Do you accept bulk orders for weddings and festivals?", "answer": f"Yes, {business_name} provides personalized bulk gift boxes and event catering for weddings, corporate gifts, and festivals."},
                {"question": "What is the typical shelf life of your offerings?", "answer": "Dry and roasted varieties typically last 2 to 3 weeks, while milk-based sweets are best enjoyed within 3 to 5 days."},
                {"question": "Do you offer sugar-free or dietary-conscious options?", "answer": "Yes, we craft special sugar-free and dry-fruit-only selections to cater to health-conscious patrons."}
            ]
        elif any(w in cat_lower for w in ["medical", "clinic", "pharma"]):
            items = [
                {"question": "Are all medications and health supplies verified and genuine?", "answer": "100%. We source strictly from authorized pharmaceutical distributors with verified batch certificates."},
                {"question": "Do you offer prescription fulfillment and consultations?", "answer": "Yes, our qualified pharmacists review your prescription carefully and guide you on dosage and instructions."},
                {"question": "Do you provide home delivery for essential medicines?", "answer": "Yes, we offer prompt doorstep delivery across our local coverage area for your convenience."},
                {"question": "What are your operating hours for urgent needs?", "answer": f"{business_name} operates extended daily hours and provides on-call emergency healthcare assistance."}
            ]
        else:
            items = [
                {"question": f"How can I inquire about products or services at {business_name}?", "answer": "You can reach us directly through our Contact form, visit our location, or call our customer service desk."},
                {"question": "Do you provide customized solutions tailored to specific needs?", "answer": "Yes! We work closely with each client to provide personalized recommendations and custom packages."},
                {"question": "What is your commitment to quality and satisfaction?", "answer": "We back every offering with a 100% satisfaction guarantee, ensuring uncompromised standards."},
                {"question": "What are your standard turnaround or delivery times?", "answer": "We prioritize fast, efficient fulfillment and will keep you updated every step of the way."}
            ]

        return {
            "type": "faq",
            "title": "Frequently Asked Questions",
            "subtitle": f"Helpful answers to common questions about {business_name}",
            "items": items
        }

    @staticmethod
    def get_default_cta_section(business_name: str, category: str = "") -> dict:
        return {
            "type": "cta",
            "title": f"Ready to Experience the Best in {category or 'Our Services'}?",
            "subtitle": f"Connect with {business_name} today. We are here to deliver exceptional quality, personalized care, and lasting satisfaction.",
            "cta": "Get in Touch",
            "secondary_cta": "Explore Offerings"
        }

    # ---------------------------------------------------------
    # DATABASE
    # ---------------------------------------------------------

    @staticmethod
    async def get_session_collection():
        return get_database()["website_builder_sessions"]

    @staticmethod
    async def get_project_collection():
        return get_database()["website_projects"]

    @staticmethod
    async def get_website(project_id: str, user_id: str):
        if not ObjectId.is_valid(project_id):
            return None

        collection = await WebsiteBuilderService.get_project_collection()

        doc = await collection.find_one({
            "_id": ObjectId(project_id),
            "user_id": user_id
        })

        if doc:
            return WebsiteProject(**doc)

        return None

    @staticmethod
    async def save_session(session: WebsiteBuilderSession):
        collection = await WebsiteBuilderService.get_session_collection()

        update_data = session.model_dump(
            by_alias=True,
            exclude={"id", "created_at"}
        )

        update_data["updated_at"] = datetime.now(timezone.utc)

        await collection.update_one(
            {"_id": ObjectId(session.id)},
            {"$set": update_data}
        )

    @staticmethod
    async def create_session(user_id: str):
        collection = await WebsiteBuilderService.get_session_collection()

        await collection.update_many(
            {"user_id": user_id, "status": "active"},
            {"$set": {"status": "archived"}}
        )

        session = WebsiteBuilderSession(
            user_id=user_id,
            current_step=1,
            collected_data={
                "onboarding_step": "business_details"
            },
            messages=[{
                "id": str(uuid.uuid4()),
                "role": "ai",
                "content": (
                    "Hi! What type of business do you run, "
                    "and what products or services do you offer?"
                ),
                "type": "text"
            }]
        )

        doc = session.model_dump(by_alias=True, exclude={"id"})
        result = await collection.insert_one(doc)

        session.id = str(result.inserted_id)

        return session

    @staticmethod
    async def get_session(session_id: str, user_id: str):
        if not ObjectId.is_valid(session_id):
            return None

        collection = await WebsiteBuilderService.get_session_collection()

        doc = await collection.find_one({
            "_id": ObjectId(session_id),
            "user_id": user_id
        })

        return WebsiteBuilderSession(**doc) if doc else None

    # ---------------------------------------------------------
    # BRAND KIT
    # ---------------------------------------------------------

    @staticmethod
    async def get_saved_brand(user_id: str, session: WebsiteBuilderSession):
        """
        Retrieve the existing business and its saved Brand Kit.
        The Brand Kit logo is never fabricated here.
        """

        business_id = session.collected_data.get("business_id")

        if not business_id:
            try:
                business = await BusinessService.get_business_by_owner(user_id)

                if business:
                    business_id = str(business.id)
                    session.collected_data["business_id"] = business_id

                    if not session.collected_data.get("Business Name"):
                        session.collected_data["Business Name"] = business.business_name

                    if not session.collected_data.get("Business Category"):
                        session.collected_data["Business Category"] = business.business_category

            except Exception:
                logger.exception("Could not retrieve business profile")

        if not business_id:
            return None

        try:
            brand = await get_brand_kit(get_database(), str(business_id))

            if not brand:
                return None

            if isinstance(brand, dict):
                brand_data = dict(brand)
            else:
                brand_data = brand.model_dump(
                    by_alias=True,
                    exclude={"id"}
                )

            brand_data.pop("_id", None)
            brand_data.pop("id", None)

            session.collected_data["Brand Guidelines"] = brand_data

            if brand_data.get("logo_url"):
                session.collected_data["saved_brand_logo"] = brand_data["logo_url"]

            return brand_data

        except Exception:
            logger.exception("Brand Kit lookup failed")
            return None

    # ---------------------------------------------------------
    # CHAT MESSAGE HELPERS
    # ---------------------------------------------------------

    @staticmethod
    def add_ai_message(
        session,
        content: str,
        message_type: str = "text",
        options: list = None,
        data: dict = None
    ):
        message = {
            "id": str(uuid.uuid4()),
            "role": "ai",
            "content": content,
            "type": message_type
        }

        if options:
            message["options"] = options

        if data:
            message["data"] = data

        session.messages.append(message)

    @staticmethod
    def add_user_message(session, content: str):
        session.messages.append({
            "id": str(uuid.uuid4()),
            "role": "user",
            "content": content
        })

    # ---------------------------------------------------------
    # ONBOARDING FLOW
    # ---------------------------------------------------------

    @staticmethod
    async def process_chat(
        session_id: str,
        user_id: str,
        message: str,
        language: str = None,
        data: dict = None
    ):

        session = await WebsiteBuilderService.get_session(
            session_id,
            user_id
        )

        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        data = data or {}
        action = data.get("action")

        # Detect and remember language mode (English, Hinglish, or Hindi)
        lang = WebsiteBuilderService.detect_language_mode(
            message,
            language or getattr(session, "language", "en")
        )
        session.language = lang

        # -----------------------------------------------------
        # GLOBAL FAST-TRACK BUILD INTENT
        # -----------------------------------------------------
        # If the user says "build the website", "bana do", "generate website" at any point,
        # never get stuck. Auto-generate missing logo/template and immediately build!
        lower_msg = message.lower().strip()
        build_phrases = [
            "build the website", "build website", "build", "generate website",
            "generate", "bana do", "website bana do", "make website",
            "website banao", "create website", "shuru karo", "banao",
            "direct banao", "confirm & generate website", "build_directly", "build directly",
            "direct website banao", "direct bana do", "सीधे वेबसाइट बनाएं",
            "वेबसाइट बना दो", "वेबसाइट बनाएं", "वेबसाइट बनाओ", "बना दो", "बनाएं",
            "सीधे वेबसाइट बनाएं", "शुरू करें", "तैयार है"
        ]
        is_build_intent = (
            action in ["generate", "build_directly"]
            or lower_msg in build_phrases
            or any(lower_msg.startswith(p) for p in [
                "build the website", "website bana do", "bana do", "website banao",
                "वेबसाइट बना दो", "वेबसाइट बनाएं", "सीधे वेबसाइट बनाएं"
            ])
        )

        b_name = session.collected_data.get("Business Name")
        b_cat = session.collected_data.get("Business Category")

        if is_build_intent and b_name and b_cat:
            WebsiteBuilderService.add_user_message(session, message)

            # Ensure logo is ready
            if not session.collected_data.get("Logo"):
                theme = WebsiteBuilderService.resolve_palette(category=b_cat)
                session.collected_data["Logo"] = WebsiteBuilderService.generate_dynamic_logo(
                    b_name, b_cat, theme["primary"]
                )
                session.collected_data["logo_status"] = "available"

            # Ensure template is selected
            if not session.collected_data.get("selected_template_name"):
                session.collected_data["selected_template_name"] = "Modern Showcase"
                session.selected_template = "modern-showcase-1"

            return await WebsiteBuilderService.generate_website(session, user_id)

        if is_build_intent and not b_name:
            WebsiteBuilderService.add_user_message(session, message)
            session.collected_data["wants_fast_build"] = True
            session.collected_data["onboarding_step"] = "business_name"
            session.current_step = 2
            ask_name_msg = (
                "Almost ready to build! What is the name of your business or shop?"
                if lang == "en" else
                "Website banane ke liye bas ek cheez chahiye! Aapki dukaan ya business ka kya naam hai?"
                if lang == "hinglish" else
                "वेबसाइट बनाने के लिए बस एक जानकारी चाहिए! आपके व्यवसाय या दुकान का क्या नाम है?"
            )
            await WebsiteBuilderService.reply(session, ask_name_msg)
            await WebsiteBuilderService.save_session(session)
            return type("Result", (), {
                "message": session.messages[-1]["content"],
                "quick_actions": [],
                "session": session
            })

        # -----------------------------------------------------
        # TEMPLATE SELECTION (BUTTON ACTION)
        # -----------------------------------------------------

        if action == "select_template":
            template_id = data.get("templateId") or data.get("template_id")
            template_name = data.get("templateName") or data.get("template_name") or str(template_id or "Custom Template")

            session.selected_template = str(template_id or "custom-template")
            session.collected_data["selected_template_id"] = str(template_id or "custom-template")
            session.collected_data["selected_template_name"] = template_name

            session.current_step = 5
            session.collected_data["onboarding_step"] = "industry_details"

            WebsiteBuilderService.add_user_message(session, template_name)
            await WebsiteBuilderService.ask_industry_question(session)
            await WebsiteBuilderService.save_session(session)

            return type("Result", (), {
                "message": session.messages[-1]["content"],
                "quick_actions": [],
                "session": session
            })

        # -----------------------------------------------------
        # LOGO SELECTION ACTIONS
        # -----------------------------------------------------

        if action == "upload_logo":
            logo_base64 = data.get("base64") or data.get("logo") or data.get("logoUrl")
            WebsiteBuilderService.add_user_message(session, message or "I uploaded my logo")
            b_name = session.collected_data.get("Business Name", "Brand")

            if logo_base64:
                session.collected_data["Logo"] = logo_base64
                session.collected_data["logo_status"] = "uploaded"
                session.collected_data["onboarding_step"] = "confirmation"
                session.current_step = 7

                ack_msg = (
                    f"Your logo for {b_name} has been uploaded successfully!"
                    if lang == "en" else
                    f"Aapki dukaan '{b_name}' ka logo upload ho gaya hai!"
                    if lang == "hinglish" else
                    f"आपकी दुकान '{b_name}' का लोगो सफलतापूर्वक अपलोड हो गया है!"
                )
                await WebsiteBuilderService.reply(session, ack_msg)
                await WebsiteBuilderService.show_confirmation_summary(session)
            else:
                session.collected_data["onboarding_step"] = "logo_check"
                session.current_step = 6
                upload_prompt = (
                    f"Please select and upload your logo file for {b_name}:"
                    if lang == "en" else
                    f"Kripya niche button par click karke '{b_name}' ka logo upload karein:"
                    if lang == "hinglish" else
                    f"कृपया नीचे बटन पर क्लिक करके '{b_name}' का लोगो अपलोड करें:"
                )
                await WebsiteBuilderService.reply(session, upload_prompt, options=[
                    {"label": "📁 Upload Logo File", "action": "upload_logo"},
                    {"label": "✨ Auto-Generate AI Logo", "action": "generate_logo"}
                ])

            await WebsiteBuilderService.save_session(session)
            return type("Result", (), {
                "message": session.messages[-1]["content"],
                "quick_actions": session.messages[-1].get("options", []),
                "session": session
            })

        if action == "use_saved_logo":
            WebsiteBuilderService.add_user_message(session, message or "Use Saved Logo")
            brand = await WebsiteBuilderService.get_saved_brand(user_id, session)
            saved_logo = (brand or {}).get("logo_url")

            if saved_logo:
                session.collected_data["Logo"] = saved_logo
                session.collected_data["logo_status"] = "available"
            else:
                b_name = session.collected_data.get("Business Name", "Brand")
                b_cat = session.collected_data.get("Business Category", "Business")
                theme = WebsiteBuilderService.resolve_palette(category=b_cat)
                session.collected_data["Logo"] = WebsiteBuilderService.generate_dynamic_logo(
                    b_name, b_cat, theme["primary"]
                )
                session.collected_data["logo_status"] = "available"

            session.collected_data["onboarding_step"] = "confirmation"
            session.current_step = 7

            await WebsiteBuilderService.show_confirmation_summary(session)
            await WebsiteBuilderService.save_session(session)

            return type("Result", (), {
                "message": session.messages[-1]["content"],
                "quick_actions": session.messages[-1].get("options", []),
                "session": session
            })

        if action in ["generate_logo", "monogram_logo", "skip_logo"]:
            WebsiteBuilderService.add_user_message(session, message or "Generate AI Logo")
            b_name = session.collected_data.get("Business Name", "Brand")
            b_cat = session.collected_data.get("Business Category", "Business")
            theme = WebsiteBuilderService.resolve_palette(category=b_cat)

            session.collected_data["Logo"] = WebsiteBuilderService.generate_dynamic_logo(
                b_name, b_cat, theme["primary"]
            )
            session.collected_data["logo_status"] = "available"
            session.collected_data["onboarding_step"] = "confirmation"
            session.current_step = 7

            ack_gen = (
                f"Generated a custom logo for {b_name}!"
                if lang == "en" else
                f"Maine aapki dukaan '{b_name}' ke liye ek stylish logo generate kar diya hai!"
                if lang == "hinglish" else
                f"मैंने आपकी दुकान '{b_name}' के लिए नया लोगो तैयार कर दिया है!"
            )
            await WebsiteBuilderService.reply(session, ack_gen)
            await WebsiteBuilderService.show_confirmation_summary(session)
            await WebsiteBuilderService.save_session(session)

            return type("Result", (), {
                "message": session.messages[-1]["content"],
                "quick_actions": session.messages[-1].get("options", []),
                "session": session
            })

        # -----------------------------------------------------
        # GENERATION ACTION
        # -----------------------------------------------------

        if action == "generate":
            WebsiteBuilderService.add_user_message(session, message)
            return await WebsiteBuilderService.generate_website(session, user_id)

        # -----------------------------------------------------
        # NORMAL MESSAGE PROCESSING
        # -----------------------------------------------------

        WebsiteBuilderService.add_user_message(session, message)

        extracted = WebsiteBuilderService.extract_business_details(
            message,
            session.collected_data
        )

        for key, value in extracted.items():
            if value:
                session.collected_data[key] = value

        step = session.collected_data.get(
            "onboarding_step",
            "business_details"
        )

        # -----------------------------------------------------
        # STEP 1: BUSINESS CATEGORY & PRODUCTS
        # -----------------------------------------------------

        if step == "business_details":
            # Check if user message is just a greeting (e.g. "hi", "hii", "hello", "namaste")
            if WebsiteBuilderService.is_greeting(message):
                greet_msg = WebsiteBuilderService.get_localized_text("initial_greeting", lang)
                await WebsiteBuilderService.reply(session, greet_msg)
                await WebsiteBuilderService.save_session(session)
                return type("Result", (), {
                    "message": session.messages[-1]["content"],
                    "quick_actions": [],
                    "session": session
                })

            sub_step = session.collected_data.get("sub_step", "category")

            # If products/services were requested in previous turn:
            if sub_step == "products_services":
                existing_cat = session.collected_data.get("Business Category")
                is_bad_cat = existing_cat in ["Hii", "Hi", "Hello", "Hey", "", None]
                lower_m = message.lower().strip()

                is_explicit_correction = any(w in lower_m for w in [
                    "no", "not", "nahi", "actually", "galat", "wrong", "badal do", "instead", "nahi balki", "i meant"
                ]) or any(lower_m.startswith(p) for p in [
                    "i have a", "i run a", "we run a", "meri dukaan", "mera business", "humara business"
                ])

                if is_explicit_correction or is_bad_cat:
                    cat_in_prod = WebsiteBuilderService.detect_business_category(message)
                    if cat_in_prod and (cat_in_prod != existing_cat or is_bad_cat):
                        session.collected_data["Business Category"] = cat_in_prod
                        session.collected_data["sub_step"] = "products_services"
                        ask_prod_msg = WebsiteBuilderService.get_localized_text(
                            "got_category_ask_products",
                            lang,
                            category=cat_in_prod
                        )
                        await WebsiteBuilderService.reply(session, ask_prod_msg)
                        await WebsiteBuilderService.save_session(session)
                        return type("Result", (), {
                            "message": session.messages[-1]["content"],
                            "quick_actions": [],
                            "session": session
                        })

                # Normal products answer - accept user's products offerings
                candidate = message.strip()
                clean_prod = re.sub(
                    r"^(i sell|we sell|selling|i offer|we offer|services are|products are|we do|i do|everything related to|everything related|hamare paas|hum bechte hain)\s+",
                    "",
                    candidate,
                    flags=re.I
                ).strip(" .")
                products = clean_prod if clean_prod else candidate

                session.collected_data["Products/Services"] = products
                session.collected_data["onboarding_step"] = "business_name"
                session.current_step = 2

                # If user had already expressed fast build intent, ask specifically for shop name to build
                if session.collected_data.get("wants_fast_build"):
                    ask_name_msg = (
                        "Almost ready to build! What is the name of your business or shop?"
                        if lang == "en" else
                        "Website banane ke liye bas ek aakhri cheez! Apni dukaan ya business ka naam bata dijiye:"
                        if lang == "hinglish" else
                        "वेबसाइट तैयार करने के लिए बस एक जानकारी चाहिए! अपनी दुकान या व्यवसाय का नाम बताएं:"
                    )
                else:
                    ask_name_msg = WebsiteBuilderService.get_localized_text("ask_name", lang)

                await WebsiteBuilderService.reply(session, ask_name_msg)
                await WebsiteBuilderService.save_session(session)
                return type("Result", (), {
                    "message": session.messages[-1]["content"],
                    "quick_actions": [],
                    "session": session
                })

            else:
                category = (
                    WebsiteBuilderService.detect_business_category(message)
                    or session.collected_data.get("Business Category")
                )

                if not category or category in ["Hii", "Hi", "Hello", "Hey"]:
                    ask_cat_msg = WebsiteBuilderService.get_localized_text("ask_category", lang)
                    await WebsiteBuilderService.reply(session, ask_cat_msg)
                else:
                    session.collected_data["Business Category"] = category
                    products = extracted.get("Products/Services") or message.strip()
                    session.collected_data["Products/Services"] = products
                    session.collected_data["onboarding_step"] = "business_name"
                    session.current_step = 2

                    ask_name_msg = WebsiteBuilderService.get_localized_text("ask_name", lang)
                    await WebsiteBuilderService.reply(session, ask_name_msg)
                    await WebsiteBuilderService.save_session(session)
                    return type("Result", (), {
                        "message": session.messages[-1]["content"],
                        "quick_actions": [],
                        "session": session
                    })

        # -----------------------------------------------------
        # STEP 2: BUSINESS NAME
        # -----------------------------------------------------

        elif step == "business_name":
            # Check if user is actually clarifying or correcting their business category
            msg_lower = message.lower().strip()
            is_cat_phrase = any(
                msg_lower.startswith(p) for p in [
                    "no", "not", "nahi", "actually", "i mean", "badal", "wrong", "galat"
                ]
            ) or any(
                msg_lower.startswith(p) for p in [
                    "i run a", "i have a", "we run a", "meri dukaan", "mera business", "humara business"
                ]
            )

            if is_cat_phrase:
                cat_in_msg = WebsiteBuilderService.detect_business_category(message)
                if cat_in_msg:
                    session.collected_data["Business Category"] = cat_in_msg
                    ask_name_msg = WebsiteBuilderService.get_localized_text("ask_name", lang)
                    got_text = (
                        f"Got it! You run a {cat_in_msg}. "
                        if lang == "en" else
                        f"Samajh gaya! Aapka {cat_in_msg} ka business hai. "
                        if lang == "hinglish" else
                        f"समझ गया! आपका {cat_in_msg} का व्यवसाय है। "
                    )
                    await WebsiteBuilderService.reply(session, got_text + ask_name_msg)
                    await WebsiteBuilderService.save_session(session)
                    return type("Result", (), {
                        "message": session.messages[-1]["content"],
                        "quick_actions": [],
                        "session": session
                    })

            name = extracted.get("Business Name")

            if not name:
                candidate = message.strip()
                cleaned = re.sub(
                    r"^(my business name is|business name is|shop name is|store name is|it is called|it's called|it is|it's|called|name is|naam hai|dukaan ka naam)\s+",
                    "",
                    candidate,
                    flags=re.I
                ).strip(" .'")
                cleaned = re.sub(r"\s+(hai|he)$", "", cleaned, flags=re.I).strip(" .'")

                stopwords_name = {"i need", "i want", "website", "shop", "business", "no", "yes", "ok", "banao", "chahiye"}
                if (
                    len(cleaned) >= 2
                    and len(cleaned) <= 80
                    and cleaned.lower() not in stopwords_name
                ):
                    name = cleaned

            if not name:
                retry_name_msg = WebsiteBuilderService.get_localized_text("ask_name_retry", lang)
                await WebsiteBuilderService.reply(session, retry_name_msg)
            else:
                session.collected_data["Business Name"] = name

                # If current category is generic or bad ("Hii", "Business", etc.), detect from business name!
                curr_cat = session.collected_data.get("Business Category")
                if not curr_cat or curr_cat in ["Hii", "Hi", "Hello", "Hey", "Business", "Shop", "None"]:
                    cat_from_name = WebsiteBuilderService.detect_business_category(name)
                    if cat_from_name:
                        session.collected_data["Business Category"] = cat_from_name

                # Check if user had fast-build intent or message says build
                wants_fast = session.collected_data.get("wants_fast_build") or any(
                    w in message.lower() for w in ["build", "banao", "generate", "bana do", "direct"]
                )

                if wants_fast:
                    b_cat = session.collected_data.get("Business Category", "Business")
                    if not session.collected_data.get("Logo"):
                        theme = WebsiteBuilderService.resolve_palette(category=b_cat)
                        session.collected_data["Logo"] = WebsiteBuilderService.generate_dynamic_logo(
                            name, b_cat, theme["primary"]
                        )
                        session.collected_data["logo_status"] = "available"
                    if not session.collected_data.get("selected_template_name"):
                        session.collected_data["selected_template_name"] = f"{b_cat} Modern Pro"
                        session.selected_template = f"{b_cat.lower().replace(' ', '-')}-pro"

                    return await WebsiteBuilderService.generate_website(session, user_id)

                # Transition to Step 3: Location & Contact Information
                session.collected_data["onboarding_step"] = "contact_location"
                session.current_step = 3

                ask_contact_msg = (
                    f"Nice to meet you, {name}! Where is your business located (city or address), and what phone number or email should customers use to contact you?"
                    if lang == "en" else
                    f"Aapse milkar accha laga, {name}! Aapka business kahan par sthit hai (city ya address), aur contact ke liye phone number ya email kya hai?"
                    if lang == "hinglish" else
                    f"आपसे मिलकर खुशी हुई, {name}! आपका व्यवसाय कहाँ स्थित है (शहर या पता), और ग्राहक संपर्क के लिए फ़ोन नंबर या ईमेल क्या है?"
                )
                await WebsiteBuilderService.reply(session, ask_contact_msg)
                await WebsiteBuilderService.save_session(session)
                return type("Result", (), {
                    "message": session.messages[-1]["content"],
                    "quick_actions": [],
                    "session": session
                })

        # -----------------------------------------------------
        # STEP 3: CONTACT & LOCATION
        # -----------------------------------------------------

        elif step == "contact_location":
            session.collected_data["Location & Contact"] = message.strip()
            session.collected_data["Location"] = message.strip()
            session.collected_data["Contact"] = message.strip()
            b_name = session.collected_data.get("Business Name", "your business")

            session.collected_data["onboarding_step"] = "specialties_highlights"
            session.current_step = 4

            ask_spec_msg = (
                f"Got it! What are some key specialties, special services, or unique features of {b_name} that you would like highlighted on your website?"
                if lang == "en" else
                f"Samajh gaya! {b_name} ki kya khaasiyat ya special offerings hain jo aap website par dikhana chahenge?"
                if lang == "hinglish" else
                f"समझ गया! {b_name} की क्या मुख्य विशेषताएं या विशेष सेवाएँ हैं जो आप वेबसाइट पर दिखाना चाहेंगे?"
            )
            await WebsiteBuilderService.reply(session, ask_spec_msg)
            await WebsiteBuilderService.save_session(session)
            return type("Result", (), {
                "message": session.messages[-1]["content"],
                "quick_actions": [],
                "session": session
            })

        # -----------------------------------------------------
        # STEP 4: SPECIALTIES & HIGHLIGHTS
        # -----------------------------------------------------

        elif step == "specialties_highlights":
            session.collected_data["Specialties"] = message.strip()
            session.collected_data["Specialties & Highlights"] = message.strip()
            session.collected_data["industry_details"] = message.strip()

            b_name = session.collected_data.get("Business Name", "your business")

            # Transition to Step 5: Ask about Logo
            session.collected_data["onboarding_step"] = "logo_check"
            session.current_step = 5

            ask_logo_msg = (
                f"Awesome! Do you have an existing logo for **{b_name}**, or would you like me to auto-generate a custom AI logo for you?"
                if lang == "en" else
                f"Shaandar! Kya aapke paas **{b_name}** ka logo hai, ya hum aapke liye ek stylish custom AI logo generate kar dein?"
                if lang == "hinglish" else
                f"शानदार! क्या आपके पास **{b_name}** का लोगो है, या हम आपके लिए एक नया आकर्षक एआई लोगो तैयार कर दें?"
            )

            logo_options = [
                {"label": "✨ Auto-Generate AI Logo", "action": "generate_logo"},
                {"label": "📁 Upload Logo File", "action": "upload_logo"},
                {"label": "⚡ Build Directly with AI Logo", "action": "build_directly"}
            ]

            await WebsiteBuilderService.reply(session, ask_logo_msg, options=logo_options)
            await WebsiteBuilderService.save_session(session)
            return type("Result", (), {
                "message": session.messages[-1]["content"],
                "quick_actions": logo_options,
                "session": session
            })

        # -----------------------------------------------------
        # STEP 5: LOGO CHECK & GENERATION
        # -----------------------------------------------------

        elif step == "logo_check":
            b_name = session.collected_data.get("Business Name", "Business")
            b_cat = session.collected_data.get("Business Category", "Business")
            b_prod = session.collected_data.get("Products/Services", b_cat)
            b_cont = session.collected_data.get("Location & Contact", "Available upon request")
            b_spec = session.collected_data.get("Specialties", "Quality offerings & dedicated care")

            # Fast build check
            if action == "build_directly" or any(w in message.lower() for w in ["build", "banao", "generate", "direct"]):
                if not session.collected_data.get("Logo"):
                    theme = WebsiteBuilderService.resolve_palette(category=b_cat)
                    session.collected_data["Logo"] = WebsiteBuilderService.generate_dynamic_logo(
                        b_name, b_cat, theme["primary"]
                    )
                    session.collected_data["logo_status"] = "available"
                return await WebsiteBuilderService.generate_website(session, user_id)

            # Auto-generate or handle logo choice
            if not session.collected_data.get("Logo"):
                theme = WebsiteBuilderService.resolve_palette(category=b_cat)
                session.collected_data["Logo"] = WebsiteBuilderService.generate_dynamic_logo(
                    b_name, b_cat, theme["primary"]
                )
                session.collected_data["logo_status"] = "available"

            session.collected_data["onboarding_step"] = "design_choice"
            session.current_step = 6

            summary_msg = (
                f"I've generated a sleek custom logo for **{b_name}**! Here is your complete business summary:\n\n"
                f"• **Business Name:** {b_name}\n"
                f"• **Category & Products:** {b_cat} ({b_prod})\n"
                f"• **Location & Contact:** {b_cont}\n"
                f"• **Key Highlights:** {b_spec}\n"
                f"• **Logo:** Custom AI Logo Ready ✨\n\n"
                f"Would you like me to **build your website directly**, or explore curated design templates first?"
                if lang == "en" else
                f"Maine **{b_name}** ke liye ek naya custom logo taiyar kar diya hai! Aapki saari jaankari:\n\n"
                f"• **Business:** {b_name}\n"
                f"• **Category:** {b_cat} ({b_prod})\n"
                f"• **Contact:** {b_cont}\n"
                f"• **Highlights:** {b_spec}\n"
                f"• **Logo:** Taiyar hai ✨\n\n"
                f"Kya aap chahte hain ki main **seedhe website bana doon**, ya design templates dekhna chahenge?"
                if lang == "hinglish" else
                f"मैंने **{b_name}** के लिए एक नया आकर्षक लोगो तैयार कर दिया है! आपकी पूरी जानकारी:\n\n"
                f"• **व्यवसाय:** {b_name}\n"
                f"• **श्रेणी:** {b_cat} ({b_prod})\n"
                f"• **संपर्क:** {b_cont}\n"
                f"• **विशेषताएं:** {b_spec}\n"
                f"• **लोगो:** तैयार है ✨\n\n"
                f"क्या आप चाहते हैं कि मैं **सीधे वेबसाइट बना दूं**, या डिज़ाइन टेम्पलेट देखना चाहेंगे?"
            )

            design_options = [
                {"label": "⚡ Build Directly", "action": "build_directly"},
                {"label": "✨ Recommend Designs", "action": "recommend"}
            ]

            await WebsiteBuilderService.reply(session, summary_msg, options=design_options)
            await WebsiteBuilderService.save_session(session)
            return type("Result", (), {
                "message": session.messages[-1]["content"],
                "quick_actions": design_options,
                "session": session
            })

        # -----------------------------------------------------
        # STEP 5: DESIGN CHOICE
        # -----------------------------------------------------

        elif step == "design_choice":
            wants_recommend = (
                action == "recommend"
                or any(w in message.lower() for w in ["recommend", "design", "designs", "template", "templates", "dikhao", "options", "suggestions"])
            )

            if wants_recommend:
                return await WebsiteBuilderService.generate_recommendations(session)

            # Build directly: generate right now without extra loops!
            b_name = session.collected_data.get("Business Name", "My Business")
            b_cat = session.collected_data.get("Business Category", "Business")

            if not session.collected_data.get("Logo"):
                theme = WebsiteBuilderService.resolve_palette(category=b_cat)
                session.collected_data["Logo"] = WebsiteBuilderService.generate_dynamic_logo(
                    b_name, b_cat, theme["primary"]
                )
                session.collected_data["logo_status"] = "available"

            session.collected_data["selected_template_name"] = f"{b_cat} Modern Pro"
            session.collected_data["selected_template_id"] = f"{b_cat.lower().replace(' ', '-')}-pro"
            session.selected_template = f"{b_cat.lower().replace(' ', '-')}-pro"

            return await WebsiteBuilderService.generate_website(session, user_id)

        # -----------------------------------------------------
        # STEP 4: TEMPLATE SELECTION (TEXT OR CHIP)
        # -----------------------------------------------------

        elif step == "template_selection":
            # Handles user selecting or typing template name (e.g., "Sweet Heritage", "1", "Rustic Haven")
            recs = session.recommendations or []
            matched = None

            for rec in recs:
                rec_name = rec.get("name", "").lower()
                rec_id = rec.get("id", "").lower()
                if rec_name in lower_msg or rec_id in lower_msg:
                    matched = rec
                    break

            if not matched and recs:
                if "1" in message or "first" in lower_msg or "pahla" in lower_msg:
                    matched = recs[0]
                elif ("2" in message or "second" in lower_msg or "doosra" in lower_msg) and len(recs) > 1:
                    matched = recs[1]
                elif ("3" in message or "third" in lower_msg or "teesra" in lower_msg) and len(recs) > 2:
                    matched = recs[2]
                else:
                    matched = recs[0]

            if matched:
                session.selected_template = str(matched["id"])
                session.collected_data["selected_template_id"] = str(matched["id"])
                session.collected_data["selected_template_name"] = str(matched["name"])
            else:
                clean_choice = message.strip()
                session.collected_data["selected_template_name"] = clean_choice or "Custom Modern"

            session.collected_data["onboarding_step"] = "industry_details"
            session.current_step = 5
            await WebsiteBuilderService.ask_industry_question(session)

        # -----------------------------------------------------
        # STEP 5: INDUSTRY DETAILS
        # -----------------------------------------------------

        elif step == "industry_details":
            session.collected_data["industry_details"] = message.strip()
            session.collected_data["onboarding_step"] = "logo_check"
            session.current_step = 6

            # Explicitly ask user about logo (upload existing or generate new)
            await WebsiteBuilderService.ask_logo_question(session, user_id=user_id)

        # -----------------------------------------------------
        # STEP 6: LOGO CHECK
        # -----------------------------------------------------

        elif step == "logo_check":
            lower_msg = message.lower().strip()
            b_name = session.collected_data.get("Business Name", "Brand")
            b_cat = session.collected_data.get("Business Category", "Business")
            theme = WebsiteBuilderService.resolve_palette(category=b_cat)

            # Check if user wants to use saved brand logo
            wants_saved = any(
                w in lower_msg for w in ["use saved", "saved logo", "purana", "brand kit wala", "brand kit logo"]
            )
            saved_logo = session.collected_data.get("saved_brand_logo")
            if wants_saved and saved_logo:
                session.collected_data["Logo"] = saved_logo
                session.collected_data["logo_status"] = "available"
                session.collected_data["onboarding_step"] = "confirmation"
                session.current_step = 7
                await WebsiteBuilderService.show_confirmation_summary(session)
                await WebsiteBuilderService.save_session(session)
                return type("Result", (), {
                    "message": session.messages[-1]["content"],
                    "quick_actions": session.messages[-1].get("options", []),
                    "session": session
                })

            # Check if user says they do NOT have a logo or explicitly want one generated
            has_negation = any(
                neg in lower_msg for neg in [
                    "nahi", "nhi", "no", "not", "dont", "don't", "na", "without", "bina", "kuch nahi", "koi nahi"
                ]
            )
            wants_generate = (
                has_negation
                or any(
                    w in lower_msg for w in [
                        "generate", "bana do", "banao", "make", "create", "ai logo",
                        "monogram", "skip", "continue", "naya", "new", "kardo", "auto"
                    ]
                )
            )

            # Check if user says they already have a logo or want to upload
            user_has_logo = (
                not wants_generate
                and any(
                    w in lower_msg for w in [
                        "have", "upload", "paas hai", "hai logo", "mera logo", "file", "haan hai", "yes i have", "mere paas"
                    ]
                )
            )

            if user_has_logo:
                upload_prompt = (
                    f"Great! Please click below to upload your logo file for {b_name}, or click generate if you'd like a new one:"
                    if lang == "en" else
                    f"Bahut badiya! Kripya niche button par click karke '{b_name}' ka logo upload karein, ya naya AI logo generate karein:"
                    if lang == "hinglish" else
                    f"बहुत बढ़िया! कृपया नीचे बटन पर क्लिक करके '{b_name}' का लोगो अपलोड करें, या नया लोगो बनाएं:"
                )
                await WebsiteBuilderService.reply(session, upload_prompt, options=[
                    {"label": "📁 Upload Logo File", "action": "upload_logo"},
                    {"label": "✨ Auto-Generate AI Logo", "action": "generate_logo"}
                ])

            elif action == "open_brand_kit" or "brand kit" in lower_msg:
                brand_help = (
                    "You can design a logo in Brand Kit, or click below to generate an instant styled logo."
                    if lang == "en" else
                    "Aap Brand Kit me logo bana sakte hain, ya niche click karke instant AI logo ke saath continue kar sakte hain."
                    if lang == "hinglish" else
                    "आप ब्रांड किट में लोगो बना सकते हैं, या नीचे क्लिक करके तुरंत नया लोगो बना सकते हैं।"
                )
                await WebsiteBuilderService.reply(
                    session,
                    brand_help,
                    options=[
                        {"label": "✨ Auto-Generate AI Logo", "action": "generate_logo"},
                        {"label": "⚡ Monogram Logo", "action": "monogram_logo"}
                    ]
                )

            else:
                # User says "generate", "nahi hai", "no logo", "bana do", "make", "skip", "continue":
                session.collected_data["Logo"] = WebsiteBuilderService.generate_dynamic_logo(
                    b_name, b_cat, theme["primary"]
                )
                session.collected_data["logo_status"] = "generated"
                session.collected_data["onboarding_step"] = "confirmation"
                session.current_step = 7

                ack_gen = (
                    f"Generated a custom logo for {b_name}!"
                    if lang == "en" else
                    f"Maine aapki dukaan '{b_name}' ke liye ek stylish naya logo generate kar diya hai!"
                    if lang == "hinglish" else
                    f"मैंने आपकी दुकान '{b_name}' के लिए नया लोगो तैयार कर दिया है!"
                )
                await WebsiteBuilderService.reply(session, ack_gen)
                await WebsiteBuilderService.show_confirmation_summary(session)

        # -----------------------------------------------------
        # STEP 7: CONFIRMATION
        # -----------------------------------------------------

        elif step == "confirmation":
            confirm_keywords = ["yes", "confirm", "build", "generate", "haan", "banao", "bana do", "theek hai", "ready", "shuru"]
            if action == "generate" or any(w in lower_msg for w in confirm_keywords):
                return await WebsiteBuilderService.generate_website(session, user_id)

            if action == "add_page_content" or any(w in lower_msg for w in ["content", "story", "details", "mission", "hours", "address", "phone"]):
                session.collected_data["onboarding_step"] = "page_content_details"
                await WebsiteBuilderService.reply(
                    session,
                    "What specific details would you like to feature on your pages? For example, your story/mission for About, specialized offerings, or opening hours."
                )

            elif action == "edit_details":
                session.collected_data["onboarding_step"] = "industry_details"
                await WebsiteBuilderService.ask_industry_question(session)

            else:
                await WebsiteBuilderService.show_confirmation_summary(session)

        elif step == "page_content_details":
            session.collected_data["custom_page_content"] = message.strip()
            session.collected_data["onboarding_step"] = "confirmation"
            await WebsiteBuilderService.show_confirmation_summary(session)

        # -----------------------------------------------------
        # GENERATED WEBSITE EDITING
        # -----------------------------------------------------

        elif step == "generated":
            if session.website_project_id:
                project = await WebsiteBuilderService.get_website(
                    str(session.website_project_id),
                    user_id
                )
                if project:
                    current_site_data = getattr(project, "website_data", None) or {
                        "business_name": project.business_name,
                        "pages": project.pages,
                        "theme": getattr(project, "theme", {})
                    }
                    edit_res = await WebsiteBuilderService.apply_website_edit(
                        user_id=user_id,
                        session_id=str(session.id),
                        instruction=message,
                        current_state=current_site_data
                    )
                    reply_msg = edit_res.get("message") or "I have updated the website according to your instruction."
                    await WebsiteBuilderService.reply(session, reply_msg)
                else:
                    await WebsiteBuilderService.reply(
                        session,
                        "Your website is ready. You can ask me to change its images, text, colors, layout or sections."
                    )
            else:
                await WebsiteBuilderService.reply(
                    session,
                    "Your website is ready. You can ask me to change its images, text, colors, layout or sections."
                )

        await WebsiteBuilderService.save_session(session)

        return type("Result", (), {
            "message": session.messages[-1]["content"],
            "quick_actions": session.messages[-1].get("options", []),
            "session": session
        })

    @staticmethod
    async def reply(session, message, options=None, data=None):
        WebsiteBuilderService.add_ai_message(
            session,
            message,
            options=options,
            data=data
        )

    # ---------------------------------------------------------
    # CONFIRMATION SUMMARY HELPER
    # ---------------------------------------------------------

    @staticmethod
    async def show_confirmation_summary(session):
        lang = getattr(session, "language", "en")
        name = session.collected_data.get("Business Name", "Your Business")
        cat = session.collected_data.get("Business Category", "Business")
        offerings = session.collected_data.get("Products/Services", "Catalog & Services")
        design = session.collected_data.get("selected_template_name", "Modern Showcase")
        has_logo = bool(session.collected_data.get("Logo"))
        logo_status = session.collected_data.get("logo_status")
        if logo_status == "uploaded":
            logo_info = "Uploaded Custom Logo" if lang == "en" else "Aapka Uploaded Logo" if lang == "hinglish" else "अपलोड किया गया लोगो"
        elif has_logo or logo_status in ["generated", "available"]:
            logo_info = f"AI Generated ({cat})" if lang == "en" else f"AI Generated Logo ({cat})" if lang == "hinglish" else f"AI द्वारा तैयार लोगो ({cat})"
        else:
            logo_info = "AI Custom Monogram"

        summary = WebsiteBuilderService.get_localized_text(
            "summary",
            lang,
            name=name,
            category=cat,
            offerings=offerings,
            design=design,
            logo_info=logo_info
        )

        if lang == "hinglish":
            options = [
                {"label": "🚀 Website Bana Do", "action": "generate"},
                {"label": "📝 Details Add Karein", "action": "add_page_content"},
                {"label": "Details Badlein", "action": "edit_details"}
            ]
        elif lang == "hi":
            options = [
                {"label": "🚀 वेबसाइट बनाएं", "action": "generate"},
                {"label": "📝 पेज विवरण जोड़ें", "action": "add_page_content"},
                {"label": "विवरण बदलें", "action": "edit_details"}
            ]
        else:
            options = [
                {"label": "🚀 Build the Website", "action": "generate"},
                {"label": "📝 Add Specific Page Details", "action": "add_page_content"},
                {"label": "Edit Details", "action": "edit_details"}
            ]

        await WebsiteBuilderService.reply(session, summary, options=options)

    # ---------------------------------------------------------
    # INDUSTRY QUESTIONS
    # ---------------------------------------------------------

    @staticmethod
    async def ask_industry_question(session):
        category = session.collected_data.get("Business Category", "").lower()
        lang = getattr(session, "language", "en")

        questions = {
            "servers & cloud hosting": {
                "en": "What server solutions do you specialize in? For example, dedicated bare-metal, VPS, cloud instances, DDoS protection, or 24/7 managed support?",
                "hinglish": "Aapki main server services kya hain? Jaise dedicated servers, cloud VPS, web hosting, DDoS protection ya 24/7 server management?",
                "hi": "आप मुख्य रूप से किस प्रकार के सर्वर प्रदान करते हैं? जैसे डेडिकेटेड सर्वर, क्लाउड वीपीएस या वेब होस्टिंग?"
            },
            "farm house & resort": {
                "en": "What amenities or experiences do you offer? For example, swimming pool, weekend stays, organic farming, or private party bookings?",
                "hinglish": "Aapke farm house par kya suvidhayein hain? Jaise pool, weekend stay, organic food ya party booking?",
                "hi": "आपके फार्म हाउस में क्या सुविधाएं हैं? जैसे स्विमिंग पूल, वीकेंड स्टे, पार्टी बुकिंग आदि?"
            },
            "stationery & books": {
                "en": "What are your popular products? For example, school & office supplies, art materials, book collections, or printing services?",
                "hinglish": "Aapke paas main products kya hain? Jaise school/office stationery, art craft supplies, books ya printing?",
                "hi": "आपके मुख्य उत्पाद क्या हैं? जैसे स्कूल व ऑफिस स्टेशनरी, किताबें या प्रिंटिंग सेवाएँ?"
            },
            "korean sweet shop": {
                "en": "What signature Korean treats do you serve? For example, Bingsu, traditional hangwa, mochi, or Korean specialty beverages?",
                "hinglish": "Aapke yahan konsi Korean sweets special hain? Jaise Bingsu, Mochi, Korean desserts ya bubble tea?",
                "hi": "आपकी दुकान की क्या विशेषता है? जैसे बिंगसू, मोची या अन्य कोरियन मिठाइयाँ?"
            },
            "indian sweet shop": {
                "en": "What makes your sweet shop special? For example, traditional recipes, pure desi ghee sweets, or festival gift boxes?",
                "hinglish": "Aapki mithai ki dukaan ki kya khaasiyat hai? Jaise pure desi ghee mithai, festival gift hampers ya fresh rasgulla?",
                "hi": "आपकी मिठाई की क्या खासियत है? जैसे शुद्ध देसी घी की मिठाइयाँ, काजू कतली या उपहार बॉक्स?"
            },
            "flower shop": {
                "en": "Do you offer wedding decorations, custom bouquets, express same-day delivery, or plant collections?",
                "hinglish": "Kya aap custom bouquets, shaadi/event decoration ya same-day flower delivery offer karte hain?",
                "hi": "क्या आप फूलों के गुलदस्ते, सजावट या होम डिलीवरी की सेवा देते हैं?"
            },
            "gym & fitness": {
                "en": "What programs do you offer? For example, strength training, personal coaching, cardio, yoga, or weight loss plans?",
                "hinglish": "Aapke gym me kya facilities hain? Jaise strength training, personal trainer, cardio ya yoga?",
                "hi": "आपके जिम में क्या सुविधाएं हैं? जैसे स्ट्रेंथ ट्रेनिंग, पर्सनल ट्रेनर, कार्डियो या योग?"
            },
            "grocery & kirana": {
                "en": "Do you offer daily essentials, fresh fruits & vegetables, or quick home delivery?",
                "hinglish": "Kya aap daily groceries ke sath free home delivery ya fresh produce offer karte hain?",
                "hi": "क्या आप दैनिक किराना सामान और होम डिलीवरी की सुविधा प्रदान करते हैं?"
            },
            "medical & clinic": {
                "en": "What healthcare services do you provide? For example, doctor consultations, dental treatments, or pharmacy?",
                "hinglish": "Aapke clinic me kya healthcare services uplabdh hain? Jaise doctor consultation, lab tests ya pharmacy?",
                "hi": "आपके क्लीनिक में क्या चिकित्सा सेवाएँ उपलब्ध हैं?"
            }
        }

        matched_q = None
        for k, q_dict in questions.items():
            if k in category or category in k:
                matched_q = q_dict.get(lang) or q_dict.get("en")
                break

        if not matched_q:
            matched_q = WebsiteBuilderService.get_localized_text("ask_industry_default", lang)

        await WebsiteBuilderService.reply(session, matched_q)

    # ---------------------------------------------------------
    # BRAND KIT & LOGO VALIDATION
    # ---------------------------------------------------------

    @staticmethod
    async def ask_logo_question(session, user_id=None):
        """
        Explicitly asks the user about their logo:
        Whether they have an existing logo to upload, want to use a saved Brand Kit logo,
        or want the AI to generate a category-specific logo for their shop.
        """
        lang = getattr(session, "language", "en")
        b_name = session.collected_data.get("Business Name", "Your Business")
        b_cat = session.collected_data.get("Business Category", "Business")

        brand = await WebsiteBuilderService.get_saved_brand(user_id or session.user_id, session)
        saved_logo = (brand or {}).get("logo_url")

        session.collected_data["onboarding_step"] = "logo_check"
        session.current_step = 6

        if saved_logo:
            if lang == "hinglish":
                text = f"Aapke Brand Kit me ek logo pehle se saved hai. Kya aap wahi logo use karna chahenge, apna logo upload karna chahenge, ya hum '{b_name}' ke liye naya AI logo generate karein?"
                options = [
                    {"label": "✅ Use Saved Logo", "action": "use_saved_logo"},
                    {"label": "📁 Upload My Logo", "action": "upload_logo"},
                    {"label": "✨ Auto-Generate AI Logo", "action": "generate_logo"},
                    {"label": "🎨 Open Brand Kit", "action": "open_brand_kit"}
                ]
            elif lang == "hi":
                text = f"आपके ब्रांड किट में एक लोगो पहले से मौजूद है। क्या आप वही लोगो उपयोग करना चाहेंगे, नया लोगो अपलोड करना चाहेंगे, या हम '{b_name}' के लिए नया लोगो बनाएं?"
                options = [
                    {"label": "✅ पुराना लोगो उपयोग करें", "action": "use_saved_logo"},
                    {"label": "📁 नया लोगो अपलोड करें", "action": "upload_logo"},
                    {"label": "✨ नया लोगो बनाएं (AI)", "action": "generate_logo"},
                    {"label": "🎨 ब्रांड किट खोलें", "action": "open_brand_kit"}
                ]
            else:
                text = f"We found a saved logo in your Brand Kit. Would you like to use your saved logo, upload your own, or auto-generate a custom logo for '{b_name}'?"
                options = [
                    {"label": "✅ Use Saved Logo", "action": "use_saved_logo"},
                    {"label": "📁 Upload My Logo", "action": "upload_logo"},
                    {"label": "✨ Auto-Generate AI Logo", "action": "generate_logo"},
                    {"label": "🎨 Open Brand Kit", "action": "open_brand_kit"}
                ]
        else:
            if lang == "hinglish":
                text = f"Kya aapke paas '{b_name}' ka logo pehle se hai, ya hum aapke business ke hisab se ek naya AI logo generate kar dein?"
                options = [
                    {"label": "📁 Mere Paas Logo Hai (Upload)", "action": "upload_logo"},
                    {"label": "✨ Naya AI Logo Generate Karein", "action": "generate_logo"},
                    {"label": "⚡ Monogram Logo se Banao", "action": "monogram_logo"},
                    {"label": "🎨 Brand Kit me banayein", "action": "open_brand_kit"}
                ]
            elif lang == "hi":
                text = f"क्या आपके पास '{b_name}' का लोगो पहले से है, या हम आपके व्यवसाय के लिए एक नया आकर्षक लोगो तैयार कर दें?"
                options = [
                    {"label": "📁 मेरे पास लोगो है (अपलोड करें)", "action": "upload_logo"},
                    {"label": "✨ नया लोगो बनाएं (AI)", "action": "generate_logo"},
                    {"label": "⚡ मोनोग्राम लोगो के साथ बनाएं", "action": "monogram_logo"},
                    {"label": "🎨 ब्रांड किट में बनाएं", "action": "open_brand_kit"}
                ]
            else:
                text = f"Do you already have a logo for '{b_name}', or would you like me to generate a custom logo for your business?"
                options = [
                    {"label": "📁 I Have a Logo (Upload)", "action": "upload_logo"},
                    {"label": "✨ Auto-Generate AI Logo", "action": "generate_logo"},
                    {"label": "⚡ Continue with Monogram", "action": "monogram_logo"},
                    {"label": "🎨 Create in Brand Kit", "action": "open_brand_kit"}
                ]

        await WebsiteBuilderService.reply(session, text, options=options)

    @staticmethod
    async def check_logo_and_continue(user_id, session, action=None, message=""):
        logo = session.collected_data.get("Logo")
        if not logo:
            await WebsiteBuilderService.ask_logo_question(session, user_id=user_id)
            return

        session.collected_data["onboarding_step"] = "confirmation"
        session.current_step = 7
        await WebsiteBuilderService.show_confirmation_summary(session)

    # ---------------------------------------------------------
    # TEMPLATE RECOMMENDATIONS
    # ---------------------------------------------------------

    @staticmethod
    async def generate_recommendations(session):
        category = session.collected_data.get("Business Category", "Business")
        lang = getattr(session, "language", "en")

        templates_by_category = {
            "Servers & Cloud Hosting": [
                ("CloudForge Enterprise", "High-performance data center & cloud server hosting layout with uptime guarantees."),
                ("HostMatrix Infrastructure", "Clean, modern server solutions with dedicated hardware showcase and pricing plans."),
                ("Apex Cloud Network", "Sleek tech infrastructure layout highlighting VPS, scalability, and 24/7 technical support.")
            ],
            "Farm House & Resort": [
                ("Nature Retreat", "Rustic luxury design with scenic farm views and booking options."),
                ("Green Meadows", "Peaceful countryside layout highlighting outdoor amenities and stays."),
                ("Heritage Farm Stay", "Warm earthy aesthetic celebrating nature, pool, and organic food.")
            ],
            "Stationery & Books": [
                ("Page & Pen", "Organized vibrant storefront for stationery, art supplies, and gifts."),
                ("Scholar's Haven", "Clean minimalist layout highlighting publications and essentials."),
                ("Creative Corner", "Modern colorful showcase for artisan papercrafts and school supplies.")
            ],
            "Korean Sweet Shop": [
                ("K-Sweet Delight", "Trendy pastel aesthetic featuring bingsu, mochi, and specialty desserts."),
                ("Seoul Treats", "Modern minimalist Asian confectionery storefront."),
                ("Blossom Cafe", "Chic cafe and sweet shop layout with vibrant dessert photo highlights.")
            ],
            "Indian Sweet Shop": [
                ("Royal Mithai", "Traditional Indian sweets with a premium royal design."),
                ("Sweet Heritage", "Warm traditional design with rich product galleries."),
                ("Modern Mithai", "Clean modern storefront for Indian sweets and hampers.")
            ],
            "Flower Shop": [
                ("Floral Elegance", "Elegant floral photography and soft romantic colors."),
                ("Bloom & Blossom", "Modern bouquet-focused storefront with delivery highlights."),
                ("Botanical Garden", "Natural botanical layout with green accents and plant collections.")
            ],
            "Gym & Fitness": [
                ("Iron Forge Fitness", "Bold fitness-focused design with workout program highlights."),
                ("Pulse Athletics", "Modern athletic website with strong membership CTAs."),
                ("Zenith Wellness", "Premium wellness, yoga, and fitness layout.")
            ],
            "Restaurant & Cafe": [
                ("Culinary Premium", "Elegant dining presentation with signature menu showcases."),
                ("Modern Bistro", "Modern food-focused layout with table booking options."),
                ("Taste & Tradition", "Warm hospitality design highlighting authentic flavors.")
            ],
            "Clothing & Fashion": [
                ("Style Avenue", "Premium fashion storefront with lookbook and collections."),
                ("Minimal Wardrobe", "Minimal product-led layout for modern apparel."),
                ("Urban Collection", "Bold contemporary fashion design.")
            ],
            "Grocery & Kirana": [
                ("Daily Fresh Mart", "Organized essentials catalog with express pickup and local delivery."),
                ("Green Pantry", "Fresh farm produce and daily grocery showcase."),
                ("Quick Kirana", "Vibrant community storefront with daily deals.")
            ],
            "Medical & Clinic": [
                ("HealthFirst Care", "Clean, trustworthy medical presentation with appointment booking."),
                ("Vitality Wellness", "Modern healthcare and clinic layout with doctor profiles."),
                ("Apex Dental & Care", "Professional healthcare showcase with service breakdown.")
            ]
        }

        # Match category flexibly
        selected = None
        for cat_key, t_list in templates_by_category.items():
            if cat_key.lower() in category.lower() or category.lower() in cat_key.lower():
                selected = t_list
                break

        if not selected:
            clean_cat = category.strip() or "Business"
            selected = [
                (f"{clean_cat} Premier", f"Modern professional layout designed specifically for {clean_cat}."),
                (f"{clean_cat} Showcase", f"Vibrant showcase highlighting your signature {clean_cat} offerings."),
                (f"{clean_cat} Classic", f"Clean, elegant storefront presenting your services and brand story.")
            ]

        recommendations = []
        for index, (name, description) in enumerate(selected):
            rec_id = f"{category.lower().replace(' ', '-')}-{index + 1}"
            recommendations.append({
                "id": rec_id,
                "templateId": rec_id,
                "templateName": name,
                "name": name,
                "label": name,
                "action": "select_template",
                "description": description,
                "reason": f"Designed for {category}",
                "style": name
            })

        session.recommendations = recommendations
        session.collected_data["onboarding_step"] = "template_selection"
        session.current_step = 4

        intro_text = WebsiteBuilderService.get_localized_text("templates_intro", lang, category=category)
        await WebsiteBuilderService.reply(session, intro_text, options=recommendations)
        await WebsiteBuilderService.save_session(session)

        return type("Result", (), {
            "message": session.messages[-1]["content"],
            "quick_actions": recommendations,
            "session": session
        })

    # ---------------------------------------------------------
    # WEBSITE GENERATION
    # ---------------------------------------------------------

    @staticmethod
    def build_fallback_site_data(
        business_name: str,
        category: str,
        products: str,
        service_tab_name: str,
        location: str,
        contact: str,
        specialties: str,
        logo: str,
        theme: dict
    ) -> dict:
        nav_tabs = ["Home", "About", service_tab_name, "Contact"]
        return {
            "business_name": business_name,
            "business_category": category,
            "logo": logo,
            "theme": theme,
            "navigation": nav_tabs,
            "pages": [
                {
                    "name": "Home",
                    "sections": [
                        {
                            "type": "navbar",
                            "title": business_name,
                            "logo": logo,
                            "navigation": nav_tabs
                        },
                        {
                            "type": "hero",
                            "title": f"Welcome to {business_name}",
                            "subtitle": f"Premier {category} offering top-tier {products}. Experience genuine quality and exceptional care in {location}.",
                            "cta": f"Explore {service_tab_name}",
                            "secondary_cta": "Our Story",
                            "image_prompt": f"aesthetic modern {category} studio storefront showcase"
                        },
                        {
                            "type": "stats",
                            "title": "Key Highlights",
                            "subtitle": "Trusted performance and verified quality",
                            "items": [
                                { "label": "Satisfaction Rate", "value": "100%", "description": "Guaranteed quality in every order" },
                                { "label": "Happy Clients", "value": "5,000+", "description": "Delivering happiness consistently" },
                                { "label": "Turnaround Time", "value": "Prompt", "description": "Quick & dependable service" },
                                { "label": "Verified Rating", "value": "4.9 ★", "description": "Top-rated by customers" }
                            ]
                        },
                        {
                            "type": "features",
                            "title": "Signature Highlights",
                            "subtitle": f"Discover what makes {business_name} truly unique",
                            "items": [
                                {
                                    "title": "Premium Quality Selection",
                                    "description": f"Carefully curated {products} tailored to your personal taste.",
                                    "image_prompt": f"premium luxury {category} detail photograph"
                                },
                                {
                                    "title": "Customer First Experience",
                                    "description": f"Personalized care, attentive assistance, and transparent service for every client.",
                                    "image_prompt": f"friendly helpful {category} customer service"
                                },
                                {
                                    "title": "Prompt & Dependable",
                                    "description": f"Fast turnaround, reliable delivery, and guaranteed satisfaction in {location}.",
                                    "image_prompt": f"clean professional {category} packaging delivery"
                                }
                            ]
                        },
                        {
                            "type": "about",
                            "title": f"About {business_name}",
                            "subtitle": "Devoted to Excellence & Craftsmanship",
                            "description": f"At {business_name}, we are passionate about bringing you the best {category} solutions. With a focus on quality, comfort, and personalized care, our team works tirelessly to ensure your experience is nothing short of extraordinary.",
                            "image_prompt": f"warm welcoming {category} interior workspace"
                        },
                        {
                            "type": "testimonials",
                            "title": "What Our Customers Say",
                            "subtitle": "Real experiences from our delighted clients",
                            "items": [
                                { "name": "Priya Sharma", "role": "Verified Customer", "rating": 5, "quote": f"{business_name} exceeded all my expectations! Outstanding quality and super prompt service." },
                                { "name": "Rahul Mehta", "role": "Frequent Client", "rating": 5, "quote": f"The attention to detail and personalized touch make {business_name} my go-to choice every single time." },
                                { "name": "Ananya Roy", "role": "Happy Client", "rating": 5, "quote": f"Authentic, dependable, and highly recommended. A wonderful experience from start to finish." }
                            ]
                        },
                        {
                            "type": "cta",
                            "title": f"Ready to Experience {business_name}?",
                            "subtitle": f"Connect with us today in {location}. We are here to assist you with prompt, personalized service.",
                            "cta": "Get in Touch"
                        },
                        {
                            "type": "footer",
                            "title": business_name,
                            "logo": logo
                        }
                    ]
                },
                {
                    "name": "About",
                    "sections": [
                        {
                            "type": "navbar",
                            "title": business_name,
                            "logo": logo,
                            "navigation": nav_tabs
                        },
                        {
                            "type": "about",
                            "title": f"Our Story & Heritage",
                            "subtitle": f"The Journey of {business_name}",
                            "description": f"Founded with a vision to redefine excellence in {category}, {business_name} has grown from a humble beginning into a cherished destination. We take pride in {specialties}, ensuring every single customer receives unmatched attention and world-class standards.",
                            "image_prompt": f"inspirational authentic {category} story craft workshop"
                        },
                        {
                            "type": "features",
                            "title": "Our Core Values",
                            "subtitle": "Principles that drive everything we do",
                            "items": [
                                { "title": "Integrity & Trust", "description": "Honest recommendations and fair pricing every day." },
                                { "title": "Bespoke Quality", "description": "No compromises on standards, ingredients, or craftsmanship." },
                                { "title": "Community Connection", "description": f"Proudly serving and supporting our local patrons in {location}." }
                            ]
                        },
                        {
                            "type": "footer",
                            "title": business_name,
                            "logo": logo
                        }
                    ]
                },
                {
                    "name": service_tab_name,
                    "sections": [
                        {
                            "type": "navbar",
                            "title": business_name,
                            "logo": logo,
                            "navigation": nav_tabs
                        },
                        {
                            "type": "products" if service_tab_name == "Products" else "services",
                            "title": f"Signature {service_tab_name}",
                            "subtitle": f"Explore our handcrafted selection of {products}",
                            "items": [
                                { "title": "Signature Collection", "description": f"Our flagship {category} offering crafted for true enthusiasts.", "price": "Featured", "image_prompt": f"premium {category} product showcase 1" },
                                { "title": "Popular Favorite", "description": "Loved by thousands of satisfied customers for its dependability.", "price": "Top Seller", "image_prompt": f"popular {category} offering 2" },
                                { "title": "Custom Bespoke Package", "description": "Tailored specifically around your individual requirements.", "price": "Custom Quote", "image_prompt": f"bespoke tailored {category} package 3" },
                                { "title": "Seasonal Special", "description": "Fresh, timely creations available for a limited time.", "price": "Special Offer", "image_prompt": f"fresh seasonal {category} special 4" }
                            ]
                        },
                        {
                            "type": "gallery",
                            "title": "Showcase Gallery",
                            "subtitle": f"A glimpse into {business_name}",
                            "items": [
                                { "title": "Artisan Craftsmanship", "image_prompt": f"{category} detailed showcase photo 1" },
                                { "title": "Studio Atmosphere", "image_prompt": f"{category} studio interior photo 2" },
                                { "title": "Client Experience", "image_prompt": f"{category} client delight photo 3" },
                                { "title": "Finished Creations", "image_prompt": f"{category} finished display photo 4" }
                            ]
                        },
                        {
                            "type": "footer",
                            "title": business_name,
                            "logo": logo
                        }
                    ]
                },
                {
                    "name": "Contact",
                    "sections": [
                        {
                            "type": "navbar",
                            "title": business_name,
                            "logo": logo,
                            "navigation": nav_tabs
                        },
                        {
                            "type": "contact",
                            "title": "Contact & Visit Us",
                            "subtitle": f"We are here to assist you. Connect with {business_name} today.",
                            "location": location,
                            "phone": contact,
                            "hours": "Mon - Sat: 9:00 AM - 8:00 PM"
                        },
                        {
                            "type": "footer",
                            "title": business_name,
                            "logo": logo
                        }
                    ]
                }
            ]
        }

    @staticmethod
    async def generate_website(session, user_id=None):
        collected = session.collected_data

        business_name = collected.get("Business Name")
        category = collected.get("Business Category")
        lang = getattr(session, "language", "en") or "en"

        if not business_name or not category:
            raise HTTPException(
                400,
                "Business name and category are required."
            )

        # Dynamic fallback: if user has no logo, auto-generate a beautiful initials monogram
        # so generation NEVER blocks or halts!
        if not collected.get("Logo"):
            brand = collected.get("Brand Guidelines") or {}
            theme = WebsiteBuilderService.resolve_palette(category=category, brand_guidelines=brand)
            collected["Logo"] = WebsiteBuilderService.generate_dynamic_logo(
                business_name, category, theme["primary"]
            )
            collected["logo_status"] = "available"

        WebsiteBuilderService.add_ai_message(
            session,
            "Creating your website. Preparing your layout, content and images...",
            message_type="generation_status"
        )

        await WebsiteBuilderService.save_session(session)

        brand = collected.get("Brand Guidelines") or {}

        theme = WebsiteBuilderService.resolve_palette(
            category=category,
            brand_guidelines=brand
        )

        logo = collected["Logo"]

        offerings = collected.get("Products/Services", "")
        details = collected.get("industry_details", "")

        ai = AIProviderFactory.get_provider(preferred="openai")

        service_tab_name = "Products" if any(w in category.lower() for w in ["shop", "store", "flower", "sweet", "boutique", "bakery", "jewel"]) else "Services"

        prompt = f"""
Create a complete, modern, multi-page professional website for this business.

BUSINESS NAME: {business_name}
BUSINESS CATEGORY: {category}
PRODUCTS/SERVICES: {offerings}
ADDITIONAL DETAILS: {details}
CUSTOM PAGE CONTENT & STORY: {collected.get('custom_page_content', '')}
SELECTED TEMPLATE: {collected.get('selected_template_name')}

REQUIREMENTS:
1. Multi-Page Architecture: Generate 4 distinct pages in the "pages" array:
   - "Home": A rich, comprehensive storefront featuring:
     1. Navbar: Business name and navigation links.
     2. Hero Section: Punchy headline, compelling subtitle, badge pill, primary CTA, secondary CTA, and hero image prompt.
     3. Key Metrics / Stats Bar: 4 numerical business highlights (e.g. "100% Quality Guaranteed", "5,000+ Happy Customers", "Fast Turnaround", "4.9/5 Rating").
     4. Signature Highlights (Features): 3 to 4 core offerings/strengths with title, description, and image prompt.
     5. Brand Story & Craftsmanship (About preview): Engaging narrative detailing background, quality standards, and customer commitment.
     6. Customer Testimonials: 3 realistic customer reviews with 5-star ratings, quotes, reviewer name, and role/location.
     7. Frequently Asked Questions (FAQ): 4 high-value questions and answers addressing customer needs, orders, and quality guarantees.
     8. Call to Action (CTA) Banner: Bold closing banner inviting direct inquiries or orders.
     9. Footer: Business name and logo.
   - "About": Featuring Navbar, Full Brand Story / Mission, Core Values / Why Choose Us, and Footer.
   - "{service_tab_name}": Featuring Navbar, Comprehensive Offerings / Catalog (4 to 6 items with title, detailed description, realistic starting price/estimate, and image_prompt), Visual Showcase / Gallery (4 items), and Footer.
   - "Contact": Featuring Navbar, Full Contact Information, Opening Hours, Inquiry / Message Form, and Footer.

2. Navbar & Branding:
   - Every page MUST have a "navbar" section with:
     "title": "{business_name}",
     "logo": "{logo}",
     "navigation": ["Home", "About", "{service_tab_name}", "Contact"]
   - The business name and logo MUST appear together in the navbar.

3. Hero Section:
   - On the "Home" page, include an impactful "hero" section with:
     "title": Captivating, punchy headline tailored specifically to {business_name} and {category}.
     "subtitle": Engaging value proposition (20-35 words).
     "cta": "Explore Offerings" or "Get Started"
     "secondary_cta": "About Us"
     "image_prompt": "High-end professional photography representing {category} and {business_name}"

4. Category Specifics:
   - All section titles, descriptions, and image prompts MUST strictly match {category}.
   - Never invent personal phone numbers, addresses, ratings, or customer count metrics.

Return ONLY valid JSON with this exact structure:

{{
  "business_name": "{business_name}",
  "business_category": "{category}",
  "logo": "{logo}",
  "theme": {{
    "primary": "{theme['primary']}",
    "secondary": "{theme['secondary']}",
    "accent": "{theme['accent']}",
    "font": "outfit"
  }},
  "navigation": ["Home", "About", "{service_tab_name}", "Contact"],
  "pages": [
    {{
      "name": "Home",
      "sections": [
        {{
          "type": "navbar",
          "title": "{business_name}",
          "logo": "{logo}",
          "navigation": ["Home", "About", "{service_tab_name}", "Contact"]
        }},
        {{
          "type": "hero",
          "title": "Business Headline",
          "subtitle": "Inspiring value proposition tailored to {category}",
          "cta": "Explore Now",
          "secondary_cta": "Learn More",
          "image_prompt": "High resolution photograph for {category}",
          "image_url": ""
        }},
        {{
          "type": "stats",
          "title": "Key Highlights",
          "subtitle": "Trusted performance and verified quality",
          "items": [
            {{ "label": "Satisfaction Rate", "value": "100%", "description": "Guaranteed quality in every order" }},
            {{ "label": "Happy Clients", "value": "5,000+", "description": "Delivering happiness consistently" }},
            {{ "label": "Turnaround Time", "value": "Prompt", "description": "Quick & dependable service" }},
            {{ "label": "Verified Rating", "value": "4.9 ★", "description": "Top-rated by customers" }}
          ]
        }},
        {{
          "type": "features",
          "title": "Signature Highlights",
          "subtitle": "Discover our signature {offerings or category}",
          "items": [
            {{
              "title": "Signature Item 1",
              "description": "Specific description",
              "image_prompt": "Photograph of item 1",
              "image_url": ""
            }},
            {{
              "title": "Signature Item 2",
              "description": "Specific description",
              "image_prompt": "Photograph of item 2",
              "image_url": ""
            }},
            {{
              "title": "Signature Item 3",
              "description": "Specific description",
              "image_prompt": "Photograph of item 3",
              "image_url": ""
            }}
          ]
        }},
        {{
          "type": "about",
          "title": "Welcome to {business_name}",
          "subtitle": "Devoted to Excellence & Craftsmanship",
          "description": "Engaging introduction to our business and dedication.",
          "image_prompt": "Warm professional photograph of {category} space",
          "image_url": ""
        }},
        {{
          "type": "testimonials",
          "title": "What Our Customers Say",
          "subtitle": "Real experiences from valued clients",
          "items": [
            {{ "name": "Priya Sharma", "role": "Verified Customer", "rating": 5, "quote": "Exceptional quality and attentive service. Exceeded all our expectations!" }},
            {{ "name": "Rahul Verma", "role": "Regular Client", "rating": 5, "quote": "Remarkable attention to detail and authenticity. Our first choice every time." }},
            {{ "name": "Ananya Patel", "role": "Community Member", "rating": 5, "quote": "Fast, courteous, and dependable service with genuine care." }}
          ]
        }},
        {{
          "type": "faq",
          "title": "Frequently Asked Questions",
          "subtitle": "Common inquiries about our {category} offerings",
          "items": [
            {{ "question": "How do I place an inquiry or order?", "answer": "You can reach out directly via our Contact page or call our desk." }},
            {{ "question": "Do you provide custom requests?", "answer": "Yes, we specialize in tailored requests suited to your needs." }},
            {{ "question": "What is your quality guarantee?", "answer": "Every offering is backed by our strict quality standards." }},
            {{ "question": "What are your delivery options?", "answer": "We offer reliable, prompt turnaround for all orders." }}
          ]
        }},
        {{
          "type": "cta",
          "title": "Ready to Experience {business_name}?",
          "subtitle": "Reach out to us today for personalized solutions and inquiries.",
          "cta": "Get in Touch",
          "secondary_cta": "Explore Offerings"
        }},
        {{
          "type": "footer",
          "title": "{business_name}",
          "logo": "{logo}"
        }}
      ]
    }},
    {{
      "name": "About",
      "sections": [
        {{
          "type": "navbar",
          "title": "{business_name}",
          "logo": "{logo}",
          "navigation": ["Home", "About", "{service_tab_name}", "Contact"]
        }},
        {{
          "type": "about",
          "title": "Our Journey & Passion",
          "subtitle": "Committed to excellence in {category}",
          "description": "Detailed background about our craft, standards, and customer commitment.",
          "image_prompt": "Artisan/professional at work in {category}",
          "image_url": ""
        }},
        {{
          "type": "features",
          "title": "Why Choose {business_name}",
          "subtitle": "Our core principles & service promises",
          "items": [
            {{ "title": "Premium Quality", "description": "Highest standards in every offering." }},
            {{ "title": "Tailored Care", "description": "Personalized service for every client." }},
            {{ "title": "Trusted Expertise", "description": "Experienced and passionate professionals." }}
          ]
        }},
        {{
          "type": "footer",
          "title": "{business_name}",
          "logo": "{logo}"
        }}
      ]
    }},
    {{
      "name": "{service_tab_name}",
      "sections": [
        {{
          "type": "navbar",
          "title": "{business_name}",
          "logo": "{logo}",
          "navigation": ["Home", "About", "{service_tab_name}", "Contact"]
        }},
        {{
          "type": "products",
          "title": "Our Offerings & Catalog",
          "subtitle": "Explore our full range of {offerings or category}",
          "items": [
            {{
              "title": "Offering 1",
              "description": "Detailed description of offering 1",
              "price": "Starts from inquiry",
              "image_prompt": "Photograph for offering 1",
              "image_url": ""
            }},
            {{
              "title": "Offering 2",
              "description": "Detailed description of offering 2",
              "price": "Starts from inquiry",
              "image_prompt": "Photograph for offering 2",
              "image_url": ""
            }},
            {{
              "title": "Offering 3",
              "description": "Detailed description of offering 3",
              "price": "Starts from inquiry",
              "image_prompt": "Photograph for offering 3",
              "image_url": ""
            }},
            {{
              "title": "Offering 4",
              "description": "Detailed description of offering 4",
              "price": "Starts from inquiry",
              "image_prompt": "Photograph for offering 4",
              "image_url": ""
            }}
          ]
        }},
        {{
          "type": "gallery",
          "title": "Showcase Gallery",
          "subtitle": "A glimpse of our work and atmosphere",
          "items": [
            {{ "title": "Gallery 1", "image_prompt": "Photo of {category} showcase 1" }},
            {{ "title": "Gallery 2", "image_prompt": "Photo of {category} showcase 2" }},
            {{ "title": "Gallery 3", "image_prompt": "Photo of {category} showcase 3" }},
            {{ "title": "Gallery 4", "image_prompt": "Photo of {category} showcase 4" }}
          ]
        }},
        {{
          "type": "footer",
          "title": "{business_name}",
          "logo": "{logo}"
        }}
      ]
    }},
    {{
      "name": "Contact",
      "sections": [
        {{
          "type": "navbar",
          "title": "{business_name}",
          "logo": "{logo}",
          "navigation": ["Home", "About", "{service_tab_name}", "Contact"]
        }},
        {{
          "type": "contact",
          "title": "Contact & Visit Us",
          "subtitle": "Reach out directly with inquiries, orders, or bookings.",
          "hours": "Mon - Sat: 9:00 AM - 8:00 PM"
        }},
        {{
          "type": "footer",
          "title": "{business_name}",
          "logo": "{logo}"
        }}
      ]
    }}
  ]
}}
"""

        result = None
        try:
            result = await ai.generate_json(
                prompt,
                system_prompt=(
                    "You are a professional website designer and developer. "
                    "Generate a complete multi-page website in JSON with Home, About, Services/Products, and Contact pages. "
                    "Ensure every page has a proper navbar with business name and navigation links, an engaging hero section, and category-relevant content. "
                    "Never invent factual business information."
                ),
                temperature=0.3,
                max_tokens=8192
            )
        except Exception as ai_err:
            logger.warning(f"AI generation call had an issue ({ai_err}), using robust deterministic builder.")
            result = None

        if not isinstance(result, dict) or not result.get("pages"):
            loc_val = collected.get("Location") or collected.get("Location & Contact") or "City Center"
            con_val = collected.get("Contact") or collected.get("Location & Contact") or "contact@example.com"
            spec_val = collected.get("Specialties") or collected.get("Specialties & Highlights") or collected.get("industry_details") or "Authentic quality & excellence"
            result = WebsiteBuilderService.build_fallback_site_data(
                business_name=business_name,
                category=category,
                products=collected.get("Products/Services") or category,
                service_tab_name=service_tab_name,
                location=loc_val,
                contact=con_val,
                specialties=spec_val,
                logo=logo,
                theme=theme
            )

        pages = result["pages"]
        navigation_tabs = ["Home", "About", service_tab_name, "Contact"]

        # Ensure Home Page is rich and fully populated with all core storefront sections
        home_page = next((p for p in pages if p.get("name", "").lower() == "home"), None)
        if home_page:
            h_sections = home_page.get("sections", [])
            sec_types = [s.get("type", "").lower() for s in h_sections if isinstance(s, dict)]

            # 1. Stats bar right after hero
            if "stats" not in sec_types:
                stats_sec = WebsiteBuilderService.get_default_stats_section(category)
                hero_idx = next((i for i, s in enumerate(h_sections) if s.get("type") == "hero"), -1)
                if hero_idx != -1:
                    h_sections.insert(hero_idx + 1, stats_sec)
                else:
                    h_sections.insert(1, stats_sec)

            # 2. Testimonials section
            sec_types = [s.get("type", "").lower() for s in h_sections if isinstance(s, dict)]
            if "testimonials" not in sec_types:
                test_sec = WebsiteBuilderService.get_default_testimonials_section(business_name, category)
                footer_idx = next((i for i, s in enumerate(h_sections) if s.get("type") == "footer"), len(h_sections))
                h_sections.insert(footer_idx, test_sec)

            # 3. FAQ section
            sec_types = [s.get("type", "").lower() for s in h_sections if isinstance(s, dict)]
            if "faq" not in sec_types:
                faq_sec = WebsiteBuilderService.get_default_faq_section(business_name, category)
                footer_idx = next((i for i, s in enumerate(h_sections) if s.get("type") == "footer"), len(h_sections))
                h_sections.insert(footer_idx, faq_sec)

            # 4. CTA conversion banner
            sec_types = [s.get("type", "").lower() for s in h_sections if isinstance(s, dict)]
            if "cta" not in sec_types:
                cta_sec = WebsiteBuilderService.get_default_cta_section(business_name, category)
                footer_idx = next((i for i, s in enumerate(h_sections) if s.get("type") == "footer"), len(h_sections))
                h_sections.insert(footer_idx, cta_sec)

        for page in pages:
            for section_index, section in enumerate(
                page.get("sections", [])
            ):
                if not isinstance(section, dict):
                    continue

                section_type = section.get("type", "")

                if section_type == "navbar":
                    section["logo"] = logo
                    section["title"] = business_name
                    section["navigation"] = navigation_tabs

                if section_type == "footer":
                    section["logo"] = logo
                    section["title"] = business_name

                if section_type == "hero":
                    section["image_url"] = (
                        WebsiteBuilderService.resolve_curated_image(
                            category,
                            section.get("image_prompt", category),
                            section_index,
                            True
                        )
                    )

                if section_type in ["about", "story"]:
                    section["image_url"] = (
                        WebsiteBuilderService.resolve_curated_image(
                            category,
                            section.get("image_prompt", f"about {category}"),
                            section_index + 1,
                            False
                        )
                    )

                for item_index, item in enumerate(
                    section.get("items", [])
                ):
                    if isinstance(item, dict):
                        item_prompt = item.get("image_prompt") or item.get("title") or category
                        item["image_url"] = (
                            WebsiteBuilderService.resolve_curated_image(
                                category,
                                item_prompt,
                                item_index + 2,
                                False
                            )
                        )

        result["business_name"] = business_name
        result["business_category"] = category
        result["logo"] = logo
        result["theme"] = theme
        result["navigation"] = navigation_tabs

        project = WebsiteProject(
            user_id=session.user_id,
            business_id=collected.get("business_id"),
            business_name=business_name,
            session_id=str(session.id),
            template_id=str(session.selected_template or "default"),
            language=session.language or "English",
            pages=pages,
            theme=theme,
            status="draft",
            website_data=result
        )

        collection = await WebsiteBuilderService.get_project_collection()

        doc = project.model_dump(
            by_alias=True,
            exclude={"id"}
        )

        doc["logo"] = logo

        inserted = await collection.insert_one(doc)

        project.id = str(inserted.inserted_id)

        session.website_project_id = project.id
        session.current_step = 8

        collected["onboarding_step"] = "generated"

        style_options = [
            {"label": "🎨 Change Theme Color", "action": "open_theme_modal", "tab": "colors"},
            {"label": "🔤 Change Font Theme", "action": "open_theme_modal", "tab": "fonts"},
            {"label": "🔘 Change Button Colors", "action": "open_theme_modal", "tab": "buttons"}
        ]

        await WebsiteBuilderService.reply(
            session,
            (
                f"Your website for {business_name} has been generated! "
                "You can now preview and edit it below, or customize your theme color, font, and button styling."
            ) if lang == "en" else (
                f"Aapki dukaan '{business_name}' ki website generate ho chuki hai! "
                "Aap live preview dekh sakte hain, ya theme color, font, aur button colors badal sakte hain."
            ) if lang == "hinglish" else (
                f"आपकी दुकान '{business_name}' की वेबसाइट तैयार हो चुकी है! "
                "आप लाइव प्रिव्यू देख सकते हैं, या थीम रंग, फ़ॉन्ट, और बटन रंग बदल सकते हैं।"
            ),
            options=style_options,
            data={
                "siteId": project.id,
                "generatedSiteData": result
            }
        )

        await WebsiteBuilderService.save_session(session)

        return type("Result", (), {
            "message": "Website generated successfully.",
            "quick_actions": style_options,
            "session": session,
            "site_id": project.id,
            "generated_site_data": doc
        })

    # ---------------------------------------------------------
    # WEBSITE REVISION
    # ---------------------------------------------------------

    @staticmethod
    async def revise_website(
        project_id: str,
        user_id: str,
        instructions: str
    ):

        site = await WebsiteBuilderService.get_website(
            project_id,
            user_id
        )

        if not site:
            raise HTTPException(404, "Website not found")

        ai = AIProviderFactory.get_provider(preferred="openai")

        prompt = f"""
Modify this existing website.

Business: {site.business_name}

Instructions:
{instructions}

Existing pages:
{json.dumps(site.pages, default=str)}

Rules:
- Preserve the business category.
- Preserve all unrelated sections.
- Modify only what the user requests.
- Never introduce unrelated images.
- Never invent business information.
- Return the complete updated pages array as JSON.
"""

        result = await ai.generate_json(
            prompt,
            system_prompt=(
                "You are an expert website editor. "
                "Make minimal and safe changes."
            ),
            temperature=0.2,
            max_tokens=8192
        )

        pages = result.get("pages") if isinstance(result, dict) else None

        if not pages:
            raise HTTPException(
                502,
                "The AI could not produce a valid website revision."
            )

        collection = await WebsiteBuilderService.get_project_collection()

        await collection.update_one(
            {
                "_id": ObjectId(project_id),
                "user_id": user_id
            },
            {
                "$set": {
                    "pages": pages,
                    "website_data.pages": pages,
                    "updated_at": datetime.now(timezone.utc)
                },
                "$inc": {"version": 1}
            }
        )

        site.pages = pages

        return site

    # ---------------------------------------------------------
    # DIRECT EDIT
    # ---------------------------------------------------------

    @staticmethod
    async def apply_website_edit(
        user_id: str,
        session_id: str,
        instruction: str,
        current_state: dict
    ):

        session = await WebsiteBuilderService.get_session(
            session_id,
            user_id
        )

        if not session:
            return {
                "action": "error",
                "message": "Website session not found."
            }

        category = session.collected_data.get(
            "Business Category",
            ""
        )

        b_name = session.collected_data.get('Business Name') or current_state.get('business_name', 'Business')

        # Repair any corrupted category (e.g. if mistakenly recorded as 'Hii' or greeting)
        resolved_category = (
            WebsiteBuilderService.detect_business_category(b_name + " " + instruction)
            or WebsiteBuilderService.detect_business_category(b_name)
        )
        if resolved_category and (category in ["Hii", "Hi", "Hello", "Hey", "", None] or resolved_category in ["Medical & Clinic", "Farm House & Resort", "Stationery & Books"]):
            category = resolved_category
            session.collected_data["Business Category"] = category
            if session.website_project_id:
                p_coll = await WebsiteBuilderService.get_project_collection()
                await p_coll.update_one(
                    {"_id": ObjectId(session.website_project_id), "user_id": user_id},
                    {"$set": {"business_category": category, "website_data.business_category": category}}
                )

        lang = WebsiteBuilderService.detect_language_mode(instruction, getattr(session, "language", "en"))
        session.language = lang

        lower_category = (category or "").lower()
        lower_instruction = instruction.lower()

        # Check if the user is asking to generate, fix, or update the logo
        is_logo_request = any(w in lower_instruction for w in ["logo", "لوगो", "लोगो", "monogram", "brand mark", "icon"])
        new_logo = None

        if is_logo_request:
            brand = session.collected_data.get("Brand Guidelines") or {}
            theme = WebsiteBuilderService.resolve_palette(category=category, brand_guidelines=brand)
            new_logo = WebsiteBuilderService.generate_dynamic_logo(b_name, category, theme["primary"])
            session.collected_data["Logo"] = new_logo
            session.collected_data["logo_status"] = "available"
            current_state["logo"] = new_logo

        logo = new_logo or session.collected_data.get('Logo') or current_state.get('logo', '')

        # -----------------------------------------------------
        # THEME COLOR, FONT THEME & BUTTON COLOR PROCESSOR
        # -----------------------------------------------------
        is_button_edit = any(w in lower_instruction for w in ["button", "btn", "बटन", "cta", "button color", "button style"])
        is_font_edit = any(w in lower_instruction for w in ["font", "typeface", "typography", "text style", "फ़ॉन्ट", "फॉन्ट"])
        is_theme_color_edit = any(w in lower_instruction for w in [
            "theme color", "palette", "background", "rang", "रंग", "theme ka color",
            "website color", "primary color", "update colors", "change color", "change colors",
            "colors", "color change", "color badal", "color badlo", "rang badlo"
        ])

        COLOR_MAP = {
            "emerald": ("#059669", "#047857"),
            "green": ("#059669", "#047857"),
            "हरा": ("#059669", "#047857"),
            "blue": ("#0284C7", "#0369A1"),
            "ocean": ("#0284C7", "#0369A1"),
            "नीला": ("#0284C7", "#0369A1"),
            "indigo": ("#4F46E5", "#4338CA"),
            "navy": ("#1E40AF", "#1E3A8A"),
            "red": ("#DC2626", "#B91C1C"),
            "crimson": ("#E11D48", "#BE123C"),
            "rose": ("#E11D48", "#BE123C"),
            "लाल": ("#DC2626", "#B91C1C"),
            "orange": ("#EA580C", "#C2410C"),
            "sunset": ("#EA580C", "#C2410C"),
            "coral": ("#F97316", "#EA580C"),
            "संतरी": ("#EA580C", "#C2410C"),
            "नारंगी": ("#EA580C", "#C2410C"),
            "amber": ("#D97706", "#B45309"),
            "gold": ("#D97706", "#B45309"),
            "yellow": ("#EAB308", "#CA8A04"),
            "पीला": ("#D97706", "#B45309"),
            "purple": ("#7C3AED", "#6D28D9"),
            "violet": ("#7C3AED", "#6D28D9"),
            "बैंगनी": ("#7C3AED", "#6D28D9"),
            "pink": ("#EC4899", "#DB2777"),
            "गुलाबी": ("#EC4899", "#DB2777"),
            "teal": ("#0D9488", "#0F766E"),
            "cyan": ("#06B6D4", "#0891B2"),
            "black": ("#18181B", "#09090B"),
            "dark": ("#18181B", "#09090B"),
            "काला": ("#18181B", "#09090B"),
            "slate": ("#1E293B", "#0F172A")
        }

        FONT_MAP = {
            "poppins": "Poppins",
            "inter": "Inter",
            "outfit": "Outfit",
            "playfair display": "Playfair Display",
            "playfair": "Playfair Display",
            "montserrat": "Montserrat",
            "roboto": "Roboto",
            "plus jakarta sans": "Plus Jakarta Sans",
            "plus jakarta": "Plus Jakarta Sans",
            "jakarta": "Plus Jakarta Sans",
            "cinzel": "Cinzel",
            "lato": "Lato",
            "serif": "Playfair Display",
            "sans": "Inter"
        }

        # Check if direct style modification can be deterministically applied
        theme_modified = False
        style_desc = []
        if "theme" not in current_state or not isinstance(current_state["theme"], dict):
            current_state["theme"] = {}
        target_theme = current_state["theme"]

        # 1. Font Theme Change
        if is_font_edit:
            matched_font = None
            for fk, fval in FONT_MAP.items():
                if fk in lower_instruction:
                    matched_font = fval
                    break
            if matched_font:
                target_theme["font"] = matched_font
                target_theme["font_family"] = matched_font
                theme_modified = True
                style_desc.append(f"font theme '{matched_font}'")

        # 2. Button Colors & Radius Change
        if is_button_edit:
            # Check button hex or named color
            btn_hex = re.search(r"#(?:[0-9a-fA-F]{3}){1,2}\b", instruction)
            if btn_hex:
                target_theme["button_color"] = btn_hex.group(0)
                theme_modified = True
                style_desc.append(f"button color {btn_hex.group(0)}")
            else:
                for ck, (prim, _) in COLOR_MAP.items():
                    if ck in lower_instruction:
                        target_theme["button_color"] = prim
                        theme_modified = True
                        style_desc.append(f"button color {ck}")
                        break

            # Check button text color
            if any(w in lower_instruction for w in ["white text", "text white", "safed text"]):
                target_theme["button_text_color"] = "#ffffff"
                theme_modified = True
            elif any(w in lower_instruction for w in ["dark text", "black text", "text dark", "text black"]):
                target_theme["button_text_color"] = "#111827"
                theme_modified = True

            # Check button corner radius
            if any(w in lower_instruction for w in ["pill", "capsule", "oval", "rounded-full"]):
                target_theme["button_radius"] = "9999px"
                theme_modified = True
                style_desc.append("pill-shaped buttons")
            elif any(w in lower_instruction for w in ["square", "sharp"]):
                target_theme["button_radius"] = "0px"
                theme_modified = True
                style_desc.append("square buttons")
            elif any(w in lower_instruction for w in ["rounded", "soft"]):
                target_theme["button_radius"] = "12px"
                theme_modified = True

        # 3. Overall Theme Color Change
        if (is_theme_color_edit or any(ck in lower_instruction for ck in COLOR_MAP.keys())) and not is_button_edit:
            col_hex = re.search(r"#(?:[0-9a-fA-F]{3}){1,2}\b", instruction)
            if col_hex:
                target_theme["primary"] = col_hex.group(0)
                target_theme["secondary"] = col_hex.group(0)
                theme_modified = True
                style_desc.append(f"theme color {col_hex.group(0)}")
            else:
                for ck, (prim, sec) in COLOR_MAP.items():
                    if ck in lower_instruction:
                        target_theme["primary"] = prim
                        target_theme["secondary"] = sec
                        if not target_theme.get("button_color"):
                            target_theme["button_color"] = prim
                        theme_modified = True
                        style_desc.append(f"theme color {ck}")
                        break

            # If user asks to change/update colors without specifying a color name, ask them!
            if not theme_modified and not is_font_edit:
                ask_msg = (
                    "Which color would you like for your website? You can choose one of the options below or specify any color:"
                    if lang == "en" else
                    "Aap apni website ke liye kaun sa color chahenge? Aap neeche diye gaye options me se chun sakte hain ya koi bhi color bata sakte hain:"
                    if lang == "hinglish" else
                    "आप अपनी वेबसाइट के लिए कौन सा रंग चुनना चाहेंगे? आप नीचे दिए गए विकल्पों में से चुन सकते हैं या कोई रंग बता सकते हैं:"
                )
                color_options = [
                    {"label": "🔵 Sapphire Blue", "action": "set_theme_color", "color": "#0284C7", "name": "Sapphire Blue"},
                    {"label": "🟣 Royal Purple", "action": "set_theme_color", "color": "#7C3AED", "name": "Royal Purple"},
                    {"label": "🟠 Sunset Orange", "action": "set_theme_color", "color": "#EA580C", "name": "Sunset Orange"},
                    {"label": "🔴 Crimson Red", "action": "set_theme_color", "color": "#DC2626", "name": "Crimson Red"},
                    {"label": "🟢 Emerald Green", "action": "set_theme_color", "color": "#059669", "name": "Emerald Green"},
                    {"label": "⚫ Minimal Dark", "action": "set_theme_color", "color": "#18181B", "name": "Minimal Dark"},
                    {"label": "🎨 Custom Color Picker", "action": "open_theme_modal", "tab": "colors"}
                ]
                return {
                    "action": "ask_color",
                    "message": ask_msg,
                    "options": color_options,
                    "updated_state": current_state
                }

        # If primary color changed, harmonize the dynamic logo
        if target_theme.get("primary") and theme_modified:
            new_theme_logo = WebsiteBuilderService.generate_dynamic_logo(b_name, category, target_theme["primary"])
            current_state["logo"] = new_theme_logo
            session.collected_data["Logo"] = new_theme_logo
            if current_state.get("pages"):
                for p in current_state["pages"]:
                    for s in p.get("sections", []):
                        if s.get("type") in ["navbar", "footer"]:
                            s["logo"] = new_theme_logo

        # If deterministically handled theme update without conflicting structural requests
        is_pure_style_request = (theme_modified or is_logo_request) and not any(
            w in lower_instruction for w in ["add page", "remove", "delete", "write", "change text", "rename", "new section"]
        )

        if is_pure_style_request:
            desc_str = ", ".join(style_desc) if style_desc else "theme styling"
            if lang == "hi":
                resp_text = f"मैंने आपकी वेबसाइट के {desc_str} को अपडेट कर दिया है! लाइव प्रिव्यू में नया स्टाइल तुरंत लागू हो गया है।"
            elif lang == "hinglish":
                resp_text = f"Maine aapki website ka {desc_str} update kar diya hai! Naya styling live preview me update ho chuka hai."
            else:
                resp_text = f"I have updated the {desc_str} for your website! The live preview has been updated with your new styling."

            if session.website_project_id:
                p_coll = await WebsiteBuilderService.get_project_collection()
                await p_coll.update_one(
                    {"_id": ObjectId(session.website_project_id), "user_id": user_id},
                    {
                        "$set": {
                            "theme": target_theme,
                            "website_data.theme": target_theme,
                            "logo": current_state.get("logo"),
                            "website_data.logo": current_state.get("logo"),
                            "updated_at": datetime.now(timezone.utc)
                        },
                        "$inc": {"version": 1}
                    }
                )

            return {
                "action": "update_theme",
                "message": resp_text,
                "updated_state": current_state
            }

        # -----------------------------------------------------
        # HOMEPAGE CONTENT EXPANSION PROCESSOR
        # -----------------------------------------------------
        is_content_expand_request = any(
            w in lower_instruction for w in [
                "more content", "add content", "homepage content", "content on homepage",
                "aur content", "zyada content", "content add", "expand content", "richer homepage",
                "content on home", "more section", "more sections"
            ]
        )

        if is_content_expand_request and current_state.get("pages"):
            home_p = next((p for p in current_state["pages"] if p.get("name", "").lower() == "home"), None)
            if home_p:
                h_secs = home_p.get("sections", [])
                sec_types = [s.get("type", "").lower() for s in h_secs if isinstance(s, dict)]

                if "stats" not in sec_types:
                    stats_sec = WebsiteBuilderService.get_default_stats_section(category)
                    hero_idx = next((i for i, s in enumerate(h_secs) if s.get("type") == "hero"), -1)
                    if hero_idx != -1:
                        h_secs.insert(hero_idx + 1, stats_sec)
                    else:
                        h_secs.insert(1, stats_sec)

                sec_types = [s.get("type", "").lower() for s in h_secs if isinstance(s, dict)]
                if "testimonials" not in sec_types:
                    test_sec = WebsiteBuilderService.get_default_testimonials_section(b_name, category)
                    footer_idx = next((i for i, s in enumerate(h_secs) if s.get("type") == "footer"), len(h_secs))
                    h_secs.insert(footer_idx, test_sec)

                sec_types = [s.get("type", "").lower() for s in h_secs if isinstance(s, dict)]
                if "faq" not in sec_types:
                    faq_sec = WebsiteBuilderService.get_default_faq_section(b_name, category)
                    footer_idx = next((i for i, s in enumerate(h_secs) if s.get("type") == "footer"), len(h_secs))
                    h_secs.insert(footer_idx, faq_sec)

                sec_types = [s.get("type", "").lower() for s in h_secs if isinstance(s, dict)]
                if "cta" not in sec_types:
                    cta_sec = WebsiteBuilderService.get_default_cta_section(b_name, category)
                    footer_idx = next((i for i, s in enumerate(h_secs) if s.get("type") == "footer"), len(h_secs))
                    h_secs.insert(footer_idx, cta_sec)

                if lang == "hi":
                    resp_text = f"मैंने {b_name} के होमपेज पर महत्वपूर्ण स्टैट्स, कस्टमर रिव्यू, सामान्य प्रश्न (FAQ) और कॉल-टू-एक्शन बैनर जोड़कर अधिक कंटेंट जोड़ दिया है!"
                elif lang == "hinglish":
                    resp_text = f"Maine {b_name} ke homepage par key stats counters, customer reviews, FAQs aur CTA banner add karke rich content update kar diya hai!"
                else:
                    resp_text = f"I have enriched the Homepage for {b_name} with key business metrics, customer reviews, frequently asked questions, and a high-converting call-to-action banner!"

                if session.website_project_id:
                    p_coll = await WebsiteBuilderService.get_project_collection()
                    await p_coll.update_one(
                        {"_id": ObjectId(session.website_project_id), "user_id": user_id},
                        {
                            "$set": {
                                "pages": current_state["pages"],
                                "website_data.pages": current_state["pages"],
                                "updated_at": datetime.now(timezone.utc)
                            },
                            "$inc": {"version": 1}
                        }
                    )

                return {
                    "action": "update_text",
                    "message": resp_text,
                    "updated_state": current_state
                }

        # -----------------------------------------------------
        # IMAGE CHANGE & REFRESH PROCESSOR
        # -----------------------------------------------------
        is_image_edit = any(
            w in lower_instruction for w in [
                "change image", "change images", "update image", "update images",
                "new image", "new images", "replace image", "replace images",
                "hero image", "header image", "cover image", "product image", "product images",
                "photo", "photos", "picture", "pictures", "image change", "photo badlo",
                "image badlo", "fresh photography", "photography", "photos change"
            ]
        )

        if is_image_edit and current_state.get("pages"):
            seed_offset = (int(datetime.now().timestamp()) % 7) + 1
            for p in current_state["pages"]:
                if isinstance(p, dict):
                    for s_idx, s in enumerate(p.get("sections", [])):
                        if not isinstance(s, dict):
                            continue
                        stype = s.get("type", "")
                        if stype == "hero":
                            s["image_url"] = WebsiteBuilderService.resolve_curated_image(
                                category, f"{b_name} {category} storefront showcase", s_idx + seed_offset, True
                            )
                        elif stype in ["products", "menu", "services", "catalog", "features"]:
                            for itm_idx, itm in enumerate(s.get("items", [])):
                                if isinstance(itm, dict):
                                    itm_title = itm.get("title") or itm.get("name") or category
                                    itm["image_url"] = WebsiteBuilderService.resolve_curated_image(
                                        category, f"{itm_title} {category}", itm_idx + seed_offset + 1, False
                                    )
                        elif stype in ["about", "story", "gallery"]:
                            s["image_url"] = WebsiteBuilderService.resolve_curated_image(
                                category, f"about {b_name} {category}", s_idx + seed_offset, False
                            )
                            for itm_idx, itm in enumerate(s.get("items", [])):
                                if isinstance(itm, dict):
                                    itm["image_url"] = WebsiteBuilderService.resolve_curated_image(
                                        category, f"gallery {category}", itm_idx + seed_offset + 2, False
                                    )

            if lang == "hi":
                resp_text = f"मैंने आपकी वेबसाइट की सभी इमेज को {category} के अनुसार नई और उच्च गुणवत्ता वाली फोटोग्राफी से अपडेट कर दिया है!"
            elif lang == "hinglish":
                resp_text = f"Maine aapki website ki images ko {category} ke hisab se fresh high-resolution photos ke sath update kar diya hai!"
            else:
                resp_text = f"I've updated your website images with fresh, high-resolution photography tailored to {b_name} ({category})!"

            if session.website_project_id:
                p_coll = await WebsiteBuilderService.get_project_collection()
                await p_coll.update_one(
                    {"_id": ObjectId(session.website_project_id), "user_id": user_id},
                    {
                        "$set": {
                            "pages": current_state["pages"],
                            "website_data.pages": current_state["pages"],
                            "updated_at": datetime.now(timezone.utc)
                        },
                        "$inc": {"version": 1}
                    }
                )

            return {
                "action": "update_image",
                "message": resp_text,
                "updated_state": current_state
            }

        # Detect explicit category conflicts.
        category_conflicts = {
            "flower": ["gym", "workout", "fitness equipment"],
            "gym": ["bouquet", "flowers", "floral arrangement"],
            "indian sweet shop": ["gym equipment", "fitness training"]
        }

        for business, conflicting_terms in category_conflicts.items():
            if business in lower_category:
                if any(term in lower_instruction for term in conflicting_terms):
                    return {
                        "action": "clarification_required",
                        "message": (
                            f"Your website is for a {category}. "
                            "This request may conflict with your business category. "
                            "Would you like to change the business theme?"
                        ),
                        "updated_state": current_state
                    }

        ai = AIProviderFactory.get_provider(preferred="openai")

        lang_name = "Hinglish (conversational Hindi in Latin script)" if lang == "hinglish" else "Hindi" if lang == "hi" else "English"

        prompt = f"""
Edit the existing website based on user instruction.

Business category: {category}
Business name: {b_name}
User language: {lang_name}

User instruction:
{instruction}

Current website:
{json.dumps(current_state, default=str)}

Return JSON:
{{
  "action": "update_text",
  "message": "Friendly, conversational response in {lang_name}",
  "updated_state": {{}}
}}

Rules:
- Preserve existing structure and content unless explicitly requested to change.
- In the 'message' field: Speak warmly and naturally to the user in {lang_name}. Keep it to 1-2 friendly, reassuring sentences. NEVER write dry technical changelogs or mention internal codes.
- If requested to modify navbar or tabs:
  - Navbar MUST include the business name "{b_name}" and logo.
  - Navbar tabs MUST include navigation links corresponding to pages (e.g. Home, About, Services/Products, Contact).
- If requested to modify or add hero section or images:
  - Include captivating headline, subtitle, CTAs, and category-matched image prompts.
- If requested to add or modify homepage or content:
  - Ensure the "Home" page is rich, engaging, and comprehensive with:
    1. Hero Section (headline, subtitle, CTAs, badge, category image)
    2. Key Metrics / Stats Bar (4 numerical highlights like "100% Satisfaction", "5,000+ Happy Clients", "Fast Turnaround", "4.9/5 Rating")
    3. Signature Highlights / Features (3-4 cards with descriptions & images)
    4. Brand Story / Why Choose Us Preview (rich narrative & core values)
    5. Customer Testimonials (3 realistic reviews with 5-star ratings and client quotes)
    6. Frequently Asked Questions (FAQ with 4 common questions & answers)
    7. Call to Action Banner (high-converting inquiry banner)
- If requested to add or modify pages:
  - Ensure the "pages" array has complete pages (Home, About, Services/Products, Contact) with proper sections.
- Keep all images authentic and relevant to {category}.
"""

        try:
            result = await ai.generate_json(
                prompt,
                system_prompt=(
                    f"You are a helpful, friendly AI website designer. "
                    f"Always respond to the user in {lang_name}. "
                    "Make concise, reassuring responses and never output robotic change logs."
                ),
                temperature=0.2,
                max_tokens=8192
            )

            if not isinstance(result, dict):
                raise ValueError("Invalid AI response")

            updated = result.get("updated_state")

            if not isinstance(updated, dict):
                raise ValueError("Missing updated_state")

            # Post-process pages to ensure image resolution and navbar consistency
            active_logo = new_logo or logo
            if active_logo:
                updated["logo"] = active_logo

            if "pages" in updated and isinstance(updated["pages"], list):
                nav_tabs = updated.get("navigation") or ["Home", "About", "Services", "Contact"]
                for p_idx, page in enumerate(updated["pages"]):
                    if not isinstance(page, dict):
                        continue
                    for s_idx, section in enumerate(page.get("sections", [])):
                        if not isinstance(section, dict):
                            continue
                        stype = section.get("type", "")
                        if stype in ["navbar", "footer"]:
                            section["title"] = b_name
                            if active_logo:
                                section["logo"] = active_logo
                            if stype == "navbar":
                                section["navigation"] = nav_tabs
                        elif stype == "hero":
                            if not section.get("image_url") or "placeholder" in section.get("image_url", ""):
                                section["image_url"] = WebsiteBuilderService.resolve_curated_image(
                                    category, section.get("image_prompt", category), s_idx, True
                                )
                        elif stype in ["about", "story"]:
                            if not section.get("image_url") or "placeholder" in section.get("image_url", ""):
                                section["image_url"] = WebsiteBuilderService.resolve_curated_image(
                                    category, section.get("image_prompt", f"about {category}"), s_idx, False
                                )
                        for itm_idx, itm in enumerate(section.get("items", [])):
                            if isinstance(itm, dict) and (not itm.get("image_url") or "placeholder" in itm.get("image_url", "")):
                                itm_prompt = itm.get("image_prompt") or itm.get("title") or category
                                itm["image_url"] = WebsiteBuilderService.resolve_curated_image(
                                    category, itm_prompt, itm_idx, False
                                )

            # If user explicitly asked for hero image change, ensure the hero image is updated to match category
            is_hero_image_req = any(w in lower_instruction for w in ["hero image", "header image", "cover image"])
            if is_hero_image_req and "pages" in updated and isinstance(updated["pages"], list):
                for page in updated["pages"]:
                    if isinstance(page, dict):
                        for s in page.get("sections", []):
                            if isinstance(s, dict) and s.get("type") == "hero":
                                s["image_url"] = WebsiteBuilderService.resolve_curated_image(
                                    category, f"{b_name} {category} storefront", 2, True
                                )

            # If user explicitly asked for logo, provide a warm natural response
            if is_logo_request:
                if lang == "hi":
                    result["message"] = f"मैंने आपकी दुकान '{b_name}' के लिए नया लोगो बनाकर वेबसाइट के नेवबार और फुटर में जोड़ दिया है। अब यह आपको वेबसाइट में स्पष्ट दिखेगा!"
                elif lang == "hinglish":
                    result["message"] = f"Maine aapki dukaan '{b_name}' ke hisab se naya logo generate karke navbar aur footer me laga diya hai. Ab yeh aapko website me saaf dikhega!"
                else:
                    result["message"] = f"I have generated and updated a customized logo for '{b_name}' across your website header and footer. It is now clearly visible on your website!"

            # Persist the changed state to the actual website project.
            if session.website_project_id:
                collection = await WebsiteBuilderService.get_project_collection()

                await collection.update_one(
                    {
                        "_id": ObjectId(session.website_project_id),
                        "user_id": user_id
                    },
                    {
                        "$set": {
                            "logo": active_logo,
                            "website_data": updated,
                            "pages": updated.get("pages", []),
                            "theme": updated.get("theme", {}),
                            "updated_at": datetime.now(timezone.utc)
                        },
                        "$inc": {"version": 1}
                    }
                )

            return result

        except Exception as exc:
            logger.exception("Website edit failed")

            return {
                "action": "error",
                "message": (
                    "I couldn't apply that change. "
                    "Your existing website has not been changed."
                ),
                "updated_state": current_state
            }