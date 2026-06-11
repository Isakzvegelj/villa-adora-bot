with open('/Users/isakzvegelj/Documents/antigravity/villa-adora-bot/app.py', 'r') as f:
    content = f.read()
start = content.find('_ROOM_LISTINGS_TRANSLATED')
eng_start = content.find('"English":', start)
eng_end = content.find('),', eng_start + 20)
eng_text = content[eng_start:eng_end+2]
print(repr(eng_text[:300]))
