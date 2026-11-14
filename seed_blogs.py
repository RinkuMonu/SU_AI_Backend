import pymongo
from datetime import datetime, timezone, timedelta

client = pymongo.MongoClient('mongodb+srv://rinkuyadav9460_db_user:PJrNGHmujot6YovI@cluster0.wrmtwnk.mongodb.net/?readPreference=secondaryPreferred')
db = client['sevenunique_ai_db']

now = datetime.now(timezone.utc)

initial_blogs = [
    {
        'title': 'How Indian Retailers & Shop Owners are Scaling 10x with WhatsApp AI Marketing',
        'slug': 'indian-retailers-whatsapp-ai-marketing',
        'category': 'AI Marketing',
        'excerpt': 'Learn how local shops, boutiques, and saree retailers in Surat, Jaipur, and Delhi are turning festive customer leads into repeat buyers with automated WhatsApp marketing sequences.',
        'content': '''# How Indian Retailers & Shop Owners are Scaling 10x with WhatsApp AI Marketing

In India, WhatsApp is no longer just a messaging app; it is the premier virtual storefront for over 60 million micro, small, and medium enterprises (MSMEs).

## Why Traditional SMS Marketing is Dying
Traditional bulk SMS campaigns often deliver open rates below 8%. In stark contrast, personalized WhatsApp messages consistently enjoy open rates exceeding **95%** within 15 minutes of delivery.

### Key Benefits of DhandaGrow WhatsApp Automation
1. **Instant Order Confirmation & Status Alerts**: Automatically notify customers when their package is packed, dispatched, or out for delivery.
2. **AI-Driven Festive Promotions**: Automatically generate contextual greetings and offers for Diwali, Eid, Raksha Bandhan, and wedding seasons.
3. **Automated Abandoned Cart Recovery**: Recover up to 35% of unfinished checkout inquiries with intelligent follow-up prompts.

## Real Case Study: Surat Textile Merchant
A textile shop in Surat used DhandaGrow’s AI Marketing to segment their customer list by previous purchase value. Within 30 days of deploying targeted catalog carousels, they observed a **4.2x increase in repeat orders** and zero spam flags.

Start leveraging DhandaGrow AI Marketing today to transform your customer communication into consistent sales.''',
        'cover_image': 'https://images.unsplash.com/photo-1616469829941-c7200edec809?w=1200&auto=format&fit=crop&q=80',
        'author': 'Rahul Singh',
        'author_role': 'Founder & Growth Strategist',
        'read_time': '4 min read',
        'tags': ['WhatsAppMarketing', 'RetailGrowth', 'IndianSellers', 'Automation'],
        'published': True,
        'featured': True,
        'views': 412,
        'likes': 68,
        'created_at': now - timedelta(days=5),
        'updated_at': now - timedelta(days=1)
    },
    {
        'title': 'The Ultimate Guide to Festive Season Fashion & Saree Campaigns',
        'slug': 'ultimate-guide-festive-fashion-saree-campaigns',
        'category': 'Fashion & Retail',
        'excerpt': 'Step-by-step blueprint to running hyper-targeted Instagram & Meta Ads for ethnic wear, lehengas, and designer sarees during the peak Indian wedding and festive season.',
        'content': '''# The Ultimate Guide to Festive Season Fashion & Saree Campaigns

The Indian festive calendar from Navratri to the winter wedding season accounts for nearly **45% of annual revenue** for ethnic fashion retailers.

## Crucial Steps for Maximum ROI
### 1. High-Resolution Virtual Photoshoots
You don't need expensive studio models anymore. With DhandaGrow Fashion AI Studio:
- Upload flat-lay photos of your sarees or kurtis.
- Generate realistic Indian model previews with studio lighting in under 30 seconds.
- Save up to 85% on traditional photography costs.

### 2. Micro-Influencer Collaborations
Partner with regional micro-influencers (10k - 50k followers) who have high trust among local shoppers in tier-2 and tier-3 cities.

### 3. Hyperlocal Geo-Targeting
Set up Meta Ad radiuses within 5-10 km of your physical showroom, inviting customers to touch, feel, and try on exclusive wedding collections in-store.

Plan your ad creatives at least 3 weeks prior to major festivals to capture early-bird shoppers!''',
        'cover_image': 'https://images.unsplash.com/photo-1610030469983-98e550d6193c?w=1200&auto=format&fit=crop&q=80',
        'author': 'Priyanshi Bansal',
        'author_role': 'Creative Lead',
        'read_time': '6 min read',
        'tags': ['EthnicFashion', 'MetaAds', 'VirtualTryOn', 'FestiveSales'],
        'published': True,
        'featured': True,
        'views': 629,
        'likes': 94,
        'created_at': now - timedelta(days=3),
        'updated_at': now
    },
    {
        'title': '5 Critical Local SEO Tactics to Dominate Google Maps for Your Store',
        'slug': 'local-seo-google-maps-store-domination',
        'category': 'Local SEO',
        'excerpt': 'Is your retail showroom or clinic showing up in the Google Local 3-Pack? Discover the exact optimization steps to rank #1 in your neighborhood.',
        'content': '''# 5 Critical Local SEO Tactics to Dominate Google Maps for Your Store

Over 76% of people who search for something nearby on their smartphone visit a related business within a day, and 28% of those searches result in a purchase.

## 5 Practical Steps to Win Nearby Searches
1. **Complete Google Business Profile (GBP) 100%**: Ensure exact NAP (Name, Address, Phone number) consistency across your website and social profiles.
2. **Collect Authentic Customer Reviews Weekly**: Send automated WhatsApp review links right after a purchase.
3. **Publish High-Resolution In-Store Photos**: Upload fresh images of your shop entrance, product aisles, and staff weekly.
4. **Utilize Google Posts for Daily Offers**: Announce discounts, seasonal sales, and holiday hours.
5. **Add Local Schema Markup**: Help Google understand your service radius with structured JSON-LD business data.

DhandaGrow's Google Maps Onboarding feature automates profile verification and review sync directly from your dashboard.''',
        'cover_image': 'https://images.unsplash.com/photo-1526778548025-fa2f459cd5c1?w=1200&auto=format&fit=crop&q=80',
        'author': 'Deepak Yadav',
        'author_role': 'SEO Specialist',
        'read_time': '5 min read',
        'tags': ['LocalSEO', 'GoogleMaps', 'Footfall', 'RetailMarketing'],
        'published': True,
        'featured': False,
        'views': 298,
        'likes': 41,
        'created_at': now - timedelta(days=2),
        'updated_at': now
    },
    {
        'title': 'AI Virtual Try-On: How Fashion Merchants are Reducing Returns by 40%',
        'slug': 'ai-virtual-try-on-reducing-ecommerce-returns',
        'category': 'E-Commerce',
        'excerpt': 'High return rates eat into fashion e-commerce profit margins. See how interactive virtual try-on tech is building buyer confidence and slashing returns.',
        'content': '''# AI Virtual Try-On: How Fashion Merchants are Reducing Returns by 40%

One of the largest hurdles in online apparel sales is size and drape uncertainty. In India, return-to-origin (RTO) rates can reach upwards of 30-40% for Cash-on-Delivery orders.

## How Virtual Try-On Works
By using deep learning image synthesis, customers can visualize how a dress, sherwani, or saree looks on diverse body shapes and skin tones.

### Immediate Benefits:
- **Higher Conversion Rates**: Shoppers are 2.4x more likely to complete a purchase when they can see realistic garment fit.
- **Lower Return Costs**: Dramatic drop in size-related disputes and courier return penalties.
- **Enhanced Customer Delight**: Modern shopping experience that rivals top global luxury portals.

Explore DhandaGrow AI Virtual Try-on inside your product catalog today.''',
        'cover_image': 'https://images.unsplash.com/photo-1441986300917-64674bd600d8?w=1200&auto=format&fit=crop&q=80',
        'author': 'Kratika Sharma',
        'author_role': 'Product Specialist',
        'read_time': '5 min read',
        'tags': ['VirtualTryOn', 'Ecommerce', 'FashionAI', 'RTOReduction'],
        'published': True,
        'featured': False,
        'views': 385,
        'likes': 52,
        'created_at': now - timedelta(days=1),
        'updated_at': now
    },
    {
        'title': 'Social Media Content Calendars Made Effortless with DhandaGrow AI',
        'slug': 'social-media-content-calendars-effortless-ai',
        'category': 'Business Growth',
        'excerpt': 'Stop stressing over daily Instagram post ideas. Discover how automated AI content engines curate a month worth of engaging Reels and carousels in minutes.',
        'content': '''# Social Media Content Calendars Made Effortless with DhandaGrow AI

Consistently posting valuable content is the single most effective way to build brand authority and trust on Instagram and Facebook.

## Consistency Over Perfection
Many small business owners post sporadically for a week and then disappear for a month. Algorithms reward daily, predictable activity.

### The 30-Day DhandaGrow AI Framework
1. **Week 1 - Educational**: Teach your customers how to identify genuine fabrics or select the right products.
2. **Week 2 - Behind the Scenes**: Showcase artisan craftsmanship, shop preparation, and customer unboxing.
3. **Week 3 - Customer Reviews & Proof**: User-generated content and video testimonials.
4. **Week 4 - Direct Offer & CTA**: Limited-time bundle offers and WhatsApp order links.

Automate your next 30 days of social media posts with DhandaGrow AI Studio.''',
        'cover_image': 'https://images.unsplash.com/photo-1611162617213-7d7a39e9b1d7?w=1200&auto=format&fit=crop&q=80',
        'author': 'DhandaGrow Editorial',
        'author_role': 'Content Strategy Lead',
        'read_time': '4 min read',
        'tags': ['SocialMedia', 'ContentStrategy', 'InstagramGrowth', 'Reels'],
        'published': False,
        'featured': False,
        'views': 86,
        'likes': 14,
        'created_at': now,
        'updated_at': now
    }
]

for blog in initial_blogs:
    db['blogs'].update_one(
        {'slug': blog['slug']},
        {'$set': blog},
        upsert=True
    )

print('Seeded successfully! Total blogs:', db['blogs'].count_documents({}))

