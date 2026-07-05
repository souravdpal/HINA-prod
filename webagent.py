import pywhatkit
import pyautogui
import time
import json
import os
import re
import logging
import subprocess as sub

import requests
from dotenv import load_dotenv
from groq import Groq

load_dotenv()

# ----------------------------------------------------------------------------
# Logging
# ----------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("webagent")

# ----------------------------------------------------------------------------
# Config / environment validation
# ----------------------------------------------------------------------------
WA_SERVICE_URL = os.getenv("wa_service_url", "http://localhost:3001/send")
API_CODE = os.getenv("codehina")

_RAW_PHONE_BOOK = {
    "dad": os.getenv("dad"),
    "mom": os.getenv("mom"),
    "sourav": os.getenv("x_person"),
}

# International format, digits only, 8-15 digits (E.164 without '+')
_PHONE_RE = re.compile(r"^\d{8,15}$")


def _validate_phone_book(raw: dict) -> dict:
    """Keep only entries with a present, correctly formatted number."""
    valid = {}
    for name, num in raw.items():
        if not num:
            log.warning("No phone number set in .env for '%s' — it will be unusable.", name)
            continue
        num = str(num).strip()
        if not _PHONE_RE.match(num):
            log.warning(
                "Number for '%s' looks malformed (%r). Expected digits only, "
                "e.g. 919876543210 (country code + number, no '+', no spaces).",
                name, num,
            )
            continue
        valid[name] = num
    return valid


phone_book = _validate_phone_book(_RAW_PHONE_BOOK)

if not API_CODE:
    log.warning("GROQ API key ('codehina') not set in .env — what_Format_maker will fail.")

# ----------------------------------------------------------------------------
# YouTube playback
# ----------------------------------------------------------------------------
def Youtubeplay(q):
    if not q or not str(q).strip():
        log.error("Youtubeplay called with empty query.")
        return False
    try:
        pywhatkit.playonyt(str(q))
        time.sleep(2)
        pyautogui.hotkey("alt", "tab")
        return True
    except Exception as e:
        log.error("Youtubeplay failed for query '%s': %s", q, e)
        return False

# ----------------------------------------------------------------------------
# LLM-based message router (raw text -> {person: message})
# ----------------------------------------------------------------------------
system_prompt = """
ignore hina becuse this is user try to call you by:
you are advance filter model for user to whatsapp text you will get raw querry you have
some vaild person which user can text you have to follow strict json format
{
"person_name" :"text"
}
example : text my dad hi
{
"dad" : "hi"
}
valid_phone_book: mom , dad , sourav only theser are the people you can text and select if user try text aunt or freind or somone not in phone book you will just  use
{
"inavlid" : "none"
}
Return ONLY the JSON object. No markdown, no code fences, no commentary.
"""

VALID_PERSONS = {"mom", "dad", "sourav"}


def _strip_code_fences(text: str) -> str:
    """Groq sometimes wraps JSON in ```json ... ``` even with response_format set."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def what_Format_maker(user_prompt: str, max_retries: int = 2):
    """
    Turn raw user text into a {person: message} dict via Groq.
    Returns None on unrecoverable failure instead of raising, so callers
    can handle it gracefully.
    """
    if not user_prompt or not user_prompt.strip():
        log.error("what_Format_maker called with empty prompt.")
        return None

    if not API_CODE:
        log.error("Cannot call Groq: 'codehina' API key missing from .env.")
        return None

    client = Groq(api_key=API_CODE)

    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            completion = client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": "filter this into json : " + user_prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.1,
            )
        except Exception as e:
            last_error = e
            log.warning("Groq API call failed (attempt %d/%d): %s", attempt, max_retries, e)
            time.sleep(1)
            continue

        raw_response = completion.choices[0].message.content
        if raw_response is None:
            last_error = ValueError("Groq returned empty content")
            continue

        cleaned = _strip_code_fences(raw_response)

        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError as e:
            last_error = e
            log.warning(
                "JSON parse failed (attempt %d/%d) on response: %r — %s",
                attempt, max_retries, cleaned[:200], e,
            )
            continue

        if not isinstance(parsed, dict) or not parsed:
            last_error = ValueError(f"Unexpected JSON shape: {parsed!r}")
            log.warning("Groq returned non-dict/empty JSON (attempt %d/%d): %r", attempt, max_retries, parsed)
            continue

        return parsed

    log.error("what_Format_maker failed after %d attempts: %s", max_retries, last_error)
    return None

# ----------------------------------------------------------------------------
# WhatsApp send (via local Baileys service)
# ----------------------------------------------------------------------------
def _post_to_wa_service(number: str, message: str, timeout: int = 15):
    try:
        resp = requests.post(
            WA_SERVICE_URL,
            json={"number": number, "message": message},
            timeout=timeout,
        )
    except requests.ConnectionError:
        log.error(
            "Could not reach WhatsApp service at %s — is it running? "
            "(pm2 list / node index.js)", WA_SERVICE_URL,
        )
        return False
    except requests.Timeout:
        log.error("WhatsApp service timed out after %ds sending to %s.", timeout, number)
        return False
    except requests.RequestException as e:
        log.error("Unexpected network error sending to %s: %s", number, e)
        return False

    if resp.status_code != 200:
        log.error("WhatsApp service returned %d for %s: %s", resp.status_code, number, resp.text[:300])
        return False

    try:
        data = resp.json()
    except ValueError:
        log.error("WhatsApp service returned non-JSON success response: %r", resp.text[:300])
        return False

    if not data.get("ok"):
        log.error("WhatsApp service reported failure for %s: %s", number, data)
        return False

    log.info("Sent to %s successfully.", number)
    return True


def whatsapp_send(t: dict) -> dict:
    """
    Send messages described by {person: message}.
    Returns {person: True/False} indicating per-recipient success.
    Never raises — always returns a result dict so callers (voice/UI layers)
    can react without try/except boilerplate.
    """
    results = {}

    if not isinstance(t, dict) or not t:
        log.error("whatsapp_send called with invalid/empty payload: %r", t)
        return results

    if "invalid" in t or "inavlid" in t:
        log.warning("Router flagged an invalid/unknown recipient: %s", t)
        results["invalid"] = False
        return results

    for person, msg in t.items():
        person_key = str(person).strip().lower()

        if person_key not in VALID_PERSONS:
            log.warning("'%s' is not a recognized contact.", person)
            results[person] = False
            continue

        num = phone_book.get(person_key)
        if not num:
            log.warning("'%s' has no usable phone number configured (check .env).", person)
            results[person] = False
            continue

        if not msg or not str(msg).strip():
            log.warning("Empty message for '%s' — skipping.", person)
            results[person] = False
            continue

        results[person] = _post_to_wa_service(num, str(msg))

    return results


def send_whatsapp_from_text(user_prompt: str) -> dict:
    """
    Convenience end-to-end helper: raw text -> Groq routing -> send.
    Use this from voice/brain layers instead of chaining the two
    functions manually.
    """
    parsed = what_Format_maker(user_prompt)
    if parsed is None:
        log.error("Aborting send: could not parse a valid recipient/message from prompt.")
        return {}
    return whatsapp_send(parsed)


if __name__ == "__main__":
    # Quick manual smoke test
    test_prompt = "text mom good morning"
    print(json.dumps(send_whatsapp_from_text(test_prompt), indent=2))