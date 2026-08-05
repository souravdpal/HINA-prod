# yt_helper.py
from youtube_transcript_api import YouTubeTranscriptApi, NoTranscriptFound, TranscriptsDisabled
from youtubesearchpython import VideosSearch
import subprocess as sub

FALLBACK_LANGUAGES = ["hi", "en", "en-IN", "fr", "es", "de", "ru"]


def get_yt_id(query: str, lim: int = 5) -> list[dict]:
    """Search YouTube for a query and return up to `lim` results.

    Requests more than 1 result on purpose: youtubesearchpython can throw
    mid-parse on certain result types (livestreams/premieres with
    duration=None trigger a str+None concat bug inside the library
    itself). A wider `lim` plus per-item filtering means one bad result
    doesn't take out the whole search.
    """
    try:
        search = VideosSearch(query, limit=lim)
        results = search.result()
    except TypeError:
        # The library's own internal formatting choked on a bad result
        # item (e.g. duration=None). Nothing usable survives this —
        # treat it as "no results" rather than letting it crash the tool.
        return []
    except Exception:
        return []

    videos = []
    for video in results.get("result", []):
        vid = video.get("id")
        title = video.get("title")
        if not vid or not title:
            continue
        videos.append({"id": vid, "title": title})
    return videos


def _broaden_query(query: str) -> str | None:
    """Drops the last word to make the query less specific. Returns None
    once there's nothing left to drop, so recursion has a hard floor."""
    words = query.strip().split()
    if len(words) <= 1:
        return None
    return " ".join(words[:-1])


def play_vedio(query: str, _depth: int = 0, _max_depth: int = 3) -> list:
    """Search for a video and return its title and playable link for mpv.

    Recursively retries with a broadened query (last word dropped each
    time) if the search comes back empty, up to `_max_depth` attempts,
    instead of failing on the very first miss.
    """
    videos = get_yt_id(query, lim=5)

    if not videos:
        broader = _broaden_query(query)
        if broader and _depth < _max_depth:
            return play_vedio(broader, _depth=_depth + 1, _max_depth=_max_depth)
        raise ValueError(
            f"No playable video found for query: {query!r} "
            f"(tried {_depth + 1} query variant(s))"
        )

    video_id = videos[0]["id"]
    video_title = videos[0]["title"]
    video_link = f"https://www.youtube.com/watch?v={video_id}"

    return [video_title, video_link]


def get_transcript(query: str) -> str:
    videos = get_yt_id(query)

    if not videos:
        return "No video found for this query."

    video_id = videos[0]["id"]

    try:
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
        transcript = transcript_list.find_transcript(FALLBACK_LANGUAGES)
        if transcript.language_code not in ["en", "en-IN"]:
            transcript = transcript.translate('en')
        fetched = transcript.fetch()
        clean_text = " ".join(seg["text"] for seg in fetched)
        return clean_text
    except (NoTranscriptFound, TranscriptsDisabled) as e:
        return f"Transcript unavailable for this video: {str(e)}"
    except Exception as e:
        return f"Error fetching transcript: {str(e)}"