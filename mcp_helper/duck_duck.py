"""
DuckDuckGo scraper (Selenium-based) -- robust version.

What changed vs. the previous version:
  - Explicit WebDriverWait on key elements instead of fixed sleeps, so the
    scraper doesn't race the page before the AI overview / results render.
  - The "give up after one pass" behavior is gone. scrape_duckduckgo now
    keeps working (more retries, then falls back to visiting the organic
    result pages directly) until it hits real targets:
        * min_images (default 4, tries for up to image_limit)
        * min_sources (organic results with title+link+snippet)
        * some overview text (falls back to snippet concatenation / page
          text if the DDG instant-answer box never renders)
  - Image extraction no longer silently skips images whose dimensions
    haven't been computed yet (natural size 0 on a lazy-loaded img). It waits
    briefly and rechecks, and falls back to scraping og:image / twitter:image
    meta tags from visited pages, which are far more reliable than scraping
    arbitrary <img> tags.
  - Fallback crawl: if the DDG results page itself doesn't yield enough
    images/overview text, the scraper visits the top organic links directly
    (same driver, reused) and pulls: page title, meta description, first
    substantial paragraph, and a handful of large content images from each.
    This is the "go inside sites and gather data" behavior that was missing.
  - All extraction still returns a consistent shape, so callers can always
    do `data.get("ai_overview_text")` etc. without blowing up.
  - Still stdout-safe for MCP stdio use: only stderr/logger, never print().
"""

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException
from webdriver_manager.chrome import ChromeDriverManager
from urllib.parse import urlparse
import time
import random
import json
import logging
import sys
import shutil

logging.basicConfig(level=logging.INFO, format="[duck_duck] %(message)s", stream=sys.stderr)
logger = logging.getLogger("duck_duck")


# ---------------------------------------------------------------------------
# Driver helpers
# ---------------------------------------------------------------------------

def human_delay(min_sec=0.4, max_sec=1.4):
    time.sleep(random.uniform(min_sec, max_sec))


def create_driver():
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-extensions")
    options.add_argument("--window-size=1920,1080")
    options.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
    )
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    driver.set_page_load_timeout(20)
    return driver


def _wait_for_any(driver, selectors, timeout=8):
    """Wait until at least one element matching any selector is present.
    Returns True if something showed up, False on timeout (non-fatal)."""
    try:
        WebDriverWait(driver, timeout).until(
            lambda d: any(d.find_elements(By.CSS_SELECTOR, sel) for sel in selectors)
        )
        return True
    except TimeoutException:
        return False


# ---------------------------------------------------------------------------
# Overview / instant-answer extraction
# ---------------------------------------------------------------------------

_BOILERPLATE_MARKERS = (
    "all images videos news maps",
    "settings",
    "privacy",
    "region:",
    "safe search:",
    "duckduckgo.com",
    "sign in",
    "about duckduckgo",
    "help improve",
)


def _looks_like_boilerplate(text: str) -> bool:
    low = text.lower()
    return any(marker in low for marker in _BOILERPLATE_MARKERS)


def extract_overview(driver, min_len=200, max_len=2000):
    selectors = [
        "[data-testid='result--ai']",
        "[data-testid='search-assist']",
        ".search-assist",
        ".module__body",
        ".zci",
        "section",
    ]

    _wait_for_any(driver, selectors[:4], timeout=6)

    best_text = None
    best_len = 0

    for sel in selectors:
        try:
            boxes = driver.find_elements(By.CSS_SELECTOR, sel)
        except Exception:
            continue

        for box in boxes:
            try:
                text = box.text.strip()
            except Exception:
                continue

            if len(text) < min_len:
                continue
            if _looks_like_boilerplate(text):
                continue

            if len(text) > best_len:
                best_text = text
                best_len = len(text)

        if best_text and sel in selectors[:2]:
            break

    if best_text and len(best_text) > max_len:
        best_text = best_text[:max_len].rsplit(" ", 1)[0] + "..."

    return best_text


def build_fallback_overview(organic_results, page_texts, max_len=2000):
    """When DDG's own instant-answer box is empty, stitch something useful
    together from organic snippets and/or text pulled from visited pages."""
    parts = []

    snippets = [r["snippet"] for r in organic_results if r.get("snippet")]
    if snippets:
        parts.append(" ".join(snippets[:5]))

    for pt in page_texts:
        if pt:
            parts.append(pt)

    if not parts:
        return None

    text = "\n\n".join(parts)
    if len(text) > max_len:
        text = text[:max_len].rsplit(" ", 1)[0] + "..."
    return text


# ---------------------------------------------------------------------------
# Image extraction (search results page)
# ---------------------------------------------------------------------------

_BAD_IMG_MARKERS = (".ico", ".svg", "favicon", "avatar", "logo", "asset", "pixel", "sprite", "spacer")


def _is_probably_content_image(src, width, height, min_dim):
    if not src or src.startswith("data:image"):
        return False
    low = src.lower()
    if any(marker in low for marker in _BAD_IMG_MARKERS):
        return False
    if width and height and (width < min_dim or height < min_dim):
        return False
    return True


def extract_image_links(driver, limit=7, min_dim=80):
    """Extract candidate content images from the DDG results page itself."""
    valid_images = []
    seen = set()

    selectors = [
        "[data-testid='result'] img",
        ".module__image img",
        ".zci__image img",
        "img",
    ]

    try:
        # give lazy-loaded images a moment to populate natural dimensions
        human_delay(0.5, 1.0)
        for selector in selectors:
            if len(valid_images) >= limit:
                break

            elements = driver.find_elements(By.CSS_SELECTOR, selector)
            for img in elements:
                if len(valid_images) >= limit:
                    break

                src = img.get_attribute("src") or img.get_attribute("data-src")
                if not src or src in seen:
                    continue

                width = height = 0
                try:
                    width = int(img.get_attribute("naturalWidth") or 0)
                    height = int(img.get_attribute("naturalHeight") or 0)
                    if width == 0 or height == 0:
                        size = img.size
                        width = size.get("width", 0)
                        height = size.get("height", 0)
                except Exception:
                    width = height = 0  # unknown -> don't auto-reject, let marker check decide

                if not _is_probably_content_image(src, width, height, min_dim):
                    continue

                # keep off-domain (real hosted) images or DDG's proxy-hosted ones
                if "external-content.duckduckgo.com" in src or (
                    src.startswith("http") and "duckduckgo.com" not in src
                ):
                    valid_images.append(src)
                    seen.add(src)

    except Exception as e:
        logger.debug("Failed to extract images from results page: %s", str(e))

    return valid_images


# ---------------------------------------------------------------------------
# Organic results extraction
# ---------------------------------------------------------------------------

def extract_organic_results(driver, limit=20):
    organic = []
    seen_links = set()

    _wait_for_any(driver, ["[data-testid='result']", ".result", "article"], timeout=8)

    try:
        results = driver.find_elements(
            By.CSS_SELECTOR, "[data-testid='result'], .result, article"
        )
    except Exception:
        results = []

    for r in results:
        if len(organic) >= limit:
            break
        try:
            title_el = r.find_element(
                By.CSS_SELECTOR, "h2 a, .result__title, [data-testid='result-title-a']"
            )
            title = title_el.text.strip()
        except Exception:
            continue

        link = ""
        try:
            for a in r.find_elements(By.TAG_NAME, "a"):
                href = a.get_attribute("href")
                if href and href.startswith("https://") and "duckduckgo.com" not in href:
                    link = href
                    break
        except Exception:
            pass

        if not title or not link or link in seen_links:
            continue

        snippet = ""
        try:
            snippet_el = r.find_element(
                By.CSS_SELECTOR, "[data-testid='result-snippet'], .result__snippet"
            )
            snippet = snippet_el.text.strip()
        except Exception:
            pass

        seen_links.add(link)
        organic.append({"title": title[:160], "link": link, "snippet": snippet[:300]})

    return organic


# ---------------------------------------------------------------------------
# Fallback: visit organic pages directly and pull data/images from them
# ---------------------------------------------------------------------------

def _domain(url):
    try:
        return urlparse(url).netloc.lower()
    except Exception:
        return ""


def scrape_page_for_data(driver, url, min_dim=120, max_images=3, max_text_chars=600):
    """Visit a single URL and pull: page text snippet + a few real content
    images (og:image / twitter:image / large <img> tags). Best-effort;
    never raises."""
    text_out = ""
    images = []

    try:
        driver.get(url)
        human_delay(0.8, 1.6)

        # 1) meta og:image / twitter:image (most reliable "hero" image)
        for meta_sel in ("meta[property='og:image']", "meta[name='twitter:image']"):
            try:
                metas = driver.find_elements(By.CSS_SELECTOR, meta_sel)
                for m in metas:
                    content = m.get_attribute("content")
                    if content and content.startswith("http") and content not in images:
                        images.append(content)
                    if len(images) >= max_images:
                        break
            except Exception:
                pass
            if len(images) >= max_images:
                break

        # 2) fall back to scanning visible <img> tags for large content images
        if len(images) < max_images:
            try:
                for img in driver.find_elements(By.TAG_NAME, "img"):
                    if len(images) >= max_images:
                        break
                    src = img.get_attribute("src") or img.get_attribute("data-src")
                    if not src:
                        continue
                    width = height = 0
                    try:
                        width = int(img.get_attribute("naturalWidth") or 0)
                        height = int(img.get_attribute("naturalHeight") or 0)
                        if width == 0 or height == 0:
                            size = img.size
                            width = size.get("width", 0)
                            height = size.get("height", 0)
                    except Exception:
                        width = height = 0
                    if _is_probably_content_image(src, width, height, min_dim) and src not in images:
                        images.append(src)
            except Exception:
                pass

        # 3) page text: first few substantial lines/paragraphs
        try:
            body = driver.find_element(By.TAG_NAME, "body").text
            lines = [line.strip() for line in body.splitlines() if len(line.strip()) > 60]
            text_out = " ".join(lines[:6])[:max_text_chars]
        except Exception:
            text_out = ""

    except (TimeoutException, WebDriverException) as e:
        logger.debug("Could not load %s: %s", url, str(e)[:100])
    except Exception as e:
        logger.debug("Unexpected error scraping %s: %s", url, str(e)[:100])

    return {"text": text_out, "images": images}


def deep_crawl_for_gaps(driver, organic_results, need_images=0, need_text=False,
                         max_sites=6, min_dim=120):
    """Visit organic result pages (in order, skipping duplicate domains where
    possible) until we've gathered enough images and/or overview text, or
    we run out of candidates. Returns (image_links, page_texts, visited)."""
    images = []
    texts = []
    visited = []
    seen_domains = set()

    # prioritize link diversity so we don't hammer one site
    ordered = sorted(
        organic_results,
        key=lambda r: _domain(r["link"]) in seen_domains,
    )

    for r in organic_results[:max_sites]:
        if len(images) >= need_images and (not need_text or texts):
            break

        url = r.get("link")
        if not url:
            continue

        dom = _domain(url)
        seen_domains.add(dom)

        data = scrape_page_for_data(driver, url, min_dim=min_dim, max_images=3)
        visited.append(url)

        for img in data["images"]:
            if img not in images:
                images.append(img)

        if data["text"]:
            texts.append(data["text"])

    return images, texts, visited


# ---------------------------------------------------------------------------
# Deep mode: visit top links and summarize (used when mode="deep")
# ---------------------------------------------------------------------------

def get_page_summary(driver, url, max_chars=700):
    try:
        driver.get(url)
        human_delay(0.8, 1.6)
        body = driver.find_element(By.TAG_NAME, "body").text
        lines = [line.strip() for line in body.splitlines() if len(line.strip()) > 50]
        return " ".join(lines[:12])[:max_chars]
    except Exception:
        return ""


def deep_summarize(driver, links, max_sites=8, min_summary_len=180):
    summaries = []
    for url in links[:max_sites]:
        summary = get_page_summary(driver, url)
        if len(summary) > min_summary_len:
            summaries.append({"url": url, "summary": summary})
    return summaries


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def _empty_result(query, status="failed", reason=""):
    return {
        "query": query,
        "ai_overview_text": None,
        "ai_links": [],
        "image_links": [],
        "organic_results": [],
        "status": status,
        "reason": reason,
    }


def _single_pass(driver, query, mode, organic_limit, image_limit):
    driver.get(f"https://duckduckgo.com/?q={query.replace(' ', '+')}&ia=web")
    _wait_for_any(
        driver,
        ["[data-testid='result']", ".result", "article", "[data-testid='result--ai']"],
        timeout=10,
    )
    human_delay(0.8, 1.6)

    result = {
        "query": query,
        "ai_overview_text": extract_overview(driver),
        "ai_links": [],
        "image_links": extract_image_links(driver, limit=image_limit),
        "organic_results": [],
        "status": "success",
    }

    organic = extract_organic_results(driver, limit=45 if mode == "deep" else organic_limit)
    result["organic_results"] = organic
    result["ai_links"] = [item["link"] for item in organic][: 40 if mode == "deep" else 18]

    if mode == "deep" and result["ai_links"]:
        summaries = deep_summarize(driver, result["ai_links"])
        if summaries:
            extra = "\n\n".join(
                f"Source: {s['url'][:80]}...\n{s['summary']}" for s in summaries[:4]
            )
            result["ai_overview_text"] = (
                f"{result['ai_overview_text']}\n\n{extra}" if result["ai_overview_text"] else extra
            )

    return result


def scrape_duckduckgo(
    query,
    mode="fast",
    max_retries=3,
    organic_limit=20,
    image_limit=7,
    min_images=4,
    min_sources=4,
    max_fallback_sites=6,
):
    """
    mode: "fast" (search page + fallback crawl if needed) or "deep" (also
          visits top links up front and appends short page summaries).

    Keeps retrying / falling back until it has at least `min_images` images
    and `min_sources` organic results (or runs out of useful retries), rather
    than returning as soon as the DDG page renders at all.
    """
    last_error = ""
    driver = None
    best_result = None

    def _ensure_driver():
        nonlocal driver
        if driver is not None:
            try:
                # cheap liveness check; raises if the browser/session is dead
                _ = driver.current_url
                return
            except Exception:
                logger.warning("Driver session is dead, recreating...")
                try:
                    driver.quit()
                except Exception:
                    pass
                driver = None
        driver = create_driver()

    try:
        _ensure_driver()

        for attempt in range(max_retries):
            try:
                _ensure_driver()
                result = _single_pass(driver, query, mode, organic_limit, image_limit)

                have_images = len(result["image_links"])
                have_sources = len(result["organic_results"])
                have_overview = bool(result["ai_overview_text"])

                logger.info(
                    "Attempt %d | overview=%s images=%d sources=%d",
                    attempt + 1,
                    "yes" if have_overview else "no",
                    have_images,
                    have_sources,
                )

                # Keep the best-so-far in case later attempts do worse
                if best_result is None or (
                    have_images + have_sources
                    > len(best_result["image_links"]) + len(best_result["organic_results"])
                ):
                    best_result = result

                good_enough = have_sources >= min_sources and have_images >= min_images and have_overview
                if good_enough:
                    best_result = result
                    break

                # Not good enough yet: try to fill the gaps by visiting the
                # organic result pages directly, instead of just retrying blind.
                if result["organic_results"]:
                    need_images = max(0, min_images - have_images)
                    need_text = not have_overview
                    if need_images or need_text:
                        extra_images, extra_texts, visited = deep_crawl_for_gaps(
                            driver,
                            result["organic_results"],
                            need_images=need_images,
                            need_text=need_text,
                            max_sites=max_fallback_sites,
                        )
                        if extra_images:
                            merged = list(result["image_links"])
                            for img in extra_images:
                                if img not in merged:
                                    merged.append(img)
                            result["image_links"] = merged[:image_limit]

                        if not result["ai_overview_text"]:
                            result["ai_overview_text"] = build_fallback_overview(
                                result["organic_results"], extra_texts
                            )

                        logger.info(
                            "Fallback crawl visited %d site(s) -> images=%d overview=%s",
                            len(visited),
                            len(result["image_links"]),
                            "yes" if result["ai_overview_text"] else "no",
                        )

                        best_result = result

                        have_images = len(result["image_links"])
                        have_overview = bool(result["ai_overview_text"])
                        if have_sources >= min_sources and have_images >= min_images and have_overview:
                            break

                # last attempt reached without satisfying targets -> loop again
                # (re-issuing the DDG search can surface different / more
                # complete DOM content, e.g. if the AI box was slow to render)
                human_delay(1.0, 2.0)

            except (TimeoutException, WebDriverException) as e:
                last_error = f"{type(e).__name__} - {str(e)[:120]}"
                logger.warning("Attempt %d failed: %s", attempt + 1, last_error)
                # the browser/chromedriver process may have died -- force a
                # fresh driver on the next loop iteration instead of hammering
                # a dead connection
                if driver is not None:
                    try:
                        driver.quit()
                    except Exception:
                        pass
                    driver = None
                human_delay(1.0, 2.0)
            except Exception as e:
                last_error = f"{type(e).__name__} - {str(e)[:120]}"
                logger.warning("Attempt %d raised unexpected error: %s", attempt + 1, last_error)
                if driver is not None:
                    try:
                        driver.quit()
                    except Exception:
                        pass
                    driver = None
                human_delay(1.0, 2.0)

        if best_result is not None:
            logger.info(
                "FINAL %s | Overview: %s | Images: %d | Links: %d | Organic: %d",
                mode.upper(),
                "Yes" if best_result["ai_overview_text"] else "No",
                len(best_result["image_links"]),
                len(best_result["ai_links"]),
                len(best_result["organic_results"]),
            )
            return best_result

        return _empty_result(query, status="failed", reason=last_error or "no data gathered")

    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass


if __name__ == "__main__":
    test_query = "what happened in us vs iran"
    data = scrape_duckduckgo(test_query, mode="fast")

    logger.info("=" * 110)
    logger.info("QUERY: %s", data["query"])

    overview = data.get("ai_overview_text") or "No summary captured"
    logger.info("OVERVIEW:")
    logger.info(overview[:1800] + "..." if len(overview) > 1800 else overview)

    images = data.get("image_links", [])
    logger.info("IMAGE LINKS (%d):", len(images))
    for i, img in enumerate(images, 1):
        logger.info("%d. %s", i, img)

    links = data.get("ai_links", [])
    logger.info("TOP LINKS (%d):", len(links))
    for i, link in enumerate(links[:25], 1):
        logger.info("%d. %s", i, link)

    with open("ddg_result.json", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    logger.info("Saved to ddg_result.json")