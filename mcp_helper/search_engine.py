"""
Lightweight, browser-free web search engine.

Replaces the old Selenium/Chrome-driven implementation. That approach spun
up a real headless Chromium process per search, which on memory-constrained
machines (shared with a desktop browser, IDEs, etc.) crashed constantly with
"connection refused" / "connection aborted" errors as Chrome got killed
under memory pressure.

This version does everything with plain HTTP requests + BeautifulSoup:
  - DuckDuckGo HTML results   (https://html.duckduckgo.com/html/)
  - Google HTML results       (https://www.google.com/search)   [best-effort]
  - Wikipedia summary + image (REST API, very reliable, great overview text)
  - Bing Images               (https://www.bing.com/images/search)

No browser, no chromedriver, no GPU/render process, no multi-hundred-MB
memory footprint per call -- just a few small HTTP requests. This also
means it's much faster (no page rendering / JS execution wait).

Public entry point (kept 100% compatible with the previous version so
web_search_mcp.py doesn't need any changes):

    unified_search(query, mode="fast" | "deep") -> {
        "query": str,
        "ai_overview_text": str | None,
        "ai_links": [str, ...],
        "image_links": [str, ...],
        "organic_results": [{"title", "link", "snippet", "engine"}, ...],
        "engines_used": [str, ...],
        "status": "success" | "failed",
        "reason": str,
    }
"""

import json
import logging
import random
import re
import time
from urllib.parse import urlparse, parse_qs, unquote

import requests
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format="[search_engine] %(message)s")
logger = logging.getLogger("search_engine")

# ---------------------------------------------------------------------------
# HTTP plumbing
# ---------------------------------------------------------------------------

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
]

_REQUEST_TIMEOUT = 10


def _headers(extra=None):
    h = {
        "User-Agent": random.choice(_USER_AGENTS),
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    if extra:
        h.update(extra)
    return h


def _get(url, params=None, headers=None, cookies=None, retries=2, timeout=_REQUEST_TIMEOUT):
    """GET with small retry/backoff for transient network errors."""
    last_exc = None
    for attempt in range(retries + 1):
        try:
            resp = requests.get(
                url, params=params, headers=_headers(headers), cookies=cookies,
                timeout=timeout,
            )
            resp.raise_for_status()
            return resp
        except requests.exceptions.RequestException as e:
            last_exc = e
            logger.warning(
                "GET %s failed (attempt %d/%d): %s",
                url, attempt + 1, retries + 1, str(e)[:150],
            )
            time.sleep(0.4 * (attempt + 1))
    raise last_exc


def human_delay(min_sec=0.15, max_sec=0.5):
    time.sleep(random.uniform(min_sec, max_sec))


def _domain(url):
    try:
        return urlparse(url).netloc.lower()
    except Exception:
        return ""


def _clean_text(s):
    if not s:
        return ""
    return re.sub(r"\s+", " ", s).strip()


# ---------------------------------------------------------------------------
# Shared image filtering
# ---------------------------------------------------------------------------

_BAD_IMG_MARKERS = (".ico", ".svg", "favicon", "avatar", "logo", "asset", "pixel", "sprite", "spacer")


def _is_probably_content_image(src):
    if not src or src.startswith("data:image"):
        return False
    low = src.lower()
    if any(marker in low for marker in _BAD_IMG_MARKERS):
        return False
    return True


def _merge_images(*lists, limit=7):
    merged, seen = [], set()
    for lst in lists:
        for img in lst:
            if img not in seen and _is_probably_content_image(img):
                seen.add(img)
                merged.append(img)
            if len(merged) >= limit:
                return merged
    return merged


def _merge_organic(*lists, limit=30):
    merged, seen = [], set()
    for lst in lists:
        for item in lst:
            link = item.get("link")
            if link and link not in seen:
                seen.add(link)
                merged.append(item)
            if len(merged) >= limit:
                return merged
    return merged


# ---------------------------------------------------------------------------
# DuckDuckGo (HTML-only endpoint -- no JS, very scrape-friendly)
# ---------------------------------------------------------------------------

def ddg_search(query, max_results=10):
    resp = _get("https://html.duckduckgo.com/html/", params={"q": query})
    soup = BeautifulSoup(resp.text, "html.parser")

    organic = []
    for result in soup.select("div.result"):
        a = result.select_one("a.result__a")
        if not a or not a.get("href"):
            continue
        link = a["href"]
        # DDG wraps outbound links: /l/?uddg=<encoded-url>&rut=...
        if "uddg=" in link:
            try:
                qs = parse_qs(urlparse(link).query)
                link = unquote(qs.get("uddg", [link])[0])
            except Exception:
                pass
        title = _clean_text(a.get_text())
        snippet_tag = result.select_one("a.result__snippet") or result.select_one("div.result__snippet")
        snippet = _clean_text(snippet_tag.get_text()) if snippet_tag else ""
        if title and link:
            organic.append({"title": title, "link": link, "snippet": snippet, "engine": "duckduckgo"})
        if len(organic) >= max_results:
            break

    logger.info("DuckDuckGo -> %d organic result(s)", len(organic))
    return organic


# ---------------------------------------------------------------------------
# Google (best-effort HTML scrape; Google changes markup often and may
# occasionally show a consent page or CAPTCHA -- we detect and skip cleanly)
# ---------------------------------------------------------------------------

_GOOGLE_COOKIES = {"CONSENT": "YES+cb.20240101-00-p0.en+FX+410"}


def google_search(query, max_results=10):
    resp = _get(
        "https://www.google.com/search",
        params={"q": query, "num": max_results, "hl": "en", "gl": "us"},
        cookies=_GOOGLE_COOKIES,
    )
    text_lower = resp.text.lower()
    if "unusual traffic" in text_lower or "recaptcha" in text_lower:
        raise RuntimeError("google blocked the request (captcha/rate-limit)")

    soup = BeautifulSoup(resp.text, "html.parser")
    organic = []
    seen_links = set()

    for h3 in soup.find_all("h3"):
        a = h3.find_parent("a")
        if not a or not a.get("href"):
            continue
        link = a["href"]
        if link.startswith("/url?"):
            qs = parse_qs(urlparse(link).query)
            link = qs.get("q", [link])[0]
        if not link.startswith("http") or link in seen_links:
            continue

        title = _clean_text(h3.get_text())
        snippet = ""
        container = a.find_parent(["div"])
        # walk a few ancestors looking for a snippet-shaped block of text
        hops = 0
        node = container
        while node is not None and hops < 4 and not snippet:
            snip_tag = node.find(["div", "span"], class_=re.compile(r"VwiC3b|IsZvec|MUxGbd"))
            if snip_tag:
                snippet = _clean_text(snip_tag.get_text(" "))
                break
            node = node.parent
            hops += 1

        if title and link:
            seen_links.add(link)
            organic.append({"title": title, "link": link, "snippet": snippet, "engine": "google"})
        if len(organic) >= max_results:
            break

    logger.info("Google -> %d organic result(s)", len(organic))
    return organic


# ---------------------------------------------------------------------------
# Wikipedia (REST API -- extremely reliable, great for overview text)
# ---------------------------------------------------------------------------

def wikipedia_lookup(query):
    """Find the best-matching Wikipedia article and return its summary."""
    try:
        search_resp = _get(
            "https://en.wikipedia.org/w/api.php",
            params={
                "action": "query", "list": "search", "srsearch": query,
                "format": "json", "srlimit": 1,
            },
        )
        hits = search_resp.json().get("query", {}).get("search", [])
        if not hits:
            return None
        title = hits[0]["title"]

        summary_resp = _get(
            f"https://en.wikipedia.org/api/rest_v1/page/summary/{requests.utils.quote(title)}"
        )
        data = summary_resp.json()
        if data.get("type") == "disambiguation":
            return None

        extract = _clean_text(data.get("extract"))
        page_url = data.get("content_urls", {}).get("desktop", {}).get("page")
        thumb = data.get("thumbnail", {}).get("source")

        if not extract:
            return None

        logger.info("Wikipedia -> matched '%s'", title)
        return {"title": title, "extract": extract, "url": page_url, "image": thumb}
    except Exception as e:
        logger.debug("Wikipedia lookup failed: %s", str(e)[:120])
        return None


# ---------------------------------------------------------------------------
# Bing Images (no JS needed, image metadata is embedded as inline JSON)
# ---------------------------------------------------------------------------

def bing_images(query, limit=7):
    try:
        resp = _get(
            "https://www.bing.com/images/search",
            params={"q": query, "form": "HDRSC2", "first": 1},
        )
    except Exception as e:
        logger.debug("Bing images request failed: %s", str(e)[:120])
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    images, seen = [], set()

    for a in soup.select("a.iusc"):
        raw = a.get("m")
        if not raw:
            continue
        try:
            meta = json.loads(raw)
        except Exception:
            continue
        src = meta.get("murl")
        if src and src not in seen and _is_probably_content_image(src):
            seen.add(src)
            images.append(src)
        if len(images) >= limit:
            break

    logger.info("Bing Images -> %d image(s)", len(images))
    return images


# ---------------------------------------------------------------------------
# Lightweight page peek (for filling gaps -- just one small GET, no render)
# ---------------------------------------------------------------------------

def _peek_page(url, min_len=200, max_len=1200, want_image=True):
    """Grab a short bit of usable text (and maybe an og:image) from a page
    without rendering it -- just a plain GET + BeautifulSoup parse."""
    try:
        resp = _get(url, retries=1, timeout=6)
    except Exception:
        return {"text": None, "image": None}

    soup = BeautifulSoup(resp.text, "html.parser")

    image = None
    if want_image:
        og = soup.find("meta", property="og:image")
        if og and og.get("content") and _is_probably_content_image(og["content"]):
            image = og["content"]

    text = None
    meta_desc = soup.find("meta", attrs={"name": "description"})
    if meta_desc and meta_desc.get("content"):
        text = _clean_text(meta_desc["content"])
    if not text or len(text) < min_len:
        paragraphs = [_clean_text(p.get_text()) for p in soup.find_all("p")]
        joined = " ".join(p for p in paragraphs if p)
        if len(joined) > len(text or ""):
            text = joined

    if text and len(text) > max_len:
        text = text[:max_len].rsplit(" ", 1)[0] + "..."

    return {"text": text if text and len(text) >= 40 else None, "image": image}


def _fill_gaps_from_pages(organic_results, need_images=0, need_text=False, max_sites=4):
    images, texts, visited = [], [], []
    for r in organic_results[:max_sites]:
        if len(images) >= need_images and (not need_text or texts):
            break
        url = r.get("link")
        if not url:
            continue
        data = _peek_page(url, want_image=len(images) < need_images)
        visited.append(url)
        if data["image"] and data["image"] not in images:
            images.append(data["image"])
        if data["text"]:
            texts.append(data["text"])
        human_delay()
    return images, texts, visited


def _build_fallback_overview(organic_results, page_texts, max_len=2000):
    parts = []
    snippets = [r["snippet"] for r in organic_results if r.get("snippet")]
    if snippets:
        parts.append(" ".join(snippets[:5]))
    parts.extend(pt for pt in page_texts if pt)
    if not parts:
        return None
    text = "\n\n".join(parts)
    if len(text) > max_len:
        text = text[:max_len].rsplit(" ", 1)[0] + "..."
    return text


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def _empty_result(query, reason=""):
    return {
        "query": query,
        "ai_overview_text": None,
        "ai_links": [],
        "image_links": [],
        "organic_results": [],
        "engines_used": [],
        "status": "failed",
        "reason": reason,
    }


def unified_search(
    query,
    mode="fast",
    image_limit=7,
    min_images=4,
    min_sources=5,
    organic_limit=20,
    max_fallback_sites=4,
):
    """
    One search call that:
      1. Looks up Wikipedia for an authoritative overview (if relevant).
      2. Pulls organic results from DuckDuckGo.
      3. Adds Google results if DDG was thin, failed, or mode == "deep".
      4. Pulls images from Bing Images.
      5. In "deep" mode (or if still short of targets), does a light GET
         on a few top organic pages to backfill images / overview text.

    Always returns the same shape:
      {query, ai_overview_text, ai_links, image_links, organic_results,
       engines_used, status, reason}
    """
    engines_used = []
    overview = None
    images = []
    organic = []
    errors = []

    # ---- Wikipedia (cheap, reliable, great overview source) ----
    wiki = wikipedia_lookup(query)
    if wiki:
        engines_used.append("wikipedia")
        overview = wiki["extract"]
        if wiki.get("image"):
            images.append(wiki["image"])
        organic.append({
            "title": wiki["title"], "link": wiki["url"],
            "snippet": wiki["extract"][:200], "engine": "wikipedia",
        })

    # ---- DuckDuckGo ----
    try:
        ddg_results = ddg_search(query, max_results=organic_limit)
        engines_used.append("duckduckgo")
        organic = _merge_organic(organic, ddg_results, limit=organic_limit)
    except Exception as e:
        errors.append(f"duckduckgo: {type(e).__name__} - {str(e)[:120]}")
        logger.warning("DuckDuckGo engine failed entirely: %s", errors[-1])

    thin = len(organic) < min_sources or not overview

    # ---- Google (fallback / supplement) ----
    if thin or mode == "deep":
        try:
            g_results = google_search(query, max_results=organic_limit)
            engines_used.append("google")
            organic = _merge_organic(organic, g_results, limit=organic_limit)
        except Exception as e:
            errors.append(f"google: {type(e).__name__} - {str(e)[:120]}")
            logger.warning("Google engine failed entirely: %s", errors[-1])

    # ---- Bing Images ----
    try:
        img_results = bing_images(query, limit=image_limit)
        if img_results:
            engines_used.append("bing_images")
        images = _merge_images(images, img_results, limit=image_limit)
    except Exception as e:
        errors.append(f"bing_images: {type(e).__name__} - {str(e)[:120]}")
        logger.warning("Bing Images failed entirely: %s", errors[-1])

    # ---- Gap-fill by lightly peeking at top pages ----
    need_images = max(0, min_images - len(images))
    need_text = not overview
    want_fill = mode == "deep" or need_images or need_text

    if want_fill and organic:
        extra_images, extra_texts, visited = _fill_gaps_from_pages(
            organic,
            need_images=need_images if need_images else (2 if mode == "deep" else 0),
            need_text=need_text,
            max_sites=max_fallback_sites,
        )
        images = _merge_images(images, extra_images, limit=image_limit)
        if not overview:
            overview = _build_fallback_overview(organic, extra_texts)
        elif mode == "deep" and extra_texts:
            overview = overview + "\n\n" + "\n\n".join(extra_texts[:3])
        logger.info(
            "Gap-fill visited %d site(s) -> images=%d overview=%s",
            len(visited), len(images), "yes" if overview else "no",
        )

    status = "success" if (organic or images or overview) else "failed"
    reason = "; ".join(errors) if status == "failed" else ""

    result = {
        "query": query,
        "ai_overview_text": overview,
        "ai_links": [item["link"] for item in organic][:40 if mode == "deep" else 18],
        "image_links": images[:image_limit],
        "organic_results": organic[:organic_limit],
        "engines_used": engines_used,
        "status": status,
        "reason": reason,
    }

    logger.info(
        "FINAL %s | engines=%s | overview=%s | images=%d | organic=%d",
        mode.upper(), engines_used, "yes" if overview else "no", len(images), len(organic),
    )
    return result


# Backwards-compatible aliases so existing MCP code that imports the old
# module names keeps working without edits.
def scrape_duckduckgo(query, mode="fast", **kwargs):
    return unified_search(query, mode=mode, **kwargs)


def scrape_google_ai(query, max_retries=3):
    return unified_search(query, mode="fast")


if __name__ == "__main__":
    test_query = "what happen in iran"
    data = unified_search(test_query, mode="deep")

    logger.info("=" * 110)
    logger.info("QUERY: %s", data["query"])
    overview = data.get("ai_overview_text") or "No summary captured"
    logger.info("OVERVIEW: %s", overview[:1800])
    logger.info("IMAGES (%d): %s", len(data["image_links"]), data["image_links"])
    logger.info("ORGANIC (%d)", len(data["organic_results"]))
    for i, r in enumerate(data["organic_results"][:15], 1):
        logger.info("%d. [%s] %s -> %s", i, r.get("engine"), r["title"], r["link"])