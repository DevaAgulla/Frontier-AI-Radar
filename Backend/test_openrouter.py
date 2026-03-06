"""
Quick smoke-test: OpenRouter → Anthropic Claude
Run:  python test_openrouter.py
"""

import httpx, json, sys, os

API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
URL = "https://openrouter.ai/api/v1/chat/completions"

payload = {
    "model": "anthropic/claude-3.5-sonnet",
    "messages": [
        {"role": "user", "content": "Hey how are you"}
    ],
    "max_tokens": 50,
}

headers = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json",
    "HTTP-Referer": "https://frontier-ai-radar.local",   # required by OpenRouter
    "X-Title": "Frontier AI Radar Test",
}

print("[...] Calling OpenRouter (anthropic/claude-3.5-sonnet) ...")

try:
    resp = httpx.post(URL, json=payload, headers=headers, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    # Extract reply
    reply = data["choices"][0]["message"]["content"]
    model_used = data.get("model", "unknown")

    print(f"[OK] SUCCESS  |  Model: {model_used}")
    print(f"     Reply  : {reply}")
    print(f"     Tokens : prompt={data['usage']['prompt_tokens']}  completion={data['usage']['completion_tokens']}")
except httpx.HTTPStatusError as e:
    print(f"[FAIL] HTTP {e.response.status_code}: {e.response.text}")
    sys.exit(1)
except Exception as e:
    print(f"[FAIL] Error: {e}")
    sys.exit(1)
