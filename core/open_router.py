import os
import sys
import time
import requests
from dotenv import load_dotenv

# Load environment variables from the .env file
load_dotenv()

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# --- Load rotating API keys (oapi1 -> oapi5) from .env ---
API_KEYS = []
for i in range(1, 6):
    key = os.getenv(f"oapi{i}")
    if key:
        API_KEYS.append((f"oapi{i}", key))

if not API_KEYS:
    print("Error: No OpenRouter keys found. Please set oapi1 ... oapi5 in your .env file.")
    sys.exit(1)

print(f"[*] Loaded {len(API_KEYS)} OpenRouter key(s) for rotation: {[label for label, _ in API_KEYS]}")

# Global rotation pointer so rotation position carries over between calls
_current_key_pos = 0


def _call_openrouter(model_name: str, system_prompt: str, user_query: str):
    """
    Low-level call to OpenRouter's chat/completions endpoint, rotating through
    oapi1 -> oapi5 whenever the active key can't serve the request right now
    (429 rate limited, 402 out of credits, 401/403 bad key).

    Returns:
        str: text response on success.
        True: if every available key failed for this model (rate-limited,
              out of credits, or invalid) - i.e. this model tier is unusable.
    """
    global _current_key_pos
    num_keys = len(API_KEYS)
    attempts = 0

    while attempts < num_keys:
        key_label, api_key = API_KEYS[_current_key_pos]

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            # Optional but recommended by OpenRouter for analytics/rankings
            "HTTP-Referer": "https://localhost",
            "X-Title": "free-models-fallback-system",
        }

        payload = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_query},
            ],
            "temperature": 0.7,
        }

        # Status codes that mean "this key can't serve this request right now" -
        # rotate to the next one instead of crashing.
        ROTATE_ON = {
            429: "rate limit hit",
            402: "insufficient credits",
            401: "invalid/revoked key",
            403: "forbidden for this key",
        }

        try:
            resp = requests.post(OPENROUTER_URL, headers=headers, json=payload, timeout=60)

            if resp.status_code in ROTATE_ON:
                reason = ROTATE_ON[resp.status_code]
                print(f"    [-] {key_label} failed ({resp.status_code} {reason}). Rotating to next key...")
                _current_key_pos = (_current_key_pos + 1) % num_keys
                attempts += 1
                continue

            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]

        except requests.exceptions.HTTPError as e:
            status = getattr(e.response, "status_code", None)
            if status in ROTATE_ON:
                reason = ROTATE_ON[status]
                print(f"    [-] {key_label} failed ({status} {reason}). Rotating to next key...")
                _current_key_pos = (_current_key_pos + 1) % num_keys
                attempts += 1
                continue
            raise e

        except Exception as e:
            if "429" in str(e) or "rate limit" in str(e).lower() or "resource exhausted" in str(e).lower():
                print(f"    [-] {key_label} hit rate limit (429). Rotating to next key...")
                _current_key_pos = (_current_key_pos + 1) % num_keys
                attempts += 1
                continue
            raise e

    # Every key rotated through and all hit 429 for this model
    return True


# --- Model-Specific Wrapper Functions ---
# --- Model-Specific Wrapper Functions ---
# --- Model-Specific Wrapper Functions ---

def ask_lite(system_prompt: str, user_query: str):
    """Uses Llama 3.3 70B Instruct (free) - solid general-purpose baseline model, $0 cost."""
    return _call_openrouter("meta-llama/llama-3.3-70b-instruct:free", system_prompt, user_query)

def ask_flash(system_prompt: str, user_query: str):
    """Uses GPT-OSS 20B (free) - efficient open-weight model, strong speed/quality balance, $0 cost."""
    return _call_openrouter("openai/gpt-oss-20b:free", system_prompt, user_query)

def ask_pro(system_prompt: str, user_query: str):
    """Uses Qwen3 Coder 480B (free) - currently the strongest free model on OpenRouter (1M context), $0 cost."""
    return _call_openrouter("qwen/qwen3-coder:free", system_prompt, user_query)

# --- Fallback Orchestrator ---

def get_reliable_response(system_prompt: str, user_query: str) -> str:
    """
    Attempts to get an answer from Pro. 
    Falls back sequentially to Flash and Lite if 429 exhaustion occurs.
    """
    print("[*] Attempting to use Pro tier (Qwen3 Coder, free)...")
    result = ask_pro(system_prompt, user_query)
    
    if result is True:
        print("[!] Pro tier exhausted across all keys. Falling back to Flash tier (GPT-OSS 20B, free)...")
        result = ask_flash(system_prompt, user_query)
        
        if result is True:
            print("[!] Flash tier exhausted across all keys. Falling back to Lite tier (Llama 3.3 70B, free)...")
            result = ask_lite(system_prompt, user_query)
            
            if result is True:
                return "[ERROR] All models are currently exhausted. Please try again later."
    
    return result


# --- Execution Block ---
if __name__ == "__main__":
    print("=== Free-Models (OpenRouter) API Fallback System with Key Rotation (Loaded via .env) ===")
    
    my_system_prompt = (
        "You are an elite, highly technical software engineer. "
        "Keep your answers brutally honest, accurate, and concise."
    )
    my_query = "Explain why standard Docker requires root privileges while Podman does not."
    
    print(f"System Prompt: {my_system_prompt}")
    print(f"User Query: {my_query}\n")
    print("-" * 40)
    
    # Run the orchestrator
    final_answer = get_reliable_response(my_system_prompt, my_query)
    
    print("\n=== Final Response ===")
    print(final_answer)