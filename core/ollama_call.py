"""
ollama_call.py — simple local Ollama calling script
=====================================================

No classes, no modes, no fancy stuff. Just feed it:
  - model name
  - system prompt (how it should behave)
  - summary / memory (optional context)
  - user query

It returns the model's text response.

Requires: `requests`
Requires Ollama running locally (default: http://localhost:11434)
"""

import requests

OLLAMA_URL = "http://localhost:11434/api/chat"


def call_ollama(model, prompt, query, memory="", temperature=0.7, stream=False):
    """
    model:    ollama model name, e.g. "llama3.1", "qwen2.5", "mistral"
    prompt:   system prompt describing how the model should behave
    query:    the user's actual question/request
    memory:   optional summary/memory text to inject as extra context
    """

    messages = []

    if prompt:
        messages.append({"role": "system", "content": prompt})

    if memory:
        messages.append({
            "role": "system",
            "content": f"Relevant memory/context:\n{memory}"
        })

    messages.append({"role": "user", "content": query})

    payload = {
        "model": model,
        "messages": messages,
        "stream": stream,
        "options": {
            "temperature": temperature
        }
    }

    try:
        response = requests.post(OLLAMA_URL, json=payload, timeout=1000000000)
        response.raise_for_status()
    except requests.RequestException as e:
        return f"[ERROR] Request failed: {e}"

    data = response.json()

    try:
        return data["message"]["content"]
    except (KeyError, TypeError):
        return f"[ERROR] Unexpected response: {data}"


if __name__ == "__main__":
    model_name = input("Model name: ").strip()
    system_prompt = input("System prompt (how it should behave): ").strip()
    memory_summary = input("Summary/memory (optional, press enter to skip): ").strip()
    user_query = input("User query: ").strip()

    result = call_ollama(
        model=model_name,
        prompt=system_prompt,
        query=user_query,
        memory=memory_summary,
    )

    print("\n--- Response ---")
    print(result)