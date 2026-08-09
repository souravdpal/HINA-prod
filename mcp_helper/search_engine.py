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
  - Bing web results          (https://www.bing.com/search)
  - Startpage results         (https://www.startpage.com/sp/search)
  - SearXNG meta-search       (public/self-hosted instance, JSON API)
  - Wikipedia summary + image (REST API, very reliable, great overview text)
  - Bing Images               (https://www.bing.com/images/search)

Plus a concurrent "tree" scraper that opens every organic result link (and,
in deep mode, a bounded second hop into the best links found on those
pages) to pull real body text/images instead of trusting engine snippets,
then a relevance-based scorer that sorts everything into one ranked list.

No browser, no chromedriver, no GPU/render process, no multi-hundred-MB
memory footprint per call -- just HTTP requests. This also means it's much
faster (no page rendering / JS execution wait).

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
from concurrent.futures import ThreadPoolExecutor, as_completed
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

# Public SearXNG instances to try (first one that responds wins). Override
# by setting SEARXNG_INSTANCE_URL to your own self-hosted instance if you
# have one -- self-hosted is more reliable and won't be rate-limited.
import os

SEARXNG_INSTANCE_URL = os.environ.get("SEARXNG_INSTANCE_URL", "").rstrip("/")
_PUBLIC_SEARXNG_INSTANCES = [
    "https://searx.be",
    "https://searx.tiekoetter.com",
    "https://priv.au",
    "https://search.inetol.net",
]


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
# Relevance scoring / world-class sorting
# ---------------------------------------------------------------------------

_ENGINE_TRUST = {
    "wikipedia": 1.25,
    "google": 1.15,
    "bing": 1.1,
    "searxng": 1.1,
    "duckduckgo": 1.0,
    "startpage": 1.0,
}

_STOPWORDS = {
    "the", "a", "an", "of", "in", "on", "for", "and", "or", "to", "is",
    "are", "what", "who", "when", "where", "why", "how", "did", "does",
    "with", "about", "was", "were", "be", "been", "at", "by", "as",
}


def _query_terms(query):
    return [t for t in re.findall(r"[a-z0-9]+", query.lower()) if t and t not in _STOPWORDS]


def _score_relevance(query_terms, item):
    """Score an organic result by term overlap across title/snippet/deep_text,
    with a bonus for the source engine's general trustworthiness and for
    deeper (fully-scraped) pages that actually confirm the content."""
    if not query_terms:
        return 0.0

    title = (item.get("title") or "").lower()
    snippet = (item.get("snippet") or "").lower()
    deep_text = (item.get("deep_text") or "").lower()

    score = 0.0
    for term in query_terms:
        if term in title:
            score += 3.0
        if term in snippet:
            score += 1.5
        if deep_text and term in deep_text:
            score += 1.0

    # Reward results where multiple distinct query terms appear together
    # (better topical match than a single keyword hit).
    hits = sum(1 for t in query_terms if t in title or t in snippet or t in deep_text)
    score += 1.2 * hits

    score *= _ENGINE_TRUST.get(item.get("engine", ""), 1.0)

    if item.get("deep_scraped"):
        score += 2.0  # confirmed real content, not just a snippet guess

    return round(score, 3)


def _sort_by_relevance(query, organic_results):
    terms = _query_terms(query)
    scored = [(_score_relevance(terms, item), item) for item in organic_results]
    scored.sort(key=lambda pair: pair[0], reverse=True)
    for score, item in scored:
        item["relevance_score"] = score
    return [item for _, item in scored]


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
# Bing (web results -- separate from Bing Images below)
# ---------------------------------------------------------------------------

def bing_web_search(query, max_results=10):
    resp = _get(
        "https://www.bing.com/search",
        params={"q": query, "count": max_results, "setlang": "en"},
    )
    soup = BeautifulSoup(resp.text, "html.parser")
    organic = []

    for li in soup.select("li.b_algo"):
        h2 = li.find("h2")
        a = h2.find("a") if h2 else None
        if not a or not a.get("href"):
            continue
        link = a["href"]
        if not link.startswith("http"):
            continue
        title = _clean_text(a.get_text())
        snip_tag = li.select_one(".b_caption p") or li.select_one(".b_lineclamp2") or li.find("p")
        snippet = _clean_text(snip_tag.get_text(" ")) if snip_tag else ""
        if title and link:
            organic.append({"title": title, "link": link, "snippet": snippet, "engine": "bing"})
        if len(organic) >= max_results:
            break

    logger.info("Bing -> %d organic result(s)", len(organic))
    return organic


# ---------------------------------------------------------------------------
# Startpage (privacy-front for Google-quality results, scrape-friendly HTML)
# ---------------------------------------------------------------------------

def startpage_search(query, max_results=10):
    resp = _get(
        "https://www.startpage.com/sp/search",
        params={"query": query, "cat": "web", "language": "english"},
    )
    soup = BeautifulSoup(resp.text, "html.parser")
    organic = []

    results = soup.select("div.w-gl__result") or soup.select("div.result")
    for result in results:
        a = result.select_one("a.w-gl__result-title") or result.find("a", href=True)
        if not a or not a.get("href"):
            continue
        link = a["href"]
        if not link.startswith("http"):
            continue
        title = _clean_text(a.get_text())
        snip_tag = result.select_one("p.w-gl__description") or result.find("p")
        snippet = _clean_text(snip_tag.get_text(" ")) if snip_tag else ""
        if title and link:
            organic.append({"title": title, "link": link, "snippet": snippet, "engine": "startpage"})
        if len(organic) >= max_results:
            break

    logger.info("Startpage -> %d organic result(s)", len(organic))
    return organic


# ---------------------------------------------------------------------------
# SearXNG (meta-search: itself aggregates Google/Bing/DDG/etc -- one JSON
# call gives us a second, independently-ranked opinion to merge in)
# ---------------------------------------------------------------------------

def searxng_search(query, max_results=10):
    instances = [SEARXNG_INSTANCE_URL] if SEARXNG_INSTANCE_URL else list(_PUBLIC_SEARXNG_INSTANCES)
    last_exc = None

    for base in instances:
        if not base:
            continue
        try:
            resp = _get(
                f"{base}/search",
                params={"q": query, "format": "json", "language": "en"},
                retries=0,
                timeout=8,
            )
            data = resp.json()
        except Exception as e:
            last_exc = e
            logger.debug("SearXNG instance %s failed: %s", base, str(e)[:120])
            continue

        organic = []
        for item in data.get("results", []):
            link = item.get("url")
            title = _clean_text(item.get("title"))
            if not link or not title:
                continue
            organic.append({
                "title": title,
                "link": link,
                "snippet": _clean_text(item.get("content")),
                "engine": "searxng",
            })
            if len(organic) >= max_results:
                break

        if organic:
            logger.info("SearXNG (%s) -> %d organic result(s)", base, len(organic))
            return organic

    if last_exc:
        raise last_exc
    return []


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


def _scrape_full_page(url, max_len=3000):
    """Full (but still lightweight, no-JS) scrape of one result page: main
    body text, an image, and any on-page links worth surfacing. This is the
    'tree' step -- we don't just trust the search engine's snippet, we
    actually open the page the engine pointed at."""
    try:
        resp = _get(url, retries=1, timeout=8)
    except Exception as e:
        return {"url": url, "text": None, "image": None, "links": [], "error": str(e)[:120]}

    ctype = resp.headers.get("Content-Type", "")
    if "text/html" not in ctype and "application/xhtml" not in ctype:
        return {"url": url, "text": None, "image": None, "links": [], "error": "non-html content"}

    soup = BeautifulSoup(resp.text, "html.parser")

    for tag in soup(["script", "style", "noscript", "nav", "footer", "header", "form"]):
        tag.decompose()

    image = None
    og = soup.find("meta", property="og:image")
    if og and og.get("content") and _is_probably_content_image(og["content"]):
        image = og["content"]

    # Prefer <article>/<main> body text when present, else all paragraphs.
    body = soup.find("article") or soup.find("main") or soup
    paragraphs = [_clean_text(p.get_text(" ")) for p in body.find_all("p")]
    text = " ".join(p for p in paragraphs if p and len(p) > 30)
    if not text:
        meta_desc = soup.find("meta", attrs={"name": "description"})
        if meta_desc and meta_desc.get("content"):
            text = _clean_text(meta_desc["content"])
    if text and len(text) > max_len:
        text = text[:max_len].rsplit(" ", 1)[0] + "..."

    # Pull a handful of on-page outbound links (the "tree" of the tree) --
    # useful for surfacing related/deeper reading without another search.
    page_domain = _domain(url)
    tree_links, seen_links = [], set()
    for a in body.find_all("a", href=True):
        href = a["href"]
        if not href.startswith("http"):
            continue
        link_domain = _domain(href)
        if link_domain == page_domain or href in seen_links:
            continue
        link_text = _clean_text(a.get_text())
        if not link_text or len(link_text) < 4:
            continue
        seen_links.add(href)
        tree_links.append({"text": link_text[:120], "href": href})
        if len(tree_links) >= 5:
            break

    return {
        "url": url,
        "text": text if text and len(text) >= 40 else None,
        "image": image,
        "links": tree_links,
        "error": None,
    }


def _deep_scrape_tree(organic_results, max_pages=12, max_workers=8):
    """Concurrently scrape the full page (not just a snippet) of every
    organic result link -- the 'tree' scrape. Attaches deep_text / a page
    image / on-page tree_links back onto each organic result in place, and
    returns the pool of extra images/texts collected along the way."""
    targets = [r for r in organic_results[:max_pages] if r.get("link")]
    if not targets:
        return [], []

    by_url = {r["link"]: r for r in targets}
    extra_images, extra_texts = [], []

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_scrape_full_page, url): url for url in by_url}
        for future in as_completed(futures):
            url = futures[future]
            try:
                data = future.result()
            except Exception as e:
                logger.debug("Deep scrape failed for %s: %s", url, str(e)[:120])
                continue

            item = by_url.get(url)
            if not item:
                continue
            item["deep_scraped"] = data["error"] is None
            if data.get("text"):
                item["deep_text"] = data["text"]
                extra_texts.append(data["text"])
            if data.get("image"):
                item["deep_image"] = data["image"]
                extra_images.append(data["image"])
            if data.get("links"):
                item["tree_links"] = data["links"]

    logger.info("Deep tree-scrape -> %d page(s) processed", len(targets))
    return extra_images, extra_texts


def _second_hop_crawl(organic_results, max_links=10, max_workers=8):
    """Deep-mode 'tree' step 2: take the on-page links discovered while
    scraping each top-level result (tree_links) and scrape a bounded batch
    of those too, so we're not just reading the pages the search engines
    pointed at but also a hop further into the sites they link to."""
    hop_urls, seen = [], set()
    for item in organic_results:
        for link in item.get("tree_links", []):
            href = link.get("href")
            if href and href not in seen:
                seen.add(href)
                hop_urls.append(href)
            if len(hop_urls) >= max_links:
                break
        if len(hop_urls) >= max_links:
            break

    if not hop_urls:
        return [], [], []

    extra_images, extra_texts, visited = [], [], []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_scrape_full_page, url): url for url in hop_urls}
        for future in as_completed(futures):
            url = futures[future]
            try:
                data = future.result()
            except Exception:
                continue
            visited.append(url)
            if data.get("text"):
                extra_texts.append(data["text"])
            if data.get("image"):
                extra_images.append(data["image"])

    logger.info("Second-hop crawl -> %d link(s) visited", len(visited))
    return extra_images, extra_texts, visited


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

    thin = len(organic) < min_sources or not overview

    # ---- Bing web + Startpage (extra engines: wider coverage, run whenever
    # results are still thin or the caller asked for a deep/world-class pass)
    if thin or mode == "deep":
        try:
            b_results = bing_web_search(query, max_results=organic_limit)
            engines_used.append("bing")
            organic = _merge_organic(organic, b_results, limit=organic_limit)
        except Exception as e:
            errors.append(f"bing: {type(e).__name__} - {str(e)[:120]}")
            logger.warning("Bing engine failed entirely: %s", errors[-1])

        try:
            sp_results = startpage_search(query, max_results=organic_limit)
            engines_used.append("startpage")
            organic = _merge_organic(organic, sp_results, limit=organic_limit)
        except Exception as e:
            errors.append(f"startpage: {type(e).__name__} - {str(e)[:120]}")
            logger.warning("Startpage engine failed entirely: %s", errors[-1])

        try:
            sx_results = searxng_search(query, max_results=organic_limit)
            engines_used.append("searxng")
            organic = _merge_organic(organic, sx_results, limit=organic_limit)
        except Exception as e:
            errors.append(f"searxng: {type(e).__name__} - {str(e)[:120]}")
            logger.warning("SearXNG engine failed entirely: %s", errors[-1])

    # ---- Bing Images ----
    try:
        img_results = bing_images(query, limit=image_limit)
        if img_results:
            engines_used.append("bing_images")
        images = _merge_images(images, img_results, limit=image_limit)
    except Exception as e:
        errors.append(f"bing_images: {type(e).__name__} - {str(e)[:120]}")
        logger.warning("Bing Images failed entirely: %s", errors[-1])

    need_images = max(0, min_images - len(images))
    need_text = not overview

    if mode == "deep" and organic:
        # ---- Full "tree" scrape: actually open every result link
        # concurrently (not just a light peek), pull real body text, a
        # page image, and a handful of on-page outbound links. ----
        extra_images, extra_texts = _deep_scrape_tree(
            organic, max_pages=max(organic_limit, max_fallback_sites), max_workers=8,
        )
        engines_used.append("deep_tree_scrape")
        images = _merge_images(images, extra_images, limit=image_limit)
        if not overview:
            overview = _build_fallback_overview(organic, extra_texts)
        elif extra_texts:
            overview = overview + "\n\n" + "\n\n".join(extra_texts[:3])

        # ---- Second hop: follow a bounded batch of the links discovered
        # on those pages too (the actual "tree" of the tree). ----
        hop_images, hop_texts, hop_visited = _second_hop_crawl(
            organic, max_links=10, max_workers=8,
        )
        if hop_visited:
            engines_used.append("second_hop_crawl")
        images = _merge_images(images, hop_images, limit=image_limit)
        if hop_texts:
            overview = (overview + "\n\n" if overview else "") + "\n\n".join(hop_texts[:3])

        logger.info(
            "Deep tree-scrape -> images=%d overview=%s (+%d second-hop link(s))",
            len(images), "yes" if overview else "no", len(hop_visited),
        )
    elif (need_images or need_text) and organic:
        # ---- Fast mode: just a light peek to backfill gaps ----
        extra_images, extra_texts, visited = _fill_gaps_from_pages(
            organic, need_images=need_images, need_text=need_text,
            max_sites=max_fallback_sites,
        )
        images = _merge_images(images, extra_images, limit=image_limit)
        if not overview:
            overview = _build_fallback_overview(organic, extra_texts)
        logger.info(
            "Gap-fill visited %d site(s) -> images=%d overview=%s",
            len(visited), len(images), "yes" if overview else "no",
        )

    # ---- World-class sorting: rank every organic result by real relevance
    # (title/snippet/deep-text term overlap + engine trust + confirmed
    # deep-scrape bonus) instead of leaving them in raw engine order. ----
    organic = _sort_by_relevance(query, organic)

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
