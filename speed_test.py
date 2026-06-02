#!/usr/bin/env python3
import requests, time

url = "http://localhost:5001/api/chat"
payload = {"session_id":"test","message":"list rooms"}

# Warmup
requests.post(url, json=payload, timeout=30)

# Time it
start = time.time()
resp = requests.post(url, json=payload, timeout=30)
elapsed = time.time() - start

print(f"Status: {resp.status_code}")
print(f"Time: {elapsed:.2f}s")
print("Response:", resp.json()['replies'][0]['content'][:150])
