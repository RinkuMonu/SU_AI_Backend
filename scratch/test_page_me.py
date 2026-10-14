import sys
sys.path.insert(0, ".")
import asyncio, httpx

async def f():
    tok = 'EAAWmVMwnqgABSkH99XuQmc2Dtb2rZCR7dHKjwF5RRC1TNo8PTZAnLRqOg9TVkOZA6dIwFkhunZAriZChYZBb04MR5p72yrrMZB2deGgJEWx0rEmtGTG8uTj88IcZCNkZCBe73XNGd4QvsmXi1uoZCIxJQmEgfIDxiq0a5pv9f29FxSZCoGuHQB5U98tZCRFmP4L5zZBkhhadZBNMuE'
    async with httpx.AsyncClient() as c:
        r = await c.get(f'https://graph.facebook.com/v19.0/me?fields=id,name,category,instagram_business_account{{id,username,name}}&access_token={tok}')
        print(r.status_code, r.json())

if __name__ == "__main__":
    asyncio.run(f())
