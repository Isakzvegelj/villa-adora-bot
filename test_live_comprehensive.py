#!/usr/bin/env python3
"""Comprehensive live bot test"""
import requests
import json
import time
import sys

BASE = 'https://villa-adora-bot-r00l.onrender.com/api/chat'

tests = [
    # Basic info
    ('rooms', 'What rooms do you have available?'),
    ('check-in/out', 'What are your check-in and check-out times?'),
    ('parking', 'Do you have parking?'),
    ('pets', 'Can I bring my dog?'),
    ('breakfast', 'Do you serve breakfast?'),
    ('restaurant', 'Tell me about your restaurant'),
    ('wine', 'Do you have local wine?'),
    ('bar', 'Do you have a bar?'),
    ('location', 'Where are you located?'),
    ('activities', 'What activities are nearby?'),
    ('booking', 'How do I make a booking?'),
    ('late check-in', 'Can I check in late at night?'),
    ('late check-out', 'Can I check out late?'),
    ('dietary vegan', 'Do you have vegan options?'),
    ('dietary gluten-free', 'Is there gluten-free food?'),
    # Multilingual
    ('slovenian', 'Kakšne so vaše sobe?'),
    ('german', 'Welche Zimmer haben Sie?'),
    ('italian', 'Quali camere avete?'),
    ('french', 'Quelles chambres avez-vous?'),
    ('spanish', '¿Qué habitaciones tienen?'),
]

results = []
for name, msg in tests:
    try:
        r = requests.post(BASE, json={'message': msg}, timeout=30)
        data = r.json()
        resp = data.get('response', data.get('message', ''))
        
        # Check completeness
        ends_with_q = resp.strip().endswith('?')
        # Check for tech leaks
        tech_leaks = any(w in resp.lower() for w in ['database', 'api', 'sql', 'json', 'python', 'flask', 'server', 'function', 'code', 'endpoint'])
        # Check not too short
        too_short = len(resp) < 50
        # Check not cut off (ends with ... or mid-word)
        cut_off = resp.strip().endswith('...') or resp.strip().endswith('..')
        
        issues = []
        if not ends_with_q: issues.append('no_question')
        if tech_leaks: issues.append('tech_leak')
        if too_short: issues.append('too_short')
        if cut_off: issues.append('cut_off')
        
        status = 'OK' if not issues else ', '.join(issues)
        results.append({'topic': name, 'status': status, 'len': len(resp), 'resp': resp[:200], 'issues': issues})
        print(f'[{name}] {status} (len={len(resp)})')
        print(f'  -> {resp[:150]}')
        print()
        time.sleep(0.3)
    except Exception as e:
        results.append({'topic': name, 'status': 'ERROR', 'error': str(e)})
        print(f'[{name}] ERROR: {e}')
        time.sleep(0.3)

print('\n=== SUMMARY ===')
ok_count = sum(1 for r in results if r['status'] == 'OK')
fail_count = len(results) - ok_count
print(f'Passed: {ok_count}/{len(results)}')
print(f'Failed: {fail_count}/{len(results)}')
for r in results:
    if r['status'] != 'OK':
        print(f"  FAIL: {r['topic']} - {r['status']}")
        if 'resp' in r:
            print(f"        Response: {r['resp'][:100]}")
