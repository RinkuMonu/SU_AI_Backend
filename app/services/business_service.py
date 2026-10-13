from bson import ObjectId
from app.core.database import get_database
from app.models.business import Business
from app.schemas.business import BusinessCreate, BusinessUpdate

class BusinessService:
    @staticmethod
    async def get_collection():
        db = get_database()
        return db["businesses"]

    @staticmethod
    async def create_business(owner_id: str, business_in: BusinessCreate) -> Business:
        collection = await BusinessService.get_collection()
        business_dict = business_in.model_dump()
        business_dict["ownerId"] = owner_id
        business_dict["owner_id"] = owner_id
        business = Business(**business_dict)
        
        doc = business.model_dump(by_alias=True, exclude={"id"})
        result = await collection.insert_one(doc)
        business.id = str(result.inserted_id)
        return business

    @staticmethod
    async def get_business(business_id: str) -> Business | None:
        collection = await BusinessService.get_collection()
        if not ObjectId.is_valid(business_id):
            return None
        doc = await collection.find_one({"_id": ObjectId(business_id)})
        if doc:
            return Business(**doc)
        return None

    @staticmethod
    async def get_business_by_owner(owner_id: str) -> Business | None:
        collection = await BusinessService.get_collection()
        doc = await collection.find_one({
            "$or": [
                {"owner_id": owner_id},
                {"ownerId": owner_id},
                {"userId": owner_id}
            ]
        })
        if doc:
            return Business(**doc)
        return None

    @staticmethod
    async def update_business(owner_id: str, business_in: BusinessUpdate) -> Business | None:
        collection = await BusinessService.get_collection()
        update_data = business_in.model_dump(exclude_unset=True)
        if not update_data:
            return await BusinessService.get_business_by_owner(owner_id)
            
        await collection.update_one(
            {"$or": [{"owner_id": owner_id}, {"ownerId": owner_id}, {"userId": owner_id}]},
            {"$set": update_data}
        )
        return await BusinessService.get_business_by_owner(owner_id)

    @staticmethod
    async def delete_business(owner_id: str) -> bool:
        collection = await BusinessService.get_collection()
        result = await collection.delete_one(
            {"$or": [{"owner_id": owner_id}, {"ownerId": owner_id}, {"userId": owner_id}]}
        )
        return result.deleted_count > 0
