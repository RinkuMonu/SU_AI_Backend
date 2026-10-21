from typing import Any, Dict, Optional
from datetime import datetime
from bson import ObjectId

def serialize_mongo(obj: Any) -> Any:
    """Recursively converts MongoDB ObjectId and datetime instances to serializable formats."""
    if isinstance(obj, ObjectId):
        return str(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, dict):
        new_dict = {}
        for k, v in obj.items():
            if k == "_id":
                str_id = str(v)
                new_dict["_id"] = str_id
                if "id" not in obj:
                    new_dict["id"] = str_id
            else:
                new_dict[k] = serialize_mongo(v)
        return new_dict
    if isinstance(obj, list):
        return [serialize_mongo(item) for item in obj]
    return obj

def success_response(message: str, data: Optional[Any] = None) -> Dict[str, Any]:
    response = {
        "success": True,
        "message": message,
    }
    if data is not None:
        response["data"] = serialize_mongo(data)
    else:
        response["data"] = {}
    return response


def error_response(message: str, error_code: str, details: Optional[Any] = None) -> Dict[str, Any]:
    response = {
        "success": False,
        "message": message,
        "error": {
            "code": error_code
        }
    }
    if details is not None:
        response["error"]["details"] = details
    return response

