#!/usr/bin/env python3
"""Quick check that ADAPTION_API_KEY is valid.

Hits the Adaption Labs "list datasets" endpoint, which requires auth but has
no side effects. A 200 means the key works.

Usage:
    python src/test_api_key.py
"""
import os
import sys

import requests
from dotenv import load_dotenv

BASE_URL = "https://api.prod.adaptionlabs.ai"

load_dotenv()  # read .env from the project root

api_key = os.getenv("ADAPTION_API_KEY")
if not api_key:
    sys.exit("ADAPTION_API_KEY is not set (check your .env file).")

print(f"Using key: {api_key[:8]}...{api_key[-4:]}")

resp = requests.get(
    f"{BASE_URL}/api/v1/datasets",
    headers={"Authorization": f"Bearer {api_key}"},
    timeout=30,
)

if resp.status_code == 200:
    data = resp.json()
    items = data.get("data", data) if isinstance(data, dict) else data
    count = len(items) if isinstance(items, list) else "?"
    print(f"OK - key is valid. Server returned {count} dataset(s).")
elif resp.status_code in (401, 403):
    print(f"INVALID - key was rejected (HTTP {resp.status_code}).")
    print(resp.text[:500])
    sys.exit(1)
else:
    print(f"Unexpected response: HTTP {resp.status_code}")
    print(resp.text[:500])
    sys.exit(1)
