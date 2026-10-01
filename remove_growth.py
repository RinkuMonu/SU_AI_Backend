import re
path = r'c:\Users\PC8\Downloads\Sevenunique_AI_Frontend\SU_AI_Frontend\app\(dashboard)\subscription\page.tsx'

try:
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Regex to match the object with id: 'GROWTH' or name: 'GROWTH'
    # Find the START of the object containing "GROWTH"
    
    # Since it's a TSX file, let's just find the exact block if possible
    # We can match { id: 'GROWTH', ... }
    
    pattern = re.compile(r'\{\s*id:\s*[\'"]GROWTH[\'"][\s\S]*?\},?', re.MULTILINE)
    new_content = pattern.sub('', content)

    with open(path, 'w', encoding='utf-8') as f:
        f.write(new_content)
    print("Successfully removed GROWTH plan from frontend.")

except Exception as e:
    print(f"Error: {e}")
