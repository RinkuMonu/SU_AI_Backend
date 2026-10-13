import sys
sys.path.insert(0, ".")
from app.services.facebook_service import FacebookService

url = FacebookService.get_authorization_url(state="test_state")
print("Auth URL:")
print(url)
