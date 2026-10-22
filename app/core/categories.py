"""
Comprehensive Category & Subcategory Taxonomy for AI Product Reel Generation.
Supports e-commerce, retail, and custom commercial products.
"""
from typing import List, Dict, Any, Optional

CATEGORIES_TAXONOMY: List[Dict[str, Any]] = [
    {
        "id": "fashion_clothing",
        "name": "Fashion & Clothing",
        "icon": "sparkles",
        "description": "Men's, women's, ethnic, streetwear, and designer apparel",
        "subcategories": [
            {"id": "mens_fashion", "name": "Men's Fashion", "items": ["T-Shirts", "Shirts", "Trousers", "Jackets", "Jeans", "Suits & Blazers"]},
            {"id": "womens_fashion", "name": "Women's Fashion", "items": ["Sarees", "Kurtis", "Dresses", "Tops", "Co-ord Sets", "Lehengas"]},
            {"id": "footwear", "name": "Footwear", "items": ["Sneakers", "Formal Shoes", "Sandals", "Boots", "Loafers", "Athletic Shoes"]},
            {"id": "accessories", "name": "Accessories", "items": ["Watches", "Bags", "Backpacks", "Belts", "Wallets", "Eyewear", "Jewellery"]},
            {"id": "kids_fashion", "name": "Kids Fashion", "items": ["Boys Wear", "Girls Wear", "Infant & Baby Wear", "Kids Footwear"]},
            {"id": "ethnic_wear", "name": "Ethnic & Festive", "items": ["Bridal Lehengas", "Sherwanis", "Silk Sarees", "Kurtas", "Dupattas"]}
        ]
    },
    {
        "id": "furniture_home",
        "name": "Furniture & Home",
        "icon": "home",
        "description": "Living room, bedroom, office furniture, lighting, and interior decor",
        "subcategories": [
            {"id": "living_room", "name": "Living Room", "items": ["Sofas & Couches", "Recliners", "Coffee Tables", "TV Units", "Bookshelves"]},
            {"id": "bedroom", "name": "Bedroom", "items": ["Beds & Mattresses", "Wardrobes", "Dressing Tables", "Nightstands"]},
            {"id": "office_furniture", "name": "Office Furniture", "items": ["Ergonomic Chairs", "Office Desks", "Filing Cabinets", "Workstations"]},
            {"id": "home_decor", "name": "Home Decor", "items": ["Lamps & Lighting", "Wall Mirrors", "Paintings & Wall Art", "Rugs & Carpets", "Vases"]},
            {"id": "kitchen_dining", "name": "Kitchen & Dining", "items": ["Dining Tables", "Dining Chairs", "Cookware", "Kitchen Organizers", "Barware"]}
        ]
    },
    {
        "id": "electronics",
        "name": "Electronics & Gadgets",
        "icon": "smartphone",
        "description": "Smartphones, laptops, audio gear, smart wearables, and home appliances",
        "subcategories": [
            {"id": "mobile_phones", "name": "Mobile Phones", "items": ["Smartphones", "Flagship Phones", "Phone Cases", "Wireless Chargers"]},
            {"id": "laptops_computers", "name": "Laptops & Computers", "items": ["Gaming Laptops", "Ultrabooks", "MacBooks", "PC Accessories", "Monitors"]},
            {"id": "headphones_audio", "name": "Audio & Sound", "items": ["Wireless Earbuds", "Over-Ear Headphones", "Bluetooth Speakers", "Soundbars"]},
            {"id": "smart_watches", "name": "Smart Wearables", "items": ["Smart Watches", "Fitness Trackers", "Smart Rings"]},
            {"id": "home_appliances", "name": "Home Appliances", "items": ["Air Conditioners", "Refrigerators", "Smart TVs", "Coffee Machines", "Vacuum Cleaners"]},
            {"id": "cameras_drones", "name": "Cameras & Drones", "items": ["Action Cameras", "DSLRs & Mirrorless", "Gimbals", "Camera Drones"]}
        ]
    },
    {
        "id": "beauty_personal_care",
        "name": "Beauty & Personal Care",
        "icon": "heart",
        "description": "Skincare serums, organic cosmetics, haircare, and luxury fragrances",
        "subcategories": [
            {"id": "skincare", "name": "Skincare", "items": ["Face Serums", "Moisturizers", "Sunscreen SPF", "Face Wash", "Face Masks", "Eye Creams"]},
            {"id": "makeup", "name": "Makeup & Cosmetics", "items": ["Lipsticks", "Foundations", "Eyeliners & Mascaras", "Blushes & Highlighters", "Eyeshadow Palettes"]},
            {"id": "haircare", "name": "Haircare", "items": ["Hair Oils", "Shampoos & Conditioners", "Hair Serums", "Styling Tools"]},
            {"id": "fragrances", "name": "Fragrances & Perfumes", "items": ["Eau de Parfum", "Attars & Ouds", "Body Mists", "Deodorants"]},
            {"id": "mens_grooming", "name": "Men's Grooming", "items": ["Beard Oils", "Shaving Kits", "Face Wash", "Hair Pomade"]}
        ]
    },
    {
        "id": "food_beverages",
        "name": "Food & Beverages",
        "icon": "utensils",
        "description": "Artisan bakery, snacks, gourmet specialties, beverages, and cafe menus",
        "subcategories": [
            {"id": "bakery", "name": "Bakery & Desserts", "items": ["Custom Cakes", "Pastries & Croissants", "Artisan Breads", "Cookies & Brownies"]},
            {"id": "snacks", "name": "Snacks & Munchies", "items": ["Roasted Nuts", "Artisan Chips", "Indian Namkeen", "Healthy Bars"]},
            {"id": "beverages", "name": "Beverages & Drinks", "items": ["Specialty Coffee", "Organic Tea & Matcha", "Cold Pressed Juices", "Kombucha", "Mocktails"]},
            {"id": "restaurant_dishes", "name": "Restaurant Specials", "items": ["Signature Biryani", "Gourmet Burgers", "Artisan Pizza", "Authentic Curries", "Pasta Dishes"]},
            {"id": "packaged_food", "name": "Packaged Gourmet", "items": ["Spices & Condiments", "Chocolates", "Honey & Spreads", "Organic Staples"]}
        ]
    },
    {
        "id": "jewellery_luxury",
        "name": "Jewellery & Luxury",
        "icon": "gem",
        "description": "Gold, diamond, polki, and high-fashion luxury jewellery and watches",
        "subcategories": [
            {"id": "fine_jewellery", "name": "Fine Jewellery", "items": ["Diamond Rings", "Gold Necklaces", "Polki Sets", "Bangles & Kadas", "Solitaires"]},
            {"id": "fashion_jewellery", "name": "Fashion Jewellery", "items": ["Chokers", "Statement Earrings", "Layered Chains", "Oxidised Silver"]},
            {"id": "luxury_watches", "name": "Luxury Timepieces", "items": ["Chronographs", "Automatic Watches", "Dress Watches", "Vintage Watches"]}
        ]
    },
    {
        "id": "fitness_health",
        "name": "Fitness & Health",
        "icon": "activity",
        "description": "Sports gear, gym equipment, activewear, and nutrition supplements",
        "subcategories": [
            {"id": "gym_gear", "name": "Gym & Training", "items": ["Dumbbells & Weights", "Resistance Bands", "Yoga Mats", "Gym Bags"]},
            {"id": "activewear", "name": "Activewear", "items": ["Gym Leggings", "Performance T-Shirts", "Sports Bras", "Trackpants"]},
            {"id": "nutrition", "name": "Nutrition & Wellness", "items": ["Whey Protein", "Pre-Workout", "Vitamins & Supplements", "Electrolytes"]}
        ]
    },
    {
        "id": "other",
        "name": "Other & Custom Products",
        "icon": "tag",
        "description": "Custom businesses, services, automotive, pet care, and specialized items",
        "subcategories": [
            {"id": "automotive", "name": "Automotive Accessories", "items": ["Car Care & Polish", "Seat Covers", "Riding Jackets", "Helmets"]},
            {"id": "pet_supplies", "name": "Pet Supplies", "items": ["Pet Food", "Pet Toys", "Grooming Kits", "Pet Beds"]},
            {"id": "stationery_gifts", "name": "Stationery & Gifts", "items": ["Handmade Journals", "Custom Hampers", "Art Supplies", "Corporate Gifts"]},
            {"id": "custom", "name": "Custom Product", "items": ["Specialty Custom Product", "Service Showcase", "Brand Campaign"]}
        ]
    }
]

# Preset product suggestions for instant preview & demonstration
PRESET_PRODUCTS = [
    {
        "id": "preset_macbook",
        "name": "MacBook Pro M3 Max",
        "category_id": "electronics",
        "category": "Electronics & Gadgets",
        "subcategory_id": "laptops_computers",
        "subcategory": "Laptops & Computers",
        "description": "Liquid Retina XDR display, M3 Max chip with 16-core CPU, up to 22 hours battery life for creative pros.",
        "price": 2499.00,
        "image_url": "https://images.unsplash.com/photo-1517336714731-489689fd1ca8?w=1080&q=85",
        "images": ["https://images.unsplash.com/photo-1517336714731-489689fd1ca8?w=1080&q=85"]
    },
    {
        "id": "preset_sofa",
        "name": "Velvet Cloud 3-Seater Sofa",
        "category_id": "furniture_home",
        "category": "Furniture & Home",
        "subcategory_id": "living_room",
        "subcategory": "Living Room",
        "description": "Handcrafted plush velvet upholstery, high-density memory foam cushioning, solid teakwood tapered legs.",
        "price": 899.00,
        "image_url": "https://images.unsplash.com/photo-1555041469-a586c61ea9bc?w=1080&q=85",
        "images": ["https://images.unsplash.com/photo-1555041469-a586c61ea9bc?w=1080&q=85"]
    },
    {
        "id": "preset_lehenga",
        "name": "Royal Crimson Bridal Lehenga",
        "category_id": "fashion_clothing",
        "category": "Fashion & Clothing",
        "subcategory_id": "ethnic_wear",
        "subcategory": "Ethnic & Festive",
        "description": "Pure raw silk lehenga with hand-embroidered zardozi and antique gold tilla work, paired with matching organza dupatta.",
        "price": 1499.00,
        "image_url": "https://images.unsplash.com/photo-1583391733956-3750e0ff4e8b?w=1080&q=85",
        "images": ["https://images.unsplash.com/photo-1583391733956-3750e0ff4e8b?w=1080&q=85"]
    },
    {
        "id": "preset_sneakers",
        "name": "Urban Glide Nitro Sneakers",
        "category_id": "fashion_clothing",
        "category": "Fashion & Clothing",
        "subcategory_id": "footwear",
        "subcategory": "Footwear",
        "description": "Breathable knit upper with responsive nitrogen-infused foam sole for all-day comfort and street style.",
        "price": 129.00,
        "image_url": "https://images.unsplash.com/photo-1552346154-21d32810aba3?w=1080&q=85",
        "images": ["https://images.unsplash.com/photo-1552346154-21d32810aba3?w=1080&q=85"]
    },
    {
        "id": "preset_serum",
        "name": "Glow Dew Vitamin C & Niacinamide Serum",
        "category_id": "beauty_personal_care",
        "category": "Beauty & Personal Care",
        "subcategory_id": "skincare",
        "subcategory": "Skincare",
        "description": "Targeted brightening serum with 15% Ethyl Ascorbic Acid, 5% Niacinamide, and Hyaluronic Acid for radiant skin.",
        "price": 38.00,
        "image_url": "https://images.unsplash.com/photo-1620916566398-39f1143ab7be?w=1080&q=85",
        "images": ["https://images.unsplash.com/photo-1620916566398-39f1143ab7be?w=1080&q=85"]
    },
    {
        "id": "preset_coffee",
        "name": "Artisan Single-Origin Cold Brew Coffee",
        "category_id": "food_beverages",
        "category": "Food & Beverages",
        "subcategory_id": "beverages",
        "subcategory": "Beverages & Drinks",
        "description": "18-hour slow steeped Arabica beans with tasting notes of dark cocoa, roasted hazelnut, and brown sugar caramel.",
        "price": 6.50,
        "image_url": "https://images.unsplash.com/photo-1517256064527-09c73fc73e38?w=1080&q=85",
        "images": ["https://images.unsplash.com/photo-1517256064527-09c73fc73e38?w=1080&q=85"]
    }
]


def get_all_categories() -> List[Dict[str, Any]]:
    """Returns all categories with subcategory summaries."""
    return [
        {
            "id": cat["id"],
            "name": cat["name"],
            "icon": cat.get("icon", "tag"),
            "description": cat.get("description", ""),
            "subcategories_count": len(cat.get("subcategories", [])),
            "subcategories": [
                {
                    "id": sub["id"],
                    "name": sub["name"],
                    "items": sub.get("items", [])
                }
                for sub in cat.get("subcategories", [])
            ]
        }
        for cat in CATEGORIES_TAXONOMY
    ]


def get_subcategories(category_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Returns subcategories, optionally filtered by category_id."""
    if not category_id:
        # Return all subcategories flattened
        result = []
        for cat in CATEGORIES_TAXONOMY:
            for sub in cat.get("subcategories", []):
                result.append({
                    "category_id": cat["id"],
                    "category_name": cat["name"],
                    "subcategory_id": sub["id"],
                    "subcategory_name": sub["name"],
                    "sample_items": sub.get("items", [])
                })
        return result

    for cat in CATEGORIES_TAXONOMY:
        if cat["id"].lower() == category_id.lower() or cat["name"].lower() == category_id.lower():
            return [
                {
                    "category_id": cat["id"],
                    "category_name": cat["name"],
                    "subcategory_id": sub["id"],
                    "subcategory_name": sub["name"],
                    "sample_items": sub.get("items", [])
                }
                for sub in cat.get("subcategories", [])
            ]
    return []


def search_categories(query: str) -> List[Dict[str, Any]]:
    """Searches categories, subcategories, and sample items by keyword."""
    if not query:
        return get_all_categories()

    q = query.strip().lower()
    matches = []
    for cat in CATEGORIES_TAXONOMY:
        cat_matches = False
        matching_subcategories = []

        if q in cat["name"].lower() or q in cat["id"].lower() or q in cat.get("description", "").lower():
            cat_matches = True
            matching_subcategories = cat.get("subcategories", [])
        else:
            for sub in cat.get("subcategories", []):
                sub_match = q in sub["name"].lower() or q in sub["id"].lower()
                items_match = any(q in item.lower() for item in sub.get("items", []))
                if sub_match or items_match:
                    matching_subcategories.append(sub)

        if cat_matches or matching_subcategories:
            matches.append({
                "id": cat["id"],
                "name": cat["name"],
                "icon": cat.get("icon", "tag"),
                "description": cat.get("description", ""),
                "subcategories": matching_subcategories
            })
    return matches


def get_preset_products(category_id: Optional[str] = None, query: Optional[str] = None) -> List[Dict[str, Any]]:
    """Returns preset commercial products matching category or search query."""
    res = PRESET_PRODUCTS
    if category_id:
        res = [p for p in res if p.get("category_id") == category_id or p.get("category", "").lower() == category_id.lower()]
    if query:
        q = query.strip().lower()
        res = [
            p for p in res
            if q in p.get("name", "").lower() or q in p.get("description", "").lower() or q in p.get("category", "").lower()
        ]
    return res
