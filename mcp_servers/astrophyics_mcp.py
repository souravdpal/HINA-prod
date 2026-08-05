import os
import sys
import re
import datetime

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)
core_dir = os.path.join(parent_dir, "core")
if core_dir not in sys.path:
    sys.path.insert(0, core_dir)


from core import hina_sdk
import requests
from bs4 import BeautifulSoup
from mcp.server.fastmcp import FastMCP
from core import hina_direct

mcp = FastMCP("Web_search mcp")

# NASA's public demo key works but is rate limited (30/hr, 50/day).
# Set env var NASA_API_KEY for a personal key with much higher limits.
NASA_API_KEY = os.environ.get("NASA_API_KEY", "DEMO_KEY")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; AstroBot/1.0; +https://example.com/bot)"
}

# ---------------------------------------------------------------------------
# app.js color palette (see COLOR_PALETTE in app.js). hina_sdk's `color`
# kwarg is looked up against this exact table on the frontend, so every
# call below uses one of these names instead of made-up strings like
# "reasoning..." or "danger" (which don't match any palette entry and
# would just fall through to the agent_name hash fallback color).
#   idle, think, reason, tool, search, success, warn, error, voice, creative
# We're a retrieval/tool-calling agent, so: "search" while working,
# "success" when done with data, "error" on failure.
# ---------------------------------------------------------------------------
COLOR_WORKING = "search"
COLOR_SUCCESS = "success"
COLOR_ERROR = "error"

AGENT_NAME = "Astro"
AGENT_ICON = "a-solid fa-user-astronaut"


# ---------------------------------------------------------------------------
# Own lightweight scraper module (no heavy generic web-search/gemini deps)
# Pulls directly from NASA / ESA / ISRO RSS + news pages and keyword-filters.
# ---------------------------------------------------------------------------

def _parse_rss(url, source_name, timeout=8):
    """Fetch and parse a standard RSS/Atom feed into simple dicts."""
    items = []
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.content, "xml")

        entries = soup.find_all("item") or soup.find_all("entry")
        for entry in entries:
            title_tag = entry.find("title")
            link_tag = entry.find("link")
            desc_tag = entry.find("description") or entry.find("summary")
            date_tag = entry.find("pubDate") or entry.find("published") or entry.find("updated")

            title = title_tag.get_text(strip=True) if title_tag else None

            # Atom <link> uses href attribute, RSS <link> uses text
            link = None
            if link_tag:
                link = link_tag.get("href") or link_tag.get_text(strip=True)

            description = desc_tag.get_text(strip=True) if desc_tag else ""
            description = re.sub("<[^<]+?>", "", description)  # strip stray HTML

            items.append({
                "source": source_name,
                "title": title,
                "link": link,
                "description": description[:400],
                "date": date_tag.get_text(strip=True) if date_tag else None,
            })
    except Exception:
        pass
    return items


def _scrape_isro_press_releases(timeout=8):
    """ISRO has no public RSS feed, so scrape its press release listing page directly."""
    items = []
    try:
        url = "https://www.isro.gov.in/press-release.html"
        resp = requests.get(url, headers=HEADERS, timeout=timeout)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.content, "html.parser")

        # ISRO's press release list is rendered as anchor tags within list/table rows.
        for a in soup.select("a[href]"):
            text = a.get_text(strip=True)
            href = a.get("href")
            if not text or not href:
                continue
            if len(text) < 15:
                continue
            if "press-release" in href or "update" in href.lower():
                full_link = href if href.startswith("http") else f"https://www.isro.gov.in/{href.lstrip('/')}"
                items.append({
                    "source": "ISRO",
                    "title": text,
                    "link": full_link,
                    "description": "",
                    "date": None,
                })
    except Exception:
        pass
    return items[:20]


def _keyword_filter(items, query, max_results):
    """Simple relevance filter/sort: keep items whose title/description mention
    any query keyword, ranked by number of keyword hits. Falls back to the
    unfiltered (most recent) items if nothing matches, so results are never empty
    just because of stricter wording."""
    if not query:
        return items[:max_results]

    keywords = [w.lower() for w in re.findall(r"\w+", query) if len(w) > 2]
    if not keywords:
        return items[:max_results]

    scored = []
    for item in items:
        haystack = f"{item.get('title', '')} {item.get('description', '')}".lower()
        score = sum(1 for kw in keywords if kw in haystack)
        if score > 0:
            scored.append((score, item))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    matched = [item for _, item in scored[:max_results]]

    if matched:
        return matched
    return items[:max_results]


def _fetch_spaceflight_news(query, max_results=10, timeout=8):
    """
    Fallback/supplement source: Spaceflight News API (api.spaceflightnewsapi.net)
    is a free, no-key, purpose-built aggregator of official press releases from
    NASA, ESA, ISRO, Roscosmos, SpaceX, etc. Used alongside the direct
    NASA/ESA/ISRO pulls above, since those can be blocked, rate-limited, or
    change their HTML/RSS structure without notice — this keeps results
    flowing even if one of the direct scrapes fails.
    """
    items = []
    try:
        params = {"limit": max_results, "search": query} if query else {"limit": max_results}
        resp = requests.get(
            "https://api.spaceflightnewsapi.net/v4/articles/",
            params=params, headers=HEADERS, timeout=timeout
        )
        resp.raise_for_status()
        data = resp.json()
        for a in data.get("results", []):
            items.append({
                "source": (a.get("news_site") or "Spaceflight News"),
                "title": a.get("title"),
                "link": a.get("url"),
                "description": (a.get("summary") or "")[:400],
                "date": a.get("published_at"),
            })
    except Exception as e:
        print(f"[astro_mcp] spaceflight_news fetch failed: {e}")
    return items


def scrape_space_news(query, max_results=8):
    """
    Pull recent space news/articles directly from NASA, ESA, and ISRO sources
    (RSS feeds + a light HTML scrape for ISRO), plus the Spaceflight News API
    as a resilient fallback, then keyword-filter against the query.
    """
    all_items = []

    nasa_items = _parse_rss("https://www.nasa.gov/news-release/feed/", "NASA")
    esa_items = _parse_rss("https://www.esa.int/rssfeed/Our_Activities/Space_News", "ESA")
    isro_items = _scrape_isro_press_releases()

    print(f"[astro_mcp] NASA={len(nasa_items)} ESA={len(esa_items)} ISRO={len(isro_items)}")

    all_items += nasa_items
    all_items += esa_items
    all_items += isro_items

    sfn_items = _fetch_spaceflight_news(query, max_results=max_results * 2)
    print(f"[astro_mcp] SpaceflightNewsAPI={len(sfn_items)}")
    all_items += sfn_items

    return _keyword_filter(all_items, query, max_results)


# ---------------------------------------------------------------------------
# small helpers to keep every tool's frontend payload consistent
# ---------------------------------------------------------------------------

def _notify_working(state_msg):
    hina_sdk.send_state(
        color=COLOR_WORKING,
        agent_name=AGENT_NAME,
        state=state_msg,
        icon=AGENT_ICON,
        done=False
    )


def _notify_done(data, state_msg, ui_type="astro"):
    hina_sdk.send_ui_json(
        data=data,
        color=COLOR_SUCCESS,
        agent_name=AGENT_NAME,
        state=state_msg,
        icon=AGENT_ICON,
        done=True,
        ui_type=ui_type,
    )


def _notify_error(state_msg, ui_type="astro"):
    hina_sdk.send_ui_json(
        data=[],
        color=COLOR_ERROR,
        agent_name=AGENT_NAME,
        state=state_msg,
        icon=AGENT_ICON,
        done=True,
        ui_type=ui_type,
    )


# ---------------------------------------------------------------------------
# NASA media (images/videos) search
# Shape: flat list of {title, media_url, media_type} — this is exactly the
# "standard media array" app.js's tryDetectMediaArray()/buildMediaGridCard()
# looks for, so with ui_type="astro" it renders as a big image/video grid
# inside the Astrophysics card shell.
# ---------------------------------------------------------------------------
@mcp.tool()
def get_nasa_media_links(query, max_results=10):

    media_list = []
    _notify_working("finding media...")

    search_url = f"https://images-api.nasa.gov/search?q={query}&media_type=image,video"

    try:
        search_response = requests.get(search_url, headers=HEADERS, timeout=10)
        search_response.raise_for_status()
        items = search_response.json().get("collection", {}).get("items", [])

        for item in items[:max_results]:
            data_fields = item.get("data", [{}])[0]
            title = data_fields.get("title", "No Title")
            item_media_type = data_fields.get("media_type")
            asset_manifest_url = item.get("href")

            if asset_manifest_url and item_media_type:
                asset_response = requests.get(asset_manifest_url, headers=HEADERS, timeout=10)
                if asset_response.status_code == 200:
                    asset_links = asset_response.json()

                    filtered_links = []
                    if item_media_type == "image":
                        filtered_links = [
                            link for link in asset_links
                            if (link.lower().endswith('.jpg') or link.lower().endswith('.jpeg'))
                            and not link.endswith('~thumb.jpg')
                        ]
                    elif item_media_type == "video":
                        filtered_links = [
                            link for link in asset_links
                            if link.lower().endswith('.mp4') or link.lower().endswith('.mov')
                        ]

                    if filtered_links:
                        media_list.append({
                            "title": title,
                            "media_url": filtered_links[0],
                            "media_type": item_media_type
                        })

        _notify_done(media_list, "found media...")
        return media_list

    except Exception as e:
        print(f"[astro_mcp] NASA media search failed: {e}")
        _notify_error("failed to fetch media")
        return []


# ---------------------------------------------------------------------------
# Astronomy Picture of the Day
# Shape: single object {title, summary, date, media_type, url, hd_url}.
# app.js's buildAstroCardRest() specifically looks for `summary`/`text`
# fields on an object (not `explanation`), so that key is renamed here.
# ---------------------------------------------------------------------------
@mcp.tool()
def get_astronomy_picture_of_the_day(date=None):
    """
    Fetch NASA's Astronomy Picture of the Day (APOD).
    date: optional 'YYYY-MM-DD' string. Defaults to today.
    """
    _notify_working("fetching today's astronomy picture...")

    params = {"api_key": NASA_API_KEY}
    if date:
        params["date"] = date

    try:
        response = requests.get(
            "https://api.nasa.gov/planetary/apod",
            params=params, headers=HEADERS, timeout=10
        )
        response.raise_for_status()
        data = response.json()

        result = {
            "title": data.get("title"),
            "summary": data.get("explanation"),
            "date": data.get("date"),
            "media_type": data.get("media_type"),
            "url": data.get("url"),
            "hd_url": data.get("hdurl"),
        }

        _notify_done(result, "found astronomy picture...")
        return result

    except Exception as e:
        print(f"[astro_mcp] APOD fetch failed: {e}")
        _notify_error("failed to fetch APOD")
        return {}


# ---------------------------------------------------------------------------
# Mars rover photos
# Shape: flat list of {title, media_url, media_type: "image"} — mapped from
# the API's img_src field so it's picked up by tryDetectMediaArray() the
# same way get_nasa_media_links()'s output is.
# ---------------------------------------------------------------------------
@mcp.tool()
def get_mars_rover_photos(rover="curiosity", sol=1000, camera=None, max_results=10):
    """
    Fetch Mars rover photos.
    rover: 'curiosity', 'opportunity', 'spirit', or 'perseverance'
    sol: Martian day number since landing (an alternative to earth_date)
    camera: optional camera abbreviation e.g. 'FHAZ', 'NAVCAM', 'MAST'
    """
    _notify_working(f"searching {rover} rover photos...")

    params = {"sol": sol, "api_key": NASA_API_KEY}
    if camera:
        params["camera"] = camera

    url = f"https://api.nasa.gov/mars-photos/api/v1/rovers/{rover}/photos"

    try:
        response = requests.get(url, params=params, headers=HEADERS, timeout=10)
        response.raise_for_status()
        photos = response.json().get("photos", [])[:max_results]

        result = [
            {
                "title": f"{p.get('rover', {}).get('name', rover)} \u00b7 {p.get('camera', {}).get('full_name', '')} \u00b7 {p.get('earth_date', '')}",
                "media_url": p.get("img_src"),
                "media_type": "image",
            }
            for p in photos
            if p.get("img_src")
        ]

        _notify_done(result, "found rover photos...")
        return result

    except Exception as e:
        print(f"[astro_mcp] Mars rover fetch failed: {e}")
        _notify_error("failed to fetch rover photos")
        return []


# ---------------------------------------------------------------------------
# Near-Earth Objects / Asteroids
# Shape: plain list of objects, no url/media fields, so it's left with the
# default (generic) card — app.js renders an array of objects as stacked
# key/value mini-cards, which fits this data well.
# ---------------------------------------------------------------------------
@mcp.tool()
def get_near_earth_objects(start_date=None, end_date=None):
    """
    Fetch near-Earth asteroid data for a date range (max 7 days).
    Dates in 'YYYY-MM-DD'. Defaults to today through today.
    """
    _notify_working("scanning for near-earth objects...")

    today = datetime.date.today().isoformat()
    params = {
        "start_date": start_date or today,
        "end_date": end_date or start_date or today,
        "api_key": NASA_API_KEY,
    }

    try:
        response = requests.get(
            "https://api.nasa.gov/neo/rest/v1/feed",
            params=params, headers=HEADERS, timeout=10
        )
        response.raise_for_status()
        data = response.json()

        neo_list = []
        for date_key, objects in data.get("near_earth_objects", {}).items():
            for obj in objects:
                diameter = obj.get("estimated_diameter", {}).get("meters", {})
                close_approach = (obj.get("close_approach_data") or [{}])[0]
                neo_list.append({
                    "name": obj.get("name"),
                    "date": date_key,
                    "is_potentially_hazardous": obj.get("is_potentially_hazardous_asteroid"),
                    "estimated_diameter_min_m": diameter.get("estimated_diameter_min"),
                    "estimated_diameter_max_m": diameter.get("estimated_diameter_max"),
                    "miss_distance_km": close_approach.get("miss_distance", {}).get("kilometers"),
                    "relative_velocity_kph": close_approach.get("relative_velocity", {}).get("kilometers_per_hour"),
                })

        # No ui_type -> app.js auto-detects as "generic" and renders a clean
        # key/value card list instead of trying (and failing) to force this
        # array through the astro/media-grid renderer.
        _notify_done(neo_list, "found near-earth objects...", ui_type=None)
        return neo_list

    except Exception as e:
        print(f"[astro_mcp] NEO fetch failed: {e}")
        _notify_error("failed to fetch near-earth objects", ui_type=None)
        return []


# ---------------------------------------------------------------------------
# Current ISS location
# Shape: single flat object -> generic key/value card.
# ---------------------------------------------------------------------------
@mcp.tool()
def get_iss_location():
    """
    Fetch the current real-time latitude/longitude of the International Space Station.
    """
    _notify_working("locating the ISS...")

    try:
        response = requests.get("http://api.open-notify.org/iss-now.json", headers=HEADERS, timeout=10)
        response.raise_for_status()
        data = response.json()

        result = {
            "latitude": data.get("iss_position", {}).get("latitude"),
            "longitude": data.get("iss_position", {}).get("longitude"),
            "timestamp": data.get("timestamp"),
        }

        _notify_done(result, "found ISS location...", ui_type=None)
        return result

    except Exception as e:
        print(f"[astro_mcp] ISS location fetch failed: {e}")
        _notify_error("failed to fetch ISS location", ui_type=None)
        return {}


# ---------------------------------------------------------------------------
# People currently in space
# Shape: {number, people: [{name, craft}, ...]} -> generic card, nested
# array of objects renders as its own stacked mini-cards automatically.
# ---------------------------------------------------------------------------
@mcp.tool()
def get_people_in_space():
    """
    Fetch the list of astronauts currently in space, and which craft they're aboard.
    """
    _notify_working("counting people in space...")

    try:
        response = requests.get("http://api.open-notify.org/astros.json", headers=HEADERS, timeout=10)
        response.raise_for_status()
        data = response.json()

        result = {
            "number": data.get("number"),
            "people": data.get("people", []),
        }

        _notify_done(result, "found people in space...", ui_type=None)
        return result

    except Exception as e:
        print(f"[astro_mcp] astronauts fetch failed: {e}")
        _notify_error("failed to fetch astronauts", ui_type=None)
        return {}


# ---------------------------------------------------------------------------
# Space news search — own NASA/ESA/ISRO scraper, no third-party search engine.
# Shape matches app.js's buildSearchResultsCard(): {query, organic_results:
# [{title, link}], ai_links: [], image_links: []}. ui_type="search" (or the
# organic_results array alone) makes it render as the familiar "Web results"
# card with clickable source cards instead of the generic key/value view.
# ---------------------------------------------------------------------------
@mcp.tool()
def search_space_info(query, max_results=8):
    """
    Search recent space news/updates directly from NASA, ESA, and ISRO sources
    (own lightweight RSS/HTML scraper defined in this file — no external search
    engine or AI summarizer is used). Good for questions like "latest Chandrayaan
    update" or "recent NASA Artemis news".
    """
    _notify_working("scraping NASA / ESA / ISRO for news...")

    try:
        raw_results = scrape_space_news(query, max_results=max_results)

        payload = {
            "query": query,
            "organic_results": [
                {"title": r.get("title"), "link": r.get("link"), "source": r.get("source")}
                for r in raw_results
                if r.get("link")
            ],
            "ai_links": [],
            "image_links": [],
        }

        print(f"[astro_mcp] search_space_info returning {len(raw_results)} results for query={query!r}")

        _notify_done(payload, "found space news...", ui_type="search")
        return raw_results

    except Exception as e:
        print(f"[astro_mcp] search_space_info failed: {e}")
        _notify_error("failed to fetch space news", ui_type="search")
        return []


if __name__ == "__main__":
    mcp.run()