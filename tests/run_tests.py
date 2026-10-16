import sys
import os
import asyncio
sys.path.insert(0, os.path.abspath("."))
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from dotenv import load_dotenv
load_dotenv(".env")

from tests.test_reel_system import (
    setup_db,
    test_1_laptop_relevance,
    test_2_lehenga_relevance,
    test_3_skincare_relevance,
    test_4_explicit_festival_theme,
    test_5_creative_mode,
    test_6_product_switching,
    test_7_concurrent_jobs,
    test_veo_provider_quota_handling,
    test_end_to_end_reel_service_job
)

async def main():
    print("=" * 70)
    print("SEVENUNIQUE AI - PRODUCT RELEVANCE & REEL SYSTEM TEST SUITE")
    print("=" * 70)
    db = setup_db()

    passed = 0
    failed = 0

    tests = [
        ("Test 1: Laptop Reel Prompt Planning & Domain Isolation", test_1_laptop_relevance, False),
        ("Test 2: Lehenga Reel Prompt Planning & Domain Isolation", test_2_lehenga_relevance, False),
        ("Test 3: Skincare Reel Prompt Planning & Domain Isolation", test_3_skincare_relevance, False),
        ("Test 4: Explicit Festival Theme (Laptop + Diwali Isolation)", test_4_explicit_festival_theme, False),
        ("Test 5: Creative Mode Abstract Storyboard", test_5_creative_mode, False),
        ("Test 6: Product Switching Context Isolation", test_6_product_switching, False),
        ("Test 7: Concurrent Jobs Scene Isolation", test_7_concurrent_jobs, False),
        ("Test 8: Google Veo Provider Quota Resilience", test_veo_provider_quota_handling, False),
        ("Test 9: End-to-End Reel Service Assembly Job", test_end_to_end_reel_service_job, True),
    ]

    for name, test_func, needs_db in tests:
        print(f"\n[RUNNING] {name}...")
        try:
            if needs_db:
                await test_func(db)
            else:
                await test_func()
            passed += 1
            print(f"[SUCCESS] {name}")
        except Exception as e:
            print(f"[FAIL] {name}: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print("\n" + "=" * 70)
    print(f"TEST SUMMARY: {passed} PASSED, {failed} FAILED (TOTAL: {len(tests)})")
    print("=" * 70)
    if failed > 0:
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
