"""
DuckDuckGo scraper (Selenium-based).

Design goals vs. the old version:
  - No hardcoded topic keywords ("US-Iran", "war", etc). Works for any query.
  - Correct boolean logic (the old code had an `or`/`and` precedence bug that
    let short, truncated overview boxes through).
  - Overview capture no longer grabs random page chunks (nav/footer/ads) --
    it scores candidate boxes and keeps the best one.
  - Cleaner separation of concerns: driver setup, overview extraction,
    organic result extraction, image extraction, and optional deep-mode 
    summarization are each their own function so they're easy to test/patch independently.
  - Driver is reused for deep-mode instead of spinning up a second one.
  - Consistent return shape even on failure, so callers can always do
    `data.get("ai_overview_text")` etc. without blowing up.
"""

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
import time
import random
import json
import logging
import sys

# IMPORTANT: this module can be imported inside an MCP stdio server process.
# MCP stdio servers treat every line written to stdout as a JSON-RPC message,
# so `print()` anywhere in here will corrupt the protocol and crash the
# client with "Failed to parse JSONRPC message from server". All diagnostic
# output must go to stderr instead (or a real logger), never stdout.
logging.basicConfig(level=logging.INFO, format="[duck_duck] %(message)s", stream=sys.stderr)
logger = logging.getLogger("duck_duck")


# ---------------------------------------------------------------------------
# Driver helpers
# ---------------------------------------------------------------------------

def human_delay(min_sec=0.5, max_sec=2.0):
    time.sleep(random.uniform(min_sec, max_sec))


def create_driver():
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-extensions")
    # Images must be enabled in the browser to ensure image nodes load in the DOM
    # options.add_argument("--disable-images")  <-- Removed to allow image scraping
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


# ---------------------------------------------------------------------------
# Image extraction
# ---------------------------------------------------------------------------
def extract_image_links(driver, limit=5, min_dim=80):
    """
    Extracts high-quality result images from the page.
    Filters out layout icons, tracking pixels, favicons, and SVGs by checking 
    dimensions and image formats.
    """
    valid_images = []
    
    # Priority selectors: target images inside organic results or module sidebars first
    selectors = [
        "[data-testid='result'] img", 
        ".module__image img", 
        ".zci__image img",
        "img" # Fallback to global if priority selectors yield nothing
    ]
    
    try:
        for selector in selectors:
            if len(valid_images) >= limit:
                break
                
            elements = driver.find_elements(By.CSS_SELECTOR, selector)
            for img in elements:
                if len(valid_images) >= limit:
                    break
                    
                src = img.get_attribute("src")
                if not src or src.startswith("data:image") or src in valid_images:
                    continue
                    
                # 1. Filter out obvious icons, vectors, and UI assets by keyword/extension
                low_src = src.lower()
                bad_markers = [".ico", ".svg", "favicon", "avatar", "logo", "asset", "pixel", "sprite"]
                if any(marker in low_src for marker in bad_markers):
                    continue
                    
                # 2. Size Validation: Eliminate low-res assets and tracking pixels
                try:
                    # Check natural DOM dimensions first
                    width = int(img.get_attribute("naturalWidth") or 0)
                    height = int(img.get_attribute("naturalHeight") or 0)
                    
                    # Fallback to layout dimensions if natural size isn't computed yet
                    if width == 0 or height == 0:
                        size = img.size
                        width = size.get("width", 0)
                        height = size.get("height", 0)
                        
                    if width < min_dim or height < min_dim:
                        continue
                except Exception:
                    # If we cannot verify dimensions, skip it to ensure quality control
                    continue
                    
                # 3. Domain Check
                if "external-content.duckduckgo.com" in src or (src.startswith("http") and "duckduckgo.com" not in src):
                    valid_images.append(src)
                    
    except Exception as e:
        logger.debug("Failed to extract images safely: %s", str(e))
        
    return valid_images

# ---------------------------------------------------------------------------
# Organic results extraction
# ---------------------------------------------------------------------------

def extract_organic_results(driver, limit=20):
    organic = []
    seen_links = set()

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
# Deep mode: visit top links and summarize
# ---------------------------------------------------------------------------

def get_page_summary(driver, url, max_chars=700):
    try:
        driver.get(url)
        human_delay(1.0, 2.0)
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


def scrape_duckduckgo(query, mode="fast", max_retries=2, organic_limit=20, image_limit=5):
    """
    mode: "fast" (search results page only) or "deep" (also visits top links
          and appends short page summaries to ai_overview_text).
    """
    last_error = ""

    for attempt in range(max_retries):
        driver = None
        try:
            driver = create_driver()
            driver.get(f"https://duckduckgo.com/?q={query.replace(' ', '+')}&ia=web")
            human_delay(1.5, 3.0)

            result = {
                "query": query,
                "ai_overview_text": extract_overview(driver),
                "ai_links": [],
                "image_links": extract_image_links(driver, limit=image_limit),
                "organic_results": [],
                "status": "success",
            }

            organic = extract_organic_results(
                driver, limit=45 if mode == "deep" else organic_limit
            )
            result["organic_results"] = organic
            result["ai_links"] = [item["link"] for item in organic][
                : 40 if mode == "deep" else 18
            ]

            if mode == "deep" and result["ai_links"]:
                summaries = deep_summarize(driver, result["ai_links"])
                if summaries:
                    extra = "\n\n".join(
                        f"Source: {s['url'][:80]}...\n{s['summary']}"
                        for s in summaries[:4]
                    )
                    result["ai_overview_text"] = (
                        f"{result['ai_overview_text']}\n\n{extra}"
                        if result["ai_overview_text"]
                        else extra
                    )

            logger.info(
                "DUCKDUCKGO %s | Overview: %s | Images: %d | Links: %d | Organic: %d",
                mode.upper(),
                "Yes" if result["ai_overview_text"] else "No",
                len(result["image_links"]),
                len(result["ai_links"]),
                len(organic),
            )
            return result

        except Exception as e:
            last_error = f"{type(e).__name__} - {str(e)[:120]}"
            logger.warning("Attempt %d failed: %s", attempt + 1, last_error)
        finally:
            if driver:
                try:
                    driver.quit()
                except Exception:
                    pass

    return _empty_result(query, status="failed", reason=last_error)


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