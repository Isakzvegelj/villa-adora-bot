import sys
path = sys.argv[1]
n = int(sys.argv[2]) if len(sys.argv) > 2 else 0
with open(path, 'r') as f:
    content = f.read()
    if n > 0:
        print(content[:n])
    else:
        print(content)
