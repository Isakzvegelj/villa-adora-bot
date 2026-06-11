# Check the actual bytes in the _ROOM_LISTINGS_TRANSLATED["English"] string
with open('/Users/isakzvegelj/Documents/antigravity/villa-adora-bot/app.py', 'r') as f:
    lines = f.readlines()

# Line 135 raw bytes
line135 = lines[134]  # 0-indexed
print("Line 135 raw:", repr(line135))
print()

# Count backslashes before 'n' in the line
import re
matches = re.findall(r'(\\+)n', line135)
for m in matches:
    print(f"Found {len(m)} backslashes before 'n'")
