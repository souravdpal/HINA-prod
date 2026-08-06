# yt_helper.py
import sys
import traceback
from youtube_transcript_api import YouTubeTranscriptApi, NoTranscriptFound, TranscriptsDisabled
import yt_dlp

FALLBACK_LANGUAGES = ["hi", "en", "en-IN", "fr", "es", "de", "ru"]


def get_yt_id(query: str, lim: int = 5) -> list[dict]:
    """Search YouTube for a query and return up to `lim` results.

    Uses yt-dlp's search extractor instead of youtubesearchpython.
    youtubesearchpython's *sync* VideosSearch spins up its own asyncio
    event loop internally, which conflicts and fails immediately when
    called from code that's already running inside an event loop (e.g.
    an MCP tool served by FastMCP's async server) — regardless of the
    query. yt-dlp does its own request handling without that conflict,
    and is actively maintained against YouTube's page/API changes.

    NOTE: this logs loudly on both failure paths (exception, and
    "succeeded but returned nothing") on purpose — the previous silent
    `except: return []` is exactly what made the last bug invisible.
    Once this is confirmed working, the logging can be dialed back.
    """
    ydl_opts = {
        "quiet": True,
        # no_warnings intentionally left False — a warning (e.g. bot
        # check / consent wall) is exactly the kind of thing that was
        # getting hidden before and turning into a silent empty result.
        "no_warnings": False,
        "extract_flat": True,   # don't resolve full formats, just metadata
        "skip_download": True,
        # noplaylist removed: a ytsearch query IS a "playlist" of
        # results to yt-dlp, so forcing noplaylist could suppress the
        # result set instead of being the no-op it would be for a
        # normal single-video URL.
    }
    # Build the exact same "ytsearchN:query" form the yt-dlp CLI uses,
    # instead of relying on the `default_search` option — that option
    # is applied by yt-dlp's own CLI arg parser, not consistently by
    # the YoutubeDL().extract_info() API, so calling extract_info with
    # a bare query silently found nothing (no exception, no results —
    # nothing ever actually got searched).
    search_url = f"ytsearch{lim}:{query}"
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(search_url, download=False)
    except Exception:
        print(
            f"[yt_helper] search RAISED for {search_url!r}:\n{traceback.format_exc()}",
            file=sys.stderr,
        )
        return []

    if not info:
        print(f"[yt_helper] search for {search_url!r} returned no info object at all (info={info!r})", file=sys.stderr)
        return []

    entries = info.get("entries")
    if entries is None:
        # Not a search/playlist result shape at all — dump the keys we
        # did get so we can see what yt-dlp actually gave back.
        print(
            f"[yt_helper] search for {search_url!r} succeeded but had no 'entries' key. "
            f"Top-level keys: {list(info.keys())}",
            file=sys.stderr,
        )
        return []

    entries = list(entries)  # force any generator to materialize
    videos = []
    for entry in entries:
        if not entry:
            continue
        vid = entry.get("id")
        title = entry.get("title")
        if not vid or not title:
            continue
        videos.append({"id": vid, "title": title})

    if not videos:
        print(
            f"[yt_helper] search for {search_url!r} returned {len(entries)} raw entries "
            f"but none had usable id+title. Sample entry: {entries[0] if entries else None!r}",
            file=sys.stderr,
        )
    return videos


def _broaden_query(query: str) -> str | None:
    """Drops the last word to make the query less specific. Returns None
    once there's nothing left to drop, so recursion has a hard floor."""
    words = query.strip().split()
    if len(words) <= 1:
        return None
    return " ".join(words[:-1])


def play_vedio(query: str, _depth: int = 0, _max_depth: int = 3) -> list:
    """Search for a video and return its title and playable link.

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