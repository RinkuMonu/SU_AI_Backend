import urllib.request
import json

data = json.dumps({"phone_number": "8305029772", "country_code": "+91"}).encode("utf-8")
req = urllib.request.Request("http://127.0.0.1:8000/api/v1/auth/send-otp", data=data, headers={"Content-Type": "application/json"})
try:
    with urllib.request.urlopen(req) as resp:
        print("STATUS:", resp.status)
        print("BODY:", resp.read().decode("utf-8"))
except urllib.error.HTTPError as e:
    print("HTTP_STATUS:", e.code)
    print("HTTP_BODY:", e.read().decode("utf-8"))
except Exception as e:
    print("EXCEPTION:", e)
