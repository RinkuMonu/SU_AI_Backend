import os
import re

file_path = r'c:\Users\PC8\Downloads\Sevenunique_AI_Frontend\SU_AI_Frontend\app\preview\[id]\page.tsx'

with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# Add activePageName state
if 'const [activePageName, setActivePageName]' not in content:
    content = content.replace(
        'const [error, setError] = useState("");',
        'const [error, setError] = useState("");\n  const [activePageName, setActivePageName] = useState("Home");'
    )

# Fix pages logic
old_pages_logic = """  const pages = siteData.pages || [];
  const homePage = pages.find((p: any) => p.name?.toLowerCase() === "home") || pages[0] || {};
  const sections = homePage.sections || [];"""

new_pages_logic = """  const pages = siteData.pages || [];
  const activePage = pages.find((p: any) => p.name?.toLowerCase() === activePageName.toLowerCase()) || pages[0] || {};
  const sections = activePage.sections || [];"""

if old_pages_logic in content:
    content = content.replace(old_pages_logic, new_pages_logic)
elif "const homePage" in content:
    # Use regex if exact match fails
    content = re.sub(r'const homePage = [^\n]+\n\s+const sections = [^\n]+', new_pages_logic.split('\n', 1)[1], content)

# Fix Nav links
old_nav_link = 'onClick={(e) => { e.preventDefault(); alert("Navigating to " + (p.name || `Page ${i + 1}`)); }} className="font-medium hover:text-brand-purple transition-colors"'
new_nav_link = 'onClick={(e) => { e.preventDefault(); setActivePageName(p.name || `Page ${i + 1}`); }} className={`font-medium hover:text-brand-purple transition-colors ${activePageName === (p.name || `Page ${i + 1}`) ? "text-brand-purple underline" : ""}`}'

if old_nav_link in content:
    content = content.replace(old_nav_link, new_nav_link)
elif 'className="font-medium hover:text-brand-purple transition-colors"' in content:
    content = content.replace('href="#" className="font-medium hover:text-brand-purple transition-colors"', 'href="#" ' + new_nav_link)

# Fix Business Name title "None"
old_title = '{siteData.business_id || "YourBrand"}'
new_title = '{siteData.business_id !== "None" ? siteData.business_id : "Your Brand"}'

if old_title in content:
    content = content.replace(old_title, new_title)

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)

print("Frontend patch applied")
