# Check what the actual Python string value is for the English room listings
# Parse the string literal directly from the source file
with open('/Users/isakzvegelj/Documents/antigravity/villa-adora-bot/app.py', 'r') as f:
    lines = f.readlines()

# Find the English room listing start
in_english = False
in_string = False
string_lines = []
for i, line in enumerate(lines):
    if '"English":' in line and '_ROOM_LISTINGS_TRANSLATED' not in line:
        in_english = True
    if in_english:
        string_lines.append(line)
        if '),' in line:
            break

# Join and evaluate the string literal
raw = ''.join(string_lines)
# Extract just the string value between the first ( and the last )
# The format is: "English": ( "...", "...", ... ),
# We need to concatenate the string parts
import re
# Find all string parts between quotes
parts = re.findall(r'"([^"]*)"', raw)
# The first part is "English": so skip it
# Actually let's be more careful - find the tuple content
start = raw.find('(')
end = raw.rfind(')')
tuple_content = raw[start+1:end]

# Parse the tuple elements - they are quoted strings
# Use a simple approach: eval the tuple
text = eval('(' + tuple_content + ')')
if isinstance(text, tuple):
    text = ''.join(text)

print("Type:", type(text))
print("Length:", len(text))
print("Contains actual newline:", "\n" in text)
print("Contains literal backslash-n:", repr("\\n") in repr(text))
print()
print("Full text:")
print(repr(text[:200]))
print()
print("Rendered:")
print(text)
