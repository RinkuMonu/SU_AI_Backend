import os

path = os.path.abspath(os.path.join("..", "SU_AI_Frontend", "app", "(auth)", "login", "user", "page.tsx"))
print("Target file:", path)

with open(path, "r", encoding="utf-8") as f:
    text = f.read()

old_social = """  const handleSocialLogin = (provider: "Gmail" | "Facebook" | "LinkedIn") => {
    setError("");
    setSocialLoading(provider);
    setSocialNotice(`Connecting with ${provider}... Initializing secure session.`);
    setTimeout(() => {
      setSocialLoading(null);
      setSocialNotice(
        `OAuth notice: ${provider} integration is active in development mode. You can sign in using your registered email and password.`
      );
    }, 1200);
  };"""

new_social = """  const handleSocialLogin = async (provider: "Gmail" | "Facebook" | "LinkedIn") => {
    setError("");
    if (provider === "Facebook") {
      setSocialLoading("Facebook");
      try {
        const origin = typeof window !== "undefined" ? window.location.origin : "http://localhost:3000";
        const res = await api.get(`/api/facebook/connect?frontend_url=${encodeURIComponent(origin)}&rerequest=true`);
        const authUrl = res.data?.authorization_url || res.data?.url;
        if (authUrl) {
          window.location.href = authUrl;
          return;
        }
      } catch (err: any) {
        console.error("Facebook connect error:", err);
        setError("Failed to initialize Facebook Login: " + (err.response?.data?.detail || err.message));
        setSocialLoading(null);
        return;
      }
    }
    setSocialLoading(provider);
    setSocialNotice(`Connecting with ${provider}... Initializing secure session.`);
    setTimeout(() => {
      setSocialLoading(null);
      setSocialNotice(
        `OAuth notice: ${provider} integration is active in development mode. You can sign in using your registered email and password.`
      );
    }, 1200);
  };"""

assert old_social in text, "old_social not found"
text = text.replace(old_social, new_social, 1)

with open(path, "w", encoding="utf-8") as f:
    f.write(text)

print("Updated login/user/page.tsx successfully!")
