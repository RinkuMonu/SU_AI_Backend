import re

with open('create_ad_page.tsx', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Remove old imports
content = content.replace('import PlatformSelector from "@/components/create-ad/PlatformSelector";\nimport ObjectiveSelector from "@/components/create-ad/ObjectiveSelector";\n', '')

# 2. Replace state variables
states_to_replace = r'''  const \[platform, setPlatform\] =
    useState\("instagram"\);

  const \[objective, setObjective\] =
    useState\("product_promotion"\);

  const \[language, setLanguage\] =
    useState\("English"\);

  const \[audience, setAudience\] =
    useState\(""\);

  const \[instruction, setInstruction\] =
    useState\(""\);

  const \[cta, setCta\] =
    useState\("Shop Now"\);'''

content = re.sub(states_to_replace, '  const [prompt, setPrompt] = useState("");', content, flags=re.MULTILINE)

# 3. Update handleGenerate
handle_gen_old = r'''    await create\(\{
      product_id: productId,
      platform,
      objective,
      language,
      target_audience: audience,
      additional_instruction: instruction,
      cta,
    \}\);'''
handle_gen_new = r'''    await create({
      product_id: productId,
      prompt: prompt,
    });'''
content = re.sub(handle_gen_old, handle_gen_new, content)

# 4. Replace form fields
form_old = r'''          <PlatformSelector[\s\S]*?className="min-h-28 w-full rounded-lg border border-border bg-surface-elevated text-white p-3 focus:ring-2 focus:ring-brand-purple outline-none resize-none"
            />

          </div>'''

form_new = r'''          <div>
            <label className="mb-2 block font-semibold text-white">
              Ad Prompt
            </label>
            <textarea
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              placeholder="Describe the ad you want to generate in detail..."
              className="min-h-[200px] w-full rounded-lg border border-border bg-surface-elevated text-white p-4 focus:ring-2 focus:ring-brand-purple outline-none resize-none"
            />
          </div>'''

content = re.sub(form_old, form_new, content)

# 5. Fix CTA in preview
content = content.replace('{cta}', '{"Shop Now"}')

# 6. Update handlePublish
publish_old = r'''    // Simulate API call to save and publish
    await new Promise\(\(resolve\) => setTimeout\(resolve, 1500\)\);
    
    if \(publishPlatform === 'facebook'\) setIsPublishingFacebook\(false\);
    else setIsPublishingInstagram\(false\);
    
    setPublishSuccessMessage\(`Successfully Published to \$\{publishPlatform.charAt\(0\).toUpperCase\(\) \+ publishPlatform.slice\(1\)\}!`\);
    setTimeout\(\(\) => setPublishSuccessMessage\(null\), 5000\);'''

publish_new = r'''    try {
      const token = localStorage.getItem('token');
      const baseUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
      const res = await fetch(`${baseUrl}/api/v1/social/publish-${publishPlatform}/${result?.id}`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        }
      });
      if (!res.ok) throw new Error('Publish failed');
      
      setPublishSuccessMessage(`Successfully Published to ${publishPlatform.charAt(0).toUpperCase() + publishPlatform.slice(1)}!`);
      setTimeout(() => setPublishSuccessMessage(null), 5000);
    } catch (err) {
      console.error(err);
      alert('Failed to publish. Please ensure you have linked your account.');
    } finally {
      if (publishPlatform === 'facebook') setIsPublishingFacebook(false);
      else setIsPublishingInstagram(false);
    }'''

content = re.sub(publish_old, publish_new, content)

with open('create_ad_page.tsx', 'w', encoding='utf-8') as f:
    f.write(content)
print('Done frontend script.')
