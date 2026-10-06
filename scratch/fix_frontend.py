import sys

file_path = r'C:\Users\PC8\Downloads\Sevenunique_AI_Frontend\SU_AI_Frontend\app\(auth)\signup\page.tsx'

with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

target = """      await authService.signup(data.name, data.email, data.password, data.role);
      router.push(`/verify-email?email=${encodeURIComponent(data.email)}`);"""

replacement = """      const response = await authService.signup(data.name, data.email, data.password, data.role);
      if (response.token && response.user) {
        localStorage.setItem("access_token", response.token);
        localStorage.setItem("user", JSON.stringify(response.user));
        window.location.href = "/dashboard";
      } else {
        router.push("/login/user");
      }"""

content = content.replace(target, replacement)

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)

print("Done updating signup/page.tsx")
