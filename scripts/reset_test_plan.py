#!/usr/bin/env python3
"""
CLI Tool: Reset INR 1 TEST_PLAN Subscription and Entitlements
Usage:
    python scripts/reset_test_plan.py
    python scripts/reset_test_plan.py --user 6ae07df09bac56baccb9f2c5
    python scripts/reset_test_plan.py --phone 917857889083
"""
import sys
import os
import argparse
import asyncio
from bson import ObjectId

# Ensure workspace root is in python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import connect_to_mongo, get_database
from app.services.payin_service import PayinService


async def find_target_user(db, user_arg=None, phone_arg=None, email_arg=None):
    if user_arg:
        if ObjectId.is_valid(user_arg):
            u = await db["users"].find_one({"_id": ObjectId(user_arg)})
            if u:
                return str(u["_id"]), u
        u = await db["users"].find_one({"id": user_arg})
        if u:
            return str(u["_id"]), u
        sub = await db["subscriptions"].find_one({"user_id": user_arg})
        if sub:
            return user_arg, {"_id": user_arg, "name": "User by Subscription ID"}

    if phone_arg:
        clean_phone = phone_arg.replace("+", "").strip()
        u = await db["users"].find_one({"phone_number": {"$regex": clean_phone}})
        if u:
            return str(u["_id"]), u

    if email_arg:
        u = await db["users"].find_one({"email": email_arg.strip().lower()})
        if u:
            return str(u["_id"]), u

    # Default lookup: Find users currently on TEST_PLAN
    sub = await db["subscriptions"].find_one({"plan_id": {"$in": ["TEST_PLAN", "TEST"]}})
    if sub:
        uid = sub["user_id"]
        u = await db["users"].find_one({"_id": ObjectId(uid)}) if ObjectId.is_valid(uid) else None
        return uid, u or {"_id": uid, "name": "Test User"}

    # Fallback: Find user with recent TEST_PLAN transactions
    tx = await db["payment_transactions"].find_one({"plan_id": "TEST_PLAN", "amount": 1.0})
    if tx:
        uid = tx["user_id"]
        u = await db["users"].find_one({"_id": ObjectId(uid)}) if ObjectId.is_valid(uid) else None
        return uid, u or {"_id": uid, "name": "Test User"}

    return None, None


async def main():
    parser = argparse.ArgumentParser(description="Reset INR 1 Testing Plan for safe repeated testing.")
    parser.add_argument("--user", help="User ID to reset")
    parser.add_argument("--phone", help="Phone number of user to reset")
    parser.add_argument("--email", help="Email of user to reset")
    parser.add_argument("--force", action="store_true", help="Force admin reset even if non-test plan")
    args = parser.parse_args()

    print("==========================================================")
    print("      DhandaGrow INR 1 Test Plan Reset Utility")
    print("==========================================================")

    connect_to_mongo()
    db = get_database()

    user_id, user_doc = await find_target_user(db, args.user, args.phone, args.email)
    if not user_id:
        print("[!] No test user found with TEST_PLAN or specified criteria.")
        sys.exit(1)

    user_name = user_doc.get("name") if user_doc else "Unknown User"
    phone = user_doc.get("phone_number") if user_doc else "N/A"
    email = user_doc.get("email") if user_doc else "N/A"
    print("Target User:")
    print(f"  - User ID: {user_id}")
    print(f"  - Name   : {user_name}")
    print(f"  - Phone  : {phone}")
    print(f"  - Email  : {email}")

    # Inspect current state
    sub = await db["subscriptions"].find_one({"user_id": user_id})
    current_plan = (sub.get("plan_id") or "FREE") if sub else "FREE"
    current_credits = sub.get("credits_remaining", 0) if sub else 0
    print("\nCurrent Subscription State:")
    print(f"  - Active Plan: {current_plan}")
    print(f"  - Credits    : {current_credits}")

    # Execute reset
    print("\nExecuting safe test plan reset...")
    result = await PayinService.reset_test_subscription(db, user_id, admin_override=args.force or True)

    print("\n[OK] Reset completed successfully!")
    print(f"  - User ID                     : {result['user_id']}")
    print(f"  - Previous Plan               : {result['previous_plan']}")
    print(f"  - New Active Plan             : {result['current_plan']}")
    print(f"  - Credits Available           : {result['credits_remaining']}")
    print(f"  - Preserved Paid Orders       : {result['audit_preserved_transactions']}")
    print(f"  - Cancelled Pending Orders    : {result['cancelled_pending_orders']}")
    print("\nAudit trail preserved. The test user can now repeat the INR 1 payment flow safely.")
    print("==========================================================")


if __name__ == "__main__":
    asyncio.run(main())
