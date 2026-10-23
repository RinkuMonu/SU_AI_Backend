"""
Migration & Reconciliation Script:
1. Reconciles and unsets duplicate fields in MongoDB `users` collection:
   - Sets canonical `googleId`, unsets `google_id`.
   - Sets canonical `phone_number`, unsets `phone` and `contactNumber`.
   - Sets canonical `email_verified` & `email_verified_at`, unsets `emailVerified` and `emailVerifiedAt`.
   - Sets canonical `name`, unsets `fullName`.
2. Establishes canonical MongoDB indexes on `users` (sparse unique on email, sparse on googleId) and drops obsolete `google_id_1_sparse`.
3. Migrates any orphaned pending users from `pending_users` to `users`.
"""
import asyncio
import logging
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.core.database import get_database, connect_to_mongo, close_mongo_connection

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("migration")

async def run_migration():
    connect_to_mongo()
    db = get_database()
    logger.info("Starting database reconciliation and index migration...")

    # 1. Reconcile and unset duplicate fields in `users`
    users_col = db["users"]
    reconciled_count = 0
    unset_count = 0

    async for u in users_col.find({}):
        set_updates = {}
        unset_updates = {}

        # Canonical googleId vs obsolete google_id
        gid = u.get("googleId") or u.get("google_id")
        if gid and u.get("googleId") != gid:
            set_updates["googleId"] = gid
        if "google_id" in u:
            unset_updates["google_id"] = ""

        # Canonical phone_number vs obsolete phone & contactNumber
        pn = u.get("phone_number") or u.get("phone") or u.get("contactNumber")
        if pn and u.get("phone_number") != pn:
            set_updates["phone_number"] = pn
        if "phone" in u:
            unset_updates["phone"] = ""
        if "contactNumber" in u:
            unset_updates["contactNumber"] = ""

        # Canonical email_verified & email_verified_at vs obsolete emailVerified & emailVerifiedAt
        ev = bool(u.get("email_verified", u.get("emailVerified", False)))
        if u.get("email_verified") != ev:
            set_updates["email_verified"] = ev
        if "emailVerified" in u:
            unset_updates["emailVerified"] = ""

        ev_at = u.get("email_verified_at") or u.get("emailVerifiedAt")
        if ev_at and u.get("email_verified_at") != ev_at:
            set_updates["email_verified_at"] = ev_at
        if "emailVerifiedAt" in u:
            unset_updates["emailVerifiedAt"] = ""

        # Canonical name vs obsolete fullName
        fn = u.get("name") or u.get("fullName")
        if fn and u.get("name") != fn:
            set_updates["name"] = fn
        if "fullName" in u:
            unset_updates["fullName"] = ""

        update_ops = {}
        if set_updates:
            update_ops["$set"] = set_updates
        if unset_updates:
            update_ops["$unset"] = unset_updates

        if update_ops:
            await users_col.update_one({"_id": u["_id"]}, update_ops)
            reconciled_count += 1
            if unset_updates:
                unset_count += len(unset_updates)

    logger.info(f"Reconciled {reconciled_count} user documents. Unset {unset_count} redundant duplicate field instances.")

    # 2. Migrate orphaned records in `pending_users`
    pending_col = db["pending_users"]
    migrated_pending = 0
    removed_duplicates = 0
    now = datetime.now(timezone.utc)

    async for p in pending_col.find({}):
        email = p.get("email")
        if not email:
            continue
        clean_email = email.lower().strip()
        existing_user = await users_col.find_one({"email": clean_email})
        if existing_user:
            # User already exists in users, safe to remove stale pending duplicate
            await pending_col.delete_one({"_id": p["_id"]})
            removed_duplicates += 1
        else:
            # Normalize to canonical fields before migrating to users
            doc = dict(p)
            doc["updated_at"] = now
            if not doc.get("created_at"):
                doc["created_at"] = now
            if "phone_verified" not in doc:
                doc["phone_verified"] = False

            # Canonical conversions
            c_name = doc.get("name") or doc.get("fullName") or "User"
            doc["name"] = c_name
            doc.pop("fullName", None)

            c_phone = doc.get("phone_number") or doc.get("phone") or doc.get("contactNumber")
            if c_phone:
                doc["phone_number"] = c_phone
            doc.pop("phone", None)
            doc.pop("contactNumber", None)

            c_gid = doc.get("googleId") or doc.get("google_id")
            if c_gid:
                doc["googleId"] = c_gid
            doc.pop("google_id", None)

            c_ev = bool(doc.get("email_verified", doc.get("emailVerified", False)))
            doc["email_verified"] = c_ev
            doc.pop("emailVerified", None)
            doc.pop("emailVerifiedAt", None)

            await users_col.insert_one(doc)
            await pending_col.delete_one({"_id": p["_id"]})
            migrated_pending += 1

    logger.info(f"Migrated {migrated_pending} pending users to 'users'; deleted {removed_duplicates} duplicate pending users.")

    # 3. Create Canonical Indexes on `users` and Drop Obsolete Indexes
    indexes = await users_col.index_information()

    # Drop obsolete index: google_id_1_sparse
    if "google_id_1_sparse" in indexes:
        logger.info("Dropping obsolete index 'google_id_1_sparse' from users collection...")
        await users_col.drop_index("google_id_1_sparse")
        logger.info("Index 'google_id_1_sparse' dropped successfully.")
    else:
        logger.info("Obsolete index 'google_id_1_sparse' is not present.")

    # Index: email (sparse unique)
    if "email_1_sparse_unique" not in indexes:
        logger.info("Creating sparse unique index on users.email...")
        await users_col.create_index(
            [("email", 1)],
            unique=True,
            sparse=True,
            name="email_1_sparse_unique"
        )
        logger.info("Index 'email_1_sparse_unique' created successfully.")
    else:
        logger.info("Index 'email_1_sparse_unique' already exists.")

    # Index: googleId (sparse)
    if "googleId_1_sparse" not in indexes:
        logger.info("Creating sparse index on users.googleId...")
        await users_col.create_index(
            [("googleId", 1)],
            sparse=True,
            name="googleId_1_sparse"
        )
        logger.info("Index 'googleId_1_sparse' created successfully.")
    else:
        logger.info("Index 'googleId_1_sparse' already exists.")

    logger.info("Migration completed successfully.")

if __name__ == "__main__":
    asyncio.run(run_migration())
