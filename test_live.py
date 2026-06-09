#!/usr/bin/env python3
import urllib.request
import json
import time
import sys

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

tests = [
    ('Hello!', 'greeting'),
    ('What rooms do you have?', 'rooms'),
    ('What is check-in time?', 'check-in'),
    ('What about check-out?', 'check-out'),
    ('Do you have parking?', 'parking'),
    ('Can I bring my dog?', 'pets'),
    ('Tell me about breakfast', 'breakfast'),
    ('Do you have a restaurant?', 'restaurant'),
    ('What about wine?', 'wine'),
    ('Is there a bar?', 'bar'),
    ('Where are you located?', 'location'),
    ('What can I do around Bled?', 'activities'),
    ('How do I book a room?', 'booking'),
    ('Can I check in at 11pm?', 'late check-in'),
    ('Can I check out at 2pm?', 'late check-out'),
    ('Do you have vegan options?', 'vegan'),
    ('I need gluten-free breakfast', 'gluten-free'),
    ('Thank you!', 'thanks'),
    ('Pozdravljeni!', 'Slovenian greeting'),
    ('Haben Sie Zimmer frei?', 'German rooms'),
    ('Bonjour, quelles chambres avez-vous?', 'French rooms'),
    ('Ciao, avete camere disponibili?', 'Italian rooms'),
    ('Hola, tienen habitaciones?', 'Spanish rooms'),
]

issues = []
for msg, label in tests:
    resp = send(msg)
    has_q = '?' in resp or '!' in resp
    has_tech = any(w in resp.lower() for w in ['database', 'sqlite', 'api', 'flask', 'rag', 'tool', 'function'])
    complete = not resp.endswith('...') and len(resp) > 10
    status = 'OK'
    problems = []
    if not has_q:
        problems.append('no follow-up question')
    if has_tech:
        problems.append('tech details leaked')
    if not complete:
        problems.append('incomplete')
    if problems:
        status = 'ISSUE'
        issues.append((label, problems))
    print(f'[{status}] {label}')
    print(f'  Q: {msg}')
    print(f'  A: {resp[:300]}')
    print()
    time.sleep(1.5)

print('='*60)
if issues:
    print(f'ISSUES FOUND: {len(issues)}')
    for label, problems in issues:
        print(f'  - {label}: {", ".join(problems)}')
else:
    print('ALL TESTS PASSED!')
