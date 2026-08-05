from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import StaleElementReferenceException, TimeoutException
import time
import random
import re
import json

def human_delay(min_sec=1.0, max_sec=3.0):
    time.sleep(random.uniform(min_sec, max_sec))

def create_driver():
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")
    
    driver = webdriver.Chrome(options=options)
    return driver

def safe_find_elements(driver, selector, timeout=10):
    try:
        WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, selector))
        )
        return driver.find_elements(By.CSS_SELECTOR, selector)
    except:
        return []

def scrape_google_ai(query, max_retries=3):
    for attempt in range(max_retries):
        driver = None
        try:
            driver = create_driver()
            driver.get("https://www.google.com")
            human_delay(2, 4)

            # Consent
            try:
                consent_btn = WebDriverWait(driver, 5).until(
                    EC.element_to_be_clickable((By.XPATH, "//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'agree') or contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'accept')]"))
                )
                consent_btn.click()
                human_delay(1, 2)
            except:
                pass

            # Search
            search_box = WebDriverWait(driver, 12).until(
                EC.presence_of_element_located((By.NAME, "q"))
            )
            search_box.clear()
            search_box.send_keys(query)
            search_box.submit()

            human_delay(5, 8)

            result = {
                "query": query,
                "ai_overview_text": None,
                "ai_links": [],
                "organic_results": [],
                "status": "success"
            }

            # === IMPROVED AI OVERVIEW DETECTION ===
            ai_selectors = [
                "div[data-attrid*='overview']",
                "block-component",
                "div[jsname='dvXlsc']",
                "div[aria-label*='AI']",
                "div.g > div > div > div > span",  # Common AI container
            ]

            ai_text = None
            all_links = []

            for selector in ai_selectors:
                elements = safe_find_elements(driver, selector, 8)
                for el in elements:
                    try:
                        text = el.text.strip()
                        if len(text) > 100:
                            ai_text = text
                            # Extract links safely
                            try:
                                links = el.find_elements(By.TAG_NAME, "a")
                                for link in links:
                                    href = link.get_attribute("href")
                                    if href and href.startswith("https://") and "google.com" not in href:
                                        clean = re.sub(r'(&|\?)(ei|ved|usg|sa|lei|hl|gl)=[^&]*', '', href)
                                        if clean not in all_links:
                                            all_links.append(clean)
                            except StaleElementReferenceException:
                                continue
                            break
                    except StaleElementReferenceException:
                        continue
                if ai_text:
                    break

            result["ai_overview_text"] = ai_text
            result["ai_links"] = all_links[:10]  # Top 10 links

            # Organic Results
            try:
                organic_blocks = driver.find_elements(By.CSS_SELECTOR, "div.g, div.MjjYud")
                for block in organic_blocks[:10]:
                    try:
                        title = block.find_element(By.CSS_SELECTOR, "h3").text
                        link = block.find_element(By.CSS_SELECTOR, "a").get_attribute("href")
                        if title and link:
                            result["organic_results"].append({"title": title[:100], "link": link})
                    except:
                        continue
            except:
                pass

            print(f"✅ Success | AI Overview: {'Yes' if ai_text else 'No'} | Links: {len(all_links)}")
            return result

        except Exception as e:
            print(f"Attempt {attempt+1}/{max_retries} failed: {type(e).__name__}")
            if attempt == max_retries - 1:
                return {"status": "failed", "reason": str(e)}
            human_delay(8, 15)
        finally:
            if driver:
                try:
                    driver.quit()
                except:
                    pass

# ========================= RUN =========================
if __name__ == "__main__":
    query = "what happen in us vs iran"
    data = scrape_google_ai(query)
    
    print("\n" + "="*80)
    print("QUERY:", data["query"])
    print("\nAI OVERVIEW:")
    print(data.get("ai_overview_text")[:700] + "..." if data.get("ai_overview_text") else "No AI Overview found")
    
    print("\nEXTRACTED LINKS:")
    for i, link in enumerate(data.get("ai_links", []), 1):
        print(f"{i}. {link}")
    
    with open("google_ai_result.json", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print("\n✅ Saved to google_ai_result.json")