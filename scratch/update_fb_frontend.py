import os

p = os.path.abspath(os.path.join("..", "SU_AI_Frontend", "app", "(dashboard)", "social-platforms", "facebook", "page.tsx"))
with open(p, "r", encoding="utf-8") as f:
    text = f.read()

target = """    if (typeof window !== "undefined") {
      const params = new URLSearchParams(window.location.search);
      const pageTokenFromUrl = params.get('fb_access_token') || params.get('page_access_token');
      const userTokenFromUrl = params.get('user_access_token') || params.get('access_token') || params.get('token');"""

replacement = """    if (typeof window !== "undefined") {
      const params = new URLSearchParams(window.location.search);
      const jwtTokenFromUrl = params.get('token') || params.get('jwt_token');
      if (jwtTokenFromUrl) {
        localStorage.setItem('access_token', jwtTokenFromUrl);
      }
      const pageTokenFromUrl = params.get('fb_access_token') || params.get('page_access_token');
      const userTokenFromUrl = params.get('user_access_token') || params.get('fb_user_access_token');"""

assert target in text, "target string not found in page.tsx"
new_text = text.replace(target, replacement, 1)

with open(p, "w", encoding="utf-8") as f:
    f.write(new_text)

print("Facebook page.tsx updated successfully!")
