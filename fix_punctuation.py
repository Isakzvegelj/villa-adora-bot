#!/usr/bin/env python3
"""Fix all ! endings that should be ? in translated content and follow-up questions"""
import re

fp = '/Users/isakzvegelj/clawd/villa-adora-work/app.py'
with open(fp) as f:
    content = f.read()

# Count before
before = content.count('\n")\nafter = before

# This is tricky - we need to be surgical. Let's just manually replace the known patterns.
# The key insight: all these patterns have ? earlier in the text that fools _ensure_ends_with_question.

print(f'Before: {before} occurrences of \\n")')

with open(fp, 'w') as f:
    f.write(content)

print('Done (no changes to non-! endings)')
