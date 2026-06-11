import re

with open('/Users/isakzvegelj/Documents/antigravity/villa-adora-bot/app.py', 'r') as f:
    content = f.read()

# Fix 1: Add more Slovenian distinctive phrases
old_slovenian = '''        "Slovenian": [
            " pozdravljeni ", " hvala lepo ", " prosim vas ", " kako ste ",
            " dober dan ", " lahko no\u010d ", " nasvidenje ", " rezervacija ", " zajtrk ",
            " soba ", " sobe ", " apartma ", " kajenje ", " kaditi ", " dovoljeno ",
            " prepovedano ", " omogo\u010deno ", " ali je ", " ali imate ", " kak\u0161na ",
            " kak\u0161ne ", " kateri ", " katera ", " kje lahko ", " koliko stane ",
            "\u017eelim rezervirati ", " kje ste ", " lep dan ", " sr\u010dno pozdravljeni "
        ],'''

new_slovenian = '''        "Slovenian": [
            " pozdravljeni ", " hvala lepo ", " prosim vas ", " kako ste ",
            " dober dan ", " lahko no\u010d ", " nasvidenje ", " rezervacija ", " zajtrk ",
            " soba ", " sobe ", " apartma ", " kajenje ", " kaditi ", " dovoljeno ",
            " prepovedano ", " omogo\u010deno ", " ali je ", " ali imate ", " kak\u0161na ",
            " kak\u0161ne ", " kateri ", " katera ", " kje lahko ", " koliko stane ",
            "\u017eelim rezervirati ", " kje ste ", " lep dan ", " sr\u010dno pozdravljeni ",
            " lahko ", " pripeljem ", " psa ", " pes ", " psi ", " ma\u010dka ",
            " hvala ", " prosim ", " zdravo ", " pozdrav ", " dobrodo\u0161li ",
            " apartmaji ", " sobah ", " jezero ", " otok ", " razgled ",
        ],'''

if old_slovenian in content:
    content = content.replace(old_slovenian, new_slovenian)
    print('Fixed Slovenian distinctive phrases')
else:
    print('ERROR: Could not find Slovenian section')

# Fix 2: Add 'psa' to pets topic keywords
old_pets = '''        "pets": ["pet", "pets", "dog", "dogs", "cat", "cats", "animal", "pes", "ma\u010dka", "hund", "katze", "cane", "gatto", "chien", "chat", "perro", "gato", "mascot"],'''
new_pets = '''        "pets": ["pet", "pets", "dog", "dogs", "cat", "cats", "animal", "pes", "psa", "ma\u010dka", "macka", "hund", "katze", "cane", "gatto", "chien", "chat", "perro", "gato", "mascot"],'''

if old_pets in content:
    content = content.replace(old_pets, new_pets)
    print('Fixed pets keywords')
else:
    print('ERROR: Could not find pets keywords')

with open('/Users/isakzvegelj/Documents/antigravity/villa-adora-bot/app.py', 'w') as f:
    f.write(content)

print('Done!')
