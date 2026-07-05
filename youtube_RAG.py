"""
youtube_RAG.py
Utilities for the HINA agent: search YouTube, play a video via mpv,
and summarize a video's transcript.
"""

from __future__ import annotations

import asyncio
import inspect
import subprocess as sub

from youtube_transcript_api import (
    YouTubeTranscriptApi,
    NoTranscriptFound,
    TranscriptsDisabled,
)
from dotenv import load_dotenv
from youtubesearchpython import VideosSearch
from googletrans import Translator  # pip install googletrans==4.0.0-rc1

from summarizer import model_res_sum
from open_promp import raw_maker
from hina_brain import model_res

load_dotenv()

# Shared prompt used to turn a rambling user request into a clean search query.
SEARCH_QUERY_PROMPT = """Act as a search query extraction engine. Your task is to analyze user input and extract ONLY the core intent or technical subject matter required to perform an effective search.
Rules:
1. Strip away all conversational filler, emotional context, personal narratives, and fluff.
2. Output ONLY the concise, search-ready query (usually 2-5 keywords).
3. Do not provide explanations, conversational replies, or meta-commentary.
4. If the user asks for resources, focus on the subject (e.g., "Python tutorials").
Examples:
- Input: "I am bad in python, idk why but I used cpp and now I forgot the syntax. Can you show me a lecture on Python?"
  Output: Python programming syntax lectures
- Input: "My Dell Latitude is running Arch Linux and I'm having trouble with Nginx configuration. Can you help me fix the gateway errors?"
  Output: Arch Linux Nginx configuration gateway error fix
- Input: "I've been feeling overwhelmed by my physics studies lately, but I really need to understand quantum entanglement."
  Output: quantum entanglement explanation
User Input: [INSERT USER INPUT HERE]
Search Query:"""

FALLBACK_LANGUAGES = ["hi", "en", "en-IN", "fr", "es"]


def get_yt_id(query: str, lim: int = 1) -> list[dict]:
    """
    Search YouTube for `query` and return up to `lim` results.

    Returns:
        list[dict]: [{"id": str, "title": str}, ...] (empty list if nothing found).
    """
    search = VideosSearch(query, limit=lim)
    results = search.result()

    videos = []
    for video in results.get("result", []):
        video_id = video["id"]
        video_title = video["title"]
        print(f"Found: {video_title} (ID: {video_id})")
        videos.append({"id": video_id, "title": video_title})

    return videos


def _extract_search_query(user_text: str) -> str:
    """Run raw user text through the LLM extractor to get a clean search query."""
    return raw_maker(contex_prompt=SEARCH_QUERY_PROMPT, data=user_text)


def play_vedio(q: str) -> None:
    """Search for a video matching `q`, play it in mpv, and notify HINA."""
    query = _extract_search_query(q)
    videos = get_yt_id(query)

    if not videos:
        print(f"No video found for query: {query!r}")
        model_res(
            up=q,
            sec_data="HINA agent response: I couldn't find a matching video to play.",
        )
        return

    video_id = videos[0]["id"]
    video_title = videos[0]["title"]

    sub.Popen(["mpv", f"https://www.youtube.com/watch?v={video_id}"])

    model_res(
        up=q,
        sec_data=f"HINA agent response: You just played a video for sourav — {video_title}",
    )


def _translate_to_english(text: str) -> str:
    """
    Translate `text` to English using googletrans.

    googletrans==4.0.0-rc1 (and some other versions) made `.translate()`
    a coroutine internally, while older/newer versions return a plain
    result. Handle both so this doesn't break across environments.
    """
    translator = Translator()
    result = translator.translate(text, dest="en")

    if inspect.iscoroutine(result):
        result = asyncio.run(result)

    return result.text


def _segment_text(segment) -> str:
    """Handle both dict-style and attribute-style transcript segments
    (different youtube_transcript_api versions return different objects)."""
    if isinstance(segment, dict):
        return segment["text"]
    return segment.text


def _fetch_transcript_text(video_id: str) -> str | None:
    """
    Try to fetch an English transcript first; fall back to any available
    language and translate it to English if necessary.

    Supports both:
      - youtube_transcript_api >= 1.0 (instance-based: YouTubeTranscriptApi().fetch/.list)
      - youtube_transcript_api < 1.0 (classmethod-based: .get_transcript/.list_transcripts)

    Returns the transcript text, or None if nothing could be fetched.
    """
    uses_new_api = hasattr(YouTubeTranscriptApi, "fetch") and not hasattr(
        YouTubeTranscriptApi, "get_transcript"
    )

    # --- Try English first ---
    try:
        if uses_new_api:
            ytt_api = YouTubeTranscriptApi()
            fetched = ytt_api.fetch(video_id, languages=["en", "en-IN"])
            return " ".join(_segment_text(seg) for seg in fetched)
        else:
            transcript_list = YouTubeTranscriptApi.get_transcript(
                video_id, languages=["en", "en-IN"]
            )
            return " ".join(_segment_text(seg) for seg in transcript_list)
    except (NoTranscriptFound, TranscriptsDisabled):
        pass
    except Exception as e:
        print(f"Unexpected error fetching English transcript: {e}")

    # --- Fall back to any available language, translate if needed ---
    try:
        if uses_new_api:
            ytt_api = YouTubeTranscriptApi()
            transcript_list = ytt_api.list(video_id)
        else:
            transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)

        transcript = transcript_list.find_transcript(FALLBACK_LANGUAGES)
        fetched = transcript.fetch()
        raw_text = " ".join(_segment_text(seg) for seg in fetched)

        if transcript.language_code != "en":
            print(f"Translating {transcript.language_code} to English...")
            return _translate_to_english(raw_text)
        return raw_text
    except Exception as e:
        print(f"Failed to fetch/translate transcript: {e}")
        return None


def yt_subs(q: str) -> None:
    """Search for a video matching `q`, summarize its transcript, and notify HINA."""
    query = _extract_search_query(q)
    videos = get_yt_id(query)

    if not videos:
        print(f"No video found for query: {query!r}")
        model_res(
            up=q,
            sec_data="HINA agent response: I couldn't find a matching video to summarize.",
        )
        return

    video_id = videos[0]["id"]

    clean_text = _fetch_transcript_text(video_id)
    if not clean_text:
        model_res(
            up=q,
            sec_data="HINA agent response: I found a video but couldn't get its transcript.",
        )
        return

    summ_data = model_res_sum(
        char="sourav query for youtube video: " + q,
        special="youtube agents ran here is summary of video: " + clean_text,
    )

    model_res(up=q, sec_data=str(summ_data))