#!/usr/bin/env python3
"""Focused test using subprocess curl"""
import subprocess
import json
import time

URL = 'https://villa-adora-bot-r00l.onrender.com/api/chat'

def send(msg):
    try:
        result = subprocess.run(
            ['curl', '-s', '--max-time', '45', URL, '-X', 'POST', 
             '-H', 'Content-Type: application/json', 
             '-d', json.dumps({'message': msg})],
            capture_output=True, text=True, timeout=50
        )
        data = json.loads(result.stdout)
        return data.get('replies', [{}])[0].get('content', str(data))
    except Exception as e:
        return f'ERROR: {e}'

issues = []
tests = [
    ('Hello!', 'greeting', 'en'),
    ('What can I do around Bled?', 'activities', 'en'),
    ('Is smoking allowed?', 'smoking', 'en'),
    ('Do you have room service?', 'room service', 'en'),
    ('Do you offer airport shuttle?', 'shuttle', 'en'),
    ('Que peut-on faire a Bled?', 'French activities', 'fr'),
    ('Bonjour, quelles chambres avez-vous?', 'French rooms', 'fr'),
    ('Haben Sie Zimmer frei?', 'German rooms', 'de'),
    ('Kakso sobe imate?', 'Slovenian rooms', 'sl'),
    ('Ciao, avete camere?', 'Italian rooms', 'it'),
    ('Hola, tienen habitaciones?', 'Spanish rooms', 'es'),
    ('Thank you!', 'thanks', 'en'),
    ('Do you have vegan options?', 'vegan', 'en'),
    ('Can I check in at 11pm?', 'late check-in', 'en'),
]

for msg, label, lang in tests:
    resp = send(msg)
    
    has_q = '?' in resp or '!' in resp
    has_tech = any(w in resp.lower() for w in ['database', 'sqlite', 'api', 'flask', 'rag'])
    is_generic_en = 'luxury boutique hotel on lake bled' in resp.lower() and '7 unique suites' in resp.lower() and lang != 'en'
    
    problems = []
    if 'ERROR' in resp:
        problems.append('network error')
    else:
        if not has_q:
            problems.append('no follow-up')
        if has_tech:
            problems.append('tech leak')
        if is_generic_en:
            problems.append(f'generic English for {lang}')
    
    status = 'OK' if not problems else 'ISSUE'
    if problems:
        issues.append((label, problems))
    
    print(f'[{status}] {label} ({lang})')
    if problems:
        print(f'       Problems: {", ".join(problems)}')
    resp_clean = resp.replace('\\n', ' ')[:200]
    print(f'       {resp_clean}')
    print()
    time.sleep(1.5)

print('='*60)
if issues:
    print(f'ISSUES: {len(issues)}/{len(tests)}')
    for label, problems in issues:
        print(f'  - {label}: {", ".join(problems)}')
else:
    print(f'ALL {len(tests)} TESTS PASSED!')
