import os

file_path = r'c:\Users\PC8\Downloads\Sevenunique_AI_Frontend\SU_AI_Frontend\app\preview\[id]\page.tsx'

with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# Replace button in hero section
old_hero_button = '<button className="px-8 py-4 bg-brand-purple text-white rounded-full font-bold text-lg hover:bg-brand-pink transition-colors shadow-lg">'
new_hero_button = '<button onClick={() => alert("Action triggered!")} className="px-8 py-4 bg-brand-purple text-white rounded-full font-bold text-lg hover:bg-brand-pink hover:scale-105 transition-all shadow-lg active:scale-95">'

if old_hero_button in content:
    content = content.replace(old_hero_button, new_hero_button)

# Add clickable behavior to nav links
old_nav_link = '<a key={i} href="#" className="font-medium hover:text-brand-purple transition-colors">'
new_nav_link = '<a key={i} href="#" onClick={(e) => { e.preventDefault(); alert("Navigating to " + (p.name || `Page ${i + 1}`)); }} className="font-medium hover:text-brand-purple transition-colors">'

if old_nav_link in content:
    content = content.replace(old_nav_link, new_nav_link)

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)

print("Patch applied")
