from PIL import Image
from imagekitio import ImageKit
from dotenv import load_dotenv
from pathlib import Path
import os
import re
import uuid
import time
import requests
from groq import Groq


load_dotenv()

imagekit = ImageKit(
    private_key=os.getenv("ig_private")
    #public_key=os.getenv("ig_public_key"),
    #url_endpoint=os.getenv("url_endpoint")
)

HINA_SERVER = os.getenv("hina_server_url", "http://127.0.0.1:3000")

# ------------------------------------------------------------
# API key router — api1..api5
# ------------------------------------------------------------
# Groq (and most inference APIs) rate-limit / occasionally 5xx per
# key. Instead of the whole image pipeline dying on one bad/limited
# key, keep a small pool of keys (env vars api1..api5) and fail over
# to the next one whenever a call errors out.
API_KEY_ENVS = ["api1", "api2", "api3", "api4", "api5"]


def _available_keys():
    keys = []
    for env_name in API_KEY_ENVS:
        val = os.getenv(env_name)
        if val:
            keys.append((env_name, val))
    return keys


def call_groq_with_fallback(build_kwargs, max_retries_per_key=1):
    """Try each configured api key in turn. build_kwargs is a callable
    that returns the kwargs dict for client.chat.completions.create()
    (kept as a callable so nothing about the request is shared/mutated
    across attempts). Returns the completion response on first success,
    raises the last error if every key is exhausted.
    """
    keys = _available_keys()
    if not keys:
        raise RuntimeError("No Groq API keys configured (expected one or more of api1..api5 in env)")

    last_err = None
    for env_name, key in keys:
        client = Groq(api_key=key)
        for attempt in range(max_retries_per_key):
            try:
                completion = client.chat.completions.create(**build_kwargs())
                return completion
            except Exception as e:
                last_err = e
                print(f"[image2text] {env_name} failed (attempt {attempt + 1}/{max_retries_per_key}): {e}")
                time.sleep(0.5)
        print(f"[image2text] {env_name} exhausted, falling back to next key...")

    raise RuntimeError(f"All Groq API keys failed. Last error: {last_err}")


THINK_TAG_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
DANGLING_THINK_TAG_RE = re.compile(r"<think>.*", re.DOTALL | re.IGNORECASE)


def strip_think_tags(text: str) -> str:
    """Some models (e.g. reasoning-tuned Qwen variants) prepend a
    <think>...</think> reasoning block to their response. Strip it out
    so only the actual answer reaches the user/caller.
    """
    if not text:
        return text
    cleaned = THINK_TAG_RE.sub("", text)
    # Handle a truncated/never-closed <think> block (e.g. hit max_completion_tokens
    # mid-thought) by dropping everything from the opening tag onward.
    cleaned = DANGLING_THINK_TAG_RE.sub("", cleaned)
    return cleaned.strip()


def cache_image_url(filepath: str, cdn_url: str):
    """Tell the node server which permanent ImageKit url a local
    saved_name maps to, BEFORE the local file gets deleted. This is
    what lets old chat bubbles pointing at /data_files/<saved_name>
    keep resolving (via a 302 redirect) instead of 404ing once the
    local copy is gone.
    """
    saved_name = os.path.basename(filepath)
    try:
        requests.post(
            f"{HINA_SERVER}/internal/cache_image",
            json={"saved_name": saved_name, "imagekit_url": cdn_url},
            timeout=5,
        )
    except Exception as e:
        # Non-fatal: worst case the old local link 404s instead of
        # redirecting. Don't let a caching hiccup break image replies.
        print(f"[image2text] failed to cache image url for {saved_name}: {e}")


def link_cam_image(filepath: str) -> str:
    # Unique id PER UPLOAD, not per process. The old code generated
    # this once at import time, so any batch of images processed in
    # the same run all got uploaded to ImageKit under the exact same
    # filename, overwriting each other.
    file_id = uuid.uuid4()

    # Open the file in binary read mode to satisfy ImageKit's payload requirements
    with open(filepath, "rb") as img_file:
        res = imagekit.files.upload(
            file=img_file,
            file_name=f"{file_id}",
            folder="/hina-ai",
        )

    # Cache saved_name -> permanent CDN url BEFORE removing the local
    # copy, so nothing that already links to /data_files/<name> breaks.
    cache_image_url(filepath, res.url)

    # The file is automatically closed when exiting the 'with' block,
    # making it safe to delete the screenshot immediately after.
    os.remove(filepath)
    return res.url


def get_img_res(file_loc: str):
    link = link_cam_image(filepath=file_loc)

    def build_kwargs():
        return dict(
            model="qwen/qwen3.6-27b",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "describe this image in pointers describe how it looks what it about in pointers summary"
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"{link}"
                            }
                        }
                    ]
                }
            ],
            temperature=1,
            max_completion_tokens=2048,  # was 1024 -- reasoning trace was eating the whole budget
            top_p=1,
            stream=False,
            stop=None,
        )

    completion = call_groq_with_fallback(build_kwargs)
    choice = completion.choices[0]
    raw_content = choice.message.content
    finish_reason = getattr(choice, "finish_reason", None)

    print(f"[image2text] finish_reason={finish_reason} raw_len={len(raw_content or '')}")
    print(f"[image2text] raw content: {raw_content!r}")

    res_o = strip_think_tags(raw_content)

    if not res_o:
        # Model burned its whole token budget inside <think>...</think> and
        # never got to an actual answer (common with reasoning models when
        # max_completion_tokens is too low), or returned nothing at all.
        # Don't silently pass "" downstream -- that's what was producing
        # "I don't see an image" replies with zero indication of why.
        print(f"[image2text] WARNING: empty result after stripping think tags "
              f"(finish_reason={finish_reason}). Falling back to raw content.")
        res_o = (raw_content or "").strip() or "[vision model returned no usable description]"
    return res_o


if __name__ == "__main__":
    print(get_img_res(file_loc="/home/sourav/Pictures/Screenshots/Screenshot From 2026-07-04 23-05-44.png"))