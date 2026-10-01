import sys
import os

p = r'c:\Users\PC8\Downloads\Sevenunique_AI_Backend\SU_AI_Backend\app\api\endpoints\website_builder.py'
with open(p, 'r', encoding='utf-8') as f:
    c = f.read()

target = """            msg_data = {
                "message": resp.message,
                "type": msg_type,
                "messages": session.messages
            }"""

replacement = """            site = None
            if session.website_project_id:
                site = await WebsiteBuilderService.get_website(str(session.website_project_id), str(current_user.id))
            
            msg_data = {
                "message": resp.message,
                "type": msg_type,
                "messages": session.messages,
                "siteId": str(session.website_project_id) if session.website_project_id else None,
                "generatedSiteData": site.pages if site else None
            }"""

# handle windows newlines
c = c.replace(target, replacement)
c = c.replace(target.replace('\n', '\r\n'), replacement.replace('\n', '\r\n'))

with open(p, 'w', encoding='utf-8') as f:
    f.write(c)

print("Done")
