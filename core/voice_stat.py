#!/usr/bin/env python3
"""
voice_status.py
----------------
Asks the HINA server whether the voice-reply toggle is ON or OFF.

The server persists the toggle state in voice_state.json (written by
POST /voice/toggle whenever the user flips the switch in the UI) and
exposes it at GET /voice/status. This module hits that endpoint and
exposes the plain integer the rest of the pipeline expects:

    1  -> voice replies are ON
    0  -> voice replies are OFF (or the server could not be reached)

As a module:
    from voice_status import get_voice_status, is_voice_on, VoiceStatusError

    value = get_voice_status()          # -> 1 or 0
    if is_voice_on():                   # -> True / False
        ...

    # custom host/port, or raise instead of failing-safe:
    get_voice_status(host="127.0.0.1", port=3000)
    get_voice_status(raise_on_error=True)   # raises VoiceStatusError instead of returning 0

As a script:
    python3 voice_status.py                # prints 1 or 0
    python3 voice_status.py --json         # prints the raw JSON body
    python3 voice_status.py --host 127.0.0.1 --port 3000

Exit codes (CLI only):
    0  -> success (regardless of whether voice is on or off)
    1  -> could not reach the server / bad response
"""

import argparse
import json
import sys
import urllib.error
import urllib.request

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 3000
DEFAULT_TIMEOUT = 3.0


class VoiceStatusError(Exception):
    """Raised when the HINA server can't be reached or returns a bad response."""
    pass


def fetch_voice_status(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, timeout: float = DEFAULT_TIMEOUT) -> dict:
    """
    Hit GET /voice/status on the HINA server and return the parsed JSON body,
    e.g. {"voice_enabled": true, "value": 1}.

    Raises VoiceStatusError on network failure or a malformed response.
    """
    url = f"http://{host}:{port}/voice/status"
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body)
    except (urllib.error.URLError, TimeoutError, ConnectionError) as err:
        raise VoiceStatusError(f"could not reach server at {url}: {err}") from err
    except (json.JSONDecodeError, ValueError) as err:
        raise VoiceStatusError(f"bad response from {url}: {err}") from err


def get_voice_status(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT,
                      timeout: float = DEFAULT_TIMEOUT, raise_on_error: bool = False) -> int:
    """
    Return 1 if voice replies are ON, 0 if OFF.

    By default, any error (server unreachable, bad JSON, etc.) fails safe
    and returns 0. Pass raise_on_error=True to instead raise VoiceStatusError.
    """
    try:
        data = fetch_voice_status(host=host, port=port, timeout=timeout)
    except VoiceStatusError:
        if raise_on_error:
            raise
        return 0

    # Server already returns `value: 1|0`, but re-derive it here too so
    # this stays correct against an older server build that only sends
    # `voice_enabled: true|false`.
    value = data.get("value")
    if value is None:
        value = 1 if data.get("voice_enabled") is True else 0
    return int(value)


def is_voice_on(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT,
                 timeout: float = DEFAULT_TIMEOUT, raise_on_error: bool = False) -> bool:
    """Convenience wrapper around get_voice_status() that returns a bool."""
    return get_voice_status(host=host, port=port, timeout=timeout, raise_on_error=raise_on_error) == 1


def _main() -> int:
    parser = argparse.ArgumentParser(description="Get HINA's voice-reply toggle state.")
    parser.add_argument("--host", default=DEFAULT_HOST, help=f"HINA server host (default: {DEFAULT_HOST})")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"HINA server port (default: {DEFAULT_PORT})")
    parser.add_argument("--json", action="store_true", help="Print the full JSON response instead of just 0/1")
    args = parser.parse_args()

    try:
        if args.json:
            data = fetch_voice_status(args.host, args.port)
            print(json.dumps(data))
        else:
            print(get_voice_status(args.host, args.port, raise_on_error=True))
    except VoiceStatusError as err:
        print(f"[voice_status] {err}", file=sys.stderr)
        print(0)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(_main())