from youtube_transcript_api import YouTubeTranscriptApi, NoTranscriptFound, TranscriptsDisabled
from youtubesearchpython import VideosSearch
import subprocess as sub
# Languages to look for if English isn't available
FALLBACK_LANGUAGES = ["hi", "en", "en-IN", "fr", "es", "de", "ru"]

def get_yt_id(query: str, lim: int = 1) -> list[dict]:
    """Search YouTube for a query and return up to `lim` results."""
    search = VideosSearch(query, limit=lim)
    results = search.result()

    videos = []
    for video in results.get("result", []):
        videos.append({
            "id": video["id"], 
            "title": video["title"]
        })

    return videos


def play_vedio(query: str) -> list:
    """Search for a video and return its title and playable link for mpv."""
    videos = get_yt_id(query)

    if not videos:
        raise ValueError(f"No video found for query: {query!r}")
        
    video_id = videos[0]["id"]
    video_title = videos[0]["title"]
    
    # Fixed the missing 'f' prefix here so the ID actually injects into the URL
    video_link = f"https://www.youtube.com/watch?v={video_id}"

    
    return [video_title, video_link]


def get_transcript(query: str) -> str:
    """
    Search for a video, fetch its transcript, and translate to English natively 
    using YouTube's built-in translation API (No external ML models required).
    """
    videos = get_yt_id(query)

    if not videos:
        return "No video found for this query."

    video_id = videos[0]["id"]
    
    try:
        # Get the list of all available transcripts for the video
        transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
        
        # Try to find a transcript in our preferred fallback languages
        transcript = transcript_list.find_transcript(FALLBACK_LANGUAGES)
        
        # NATIVE TRANSLATION: If the found language isn't English, tell YouTube to translate it
        if transcript.language_code not in ["en", "en-IN"]:
            transcript = transcript.translate('en')
            
        fetched = transcript.fetch()
        
        # Combine the text dictionary into a single clean string
        clean_text = " ".join(seg["text"] for seg in fetched)
        return clean_text

    except (NoTranscriptFound, TranscriptsDisabled) as e:
        return f"Transcript unavailable for this video: {str(e)}"
    except Exception as e:
        return f"Error fetching transcript: {str(e)}"