import os

file_path = r'c:\Users\PC8\Downloads\Sevenunique_AI_Frontend\SU_AI_Frontend\app\preview\[id]\page.tsx'

with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

old_title = '{siteData.business_id !== "None" ? siteData.business_id : "Your Brand"}'
new_title = '{siteData.business_name || (siteData.business_id !== "None" ? siteData.business_id : "Your Brand")}'

if old_title in content:
    content = content.replace(old_title, new_title)

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)

print("Frontend patch for business_name applied")
