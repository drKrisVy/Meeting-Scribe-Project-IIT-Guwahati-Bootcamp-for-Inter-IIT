import hashlib
import json
from pathlib import Path

from dotenv import load_dotenv
from groq import Groq

load_dotenv()
client = Groq()

CACHE_DIR = Path(".cache/llm")


def cache_key(model, messages, temperature):
    payload = json.dumps(
        {"model": model, "messages": messages, "temperature": temperature},
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def chat_json(model, system_prompt, user_text, temperature=0, use_cache=True):
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_text},
    ]

    path = CACHE_DIR / f"{cache_key(model, messages, temperature)}.json"

    if use_cache and path.exists():
        print("  (cache hit)")
        return json.loads(path.read_text())

    response = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
        response_format={"type": "json_object"},
    )
    data = json.loads(response.choices[0].message.content)

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))
    return data