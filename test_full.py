#!/usr/bin/env python3
"""Full comprehensive test suite"""
import urllib.request
import json
import time

URL = 'https://villa-adora-bot-r00l.onrender.com/api/chat'

def send(msg):
    data = json.dumps({'message': msg}).encode()
    req = urllib.request.Request(URL, data=data, headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            result = json.loads(resp.read())
            return result.get('replies', [{}])[0].get('content', str(result))
    except Exception as e:
        return f'ERROR: {e}'

issues = []
tests = [
    # English
    ('Hello!', 'greeting', 'en'),
    ('What rooms do you have?', 'rooms', 'en'),
    ('What is check-in time?', 'check-in', 'en'),
    ('What about check-out?', 'check-out', 'en'),
    ('Do you have parking?', 'parking', 'en'),
    ('Can I bring my dog?', 'pets', 'en'),
    ('Tell me about breakfast', 'breakfast', 'en'),
    ('Do you have a restaurant?', 'restaurant', 'en'),
    ('What about wine?', 'wine', 'en'),
    ('Is there a bar?', 'bar', 'en'),
    ('Where are you located?', 'location', 'en'),
    ('What can I do around Bled?', 'activities', 'en'),
    ('How do I book a room?', 'booking', 'en'),
    ('Can I check in at 11pm?', 'late check-in', 'en'),
    ('Can I check out at 2pm?', 'late check-out', 'en'),
    ('Do you have vegan options?', 'vegan', 'en'),
    ('I need gluten-free breakfast', 'gluten-free', 'en'),
    ('Thank you!', 'thanks', 'en'),
    ('Is smoking allowed?', 'smoking', 'en'),
    ('Do you have room service?', 'room service', 'en'),
    ('Do you offer airport shuttle?', 'shuttle', 'en'),
    # Multilingual
    ('Pozdravljeni!', 'Slovenian greeting', 'sl'),
    ('Haben Sie Zimmer frei?', 'German rooms', 'de'),
    ('Bonjour, quelles chambres avez-vous?', 'French rooms', 'fr'),
    ('Ciao, avete camere disponibili?', 'Italian rooms', 'it'),
    ('Hola, tienen habitaciones?', 'Spanish rooms', 'es'),
    ('Que peut-on faire a Bled?', 'French activities', 'fr'),
    ('Erzahlen Sie mir vom Restaurant', 'German restaurant', 'de'),
    ('Kakso sobe imate?', 'Slovenian rooms', 'sl'),
]

for msg, label, lang in tests:
    resp = send(msg)
    
    # Quality checks
    has_q = '?' in resp or '!' in resp
    has_tech = any(w in resp.lower() for w in ['database', 'sqlite', 'api', 'flask', 'rag', 'tool', 'function'])
    complete = not resp.endswith('...') and len(resp) > 10
    
    # Language check for non-English
    non_en = lang != 'en'
    if non_en:
        # Check response is NOT just English generic
        is_generic_en = 'luxury boutique hotel on lake bled' in resp.lower() and '7 unique suites' in resp.lower()
        if is_generic_en:
            problems = ['generic English response to non-English query']
        else:
            problems = []
    else:
        problems = []
    
    if not has_q:
        problems.append('no follow-up ?')
    if has_tech:
        problems.append('tech leak')
    if not complete:
        problems.append('incomplete')
    
    status = 'OK' if not problems else 'ISSUE'
    if problems:
        issues.append((label, problems, resp[:100]))
    
    print(f'[{status}] {label} ({lang})')
    if problems:
        print(f'       Problems: {", ".join(problems)}')
    print(f'       {resp[:200]}')
    print()
    time.sleep(1.5)

print('='*60)
if issues:
    print(f'ISSUES: {len(issues)}/{len(tests)}')
    for label, problems, snippet in issues:
        print(f'  - {label}: {", ".join(problems)}')
        print(f'    "{snippet}..."')
else:
    print(f'ALL {len(tests)} TESTS PASSED!')
