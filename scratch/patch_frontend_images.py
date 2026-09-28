import os

file_path = r'c:\Users\PC8\Downloads\Sevenunique_AI_Frontend\SU_AI_Frontend\app\preview\[id]\page.tsx'

with open(file_path, 'r', encoding='utf-8') as f:
    content = f.read()

# Replace the feature card rendering
old_feature_card = """                      <div 
                        key={i} 
                        onClick={() => alert(`Feature clicked: ${item}`)}
                        className="p-6 bg-white rounded-xl shadow-sm border border-gray-100 hover:shadow-md transition-shadow cursor-pointer"
                      >
                        <h3 className="font-bold text-lg text-brand-purple">{item}</h3>
                      </div>"""

new_feature_card = """                      <div 
                        key={i} 
                        onClick={() => alert(`Feature clicked: ${item}`)}
                        className="flex flex-col bg-white rounded-xl shadow-md border border-gray-100 hover:shadow-2xl hover:-translate-y-2 hover:scale-[1.02] transition-all duration-300 cursor-pointer overflow-hidden group"
                      >
                        <div className="w-full h-48 bg-gray-200 relative overflow-hidden">
                          <img 
                            src={`https://image.pollinations.ai/prompt/${encodeURIComponent((siteData.business_name || siteData.business_id) + " " + item.substring(0, 50))}?width=400&height=300&nologo=true`} 
                            alt={item} 
                            className="w-full h-full object-cover group-hover:scale-110 transition-transform duration-700" 
                            loading="lazy" 
                          />
                        </div>
                        <div className="p-6 flex flex-col justify-start">
                          <h3 className="font-bold text-brand-purple text-base leading-relaxed">{item}</h3>
                        </div>
                      </div>"""

if old_feature_card in content:
    content = content.replace(old_feature_card, new_feature_card)
else:
    print("WARNING: Could not find old feature card block exactly.")
    # Try finding it dynamically just in case
    import re
    content = re.sub(
        r'<div[^>]*key=\{i\}[^>]*onClick=\{[^\}]*\}[^>]*className="p-6 bg-white rounded-xl shadow-sm border border-gray-100 hover:shadow-md transition-shadow cursor-pointer"[^>]*>\s*<h3[^>]*>\{item\}</h3>\s*</div>',
        new_feature_card,
        content,
        flags=re.MULTILINE
    )

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)

print("Frontend patch for images and animations applied")
