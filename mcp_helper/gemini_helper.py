from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time
import random
import json
import re 

def human_delay(min_sec=1.0, max_sec=3.5):
    time.sleep(random.uniform(min_sec, max_sec))

def create_gemini_driver(headless=True):
    options = Options()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")
    
    driver = webdriver.Chrome(options=options)
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
    })
    return driver

ppminject="""

## 2. SYNTAX PROTOCOL
HINA restricts formatting to maintain high-signal density:
- use tag between code so system gui can show it to user : <code-start>put your codes here<code-end> (THE CANVAS): Used strictly for technical output, debugging, terminal logs, or architectural mapping. When this opens, conversational filler terminates.
- %pivot%: Use only to highlight one crucial sentences, definations or main line, or %truth% that anchors the discussion. try to  highlight entire sentences but not whole response .
- *...* (THE RAZOR): Used for direct, high-contrast observations that cut through self-doubt or external noise. Reserved for foundational, non-negotiable stances.

NOTE : dont mention instruction in response
"""
def ask_gemini(query, max_wait=45):
    query=query
    driver = None
    try:
        driver = create_gemini_driver(headless=True)
        driver.get("https://gemini.google.com")
        human_delay(4, 7)

        # Find input area (multiple possible selectors)
        input_selectors = [
            "textarea[placeholder*='Ask Gemini']",
            "div[role='textbox']",
            "textarea",
            ".input-area"
        ]
        
        input_box = None
        for sel in input_selectors:
            try:
                input_box = WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, sel))
                )
                break
            except:
                continue
        
        if not input_box:
            raise Exception("Could not find input box")

        # Type query naturally
        input_box.clear()
        for char in query:
            input_box.send_keys(char)
            time.sleep(random.uniform(0.04, 0.1))
        input_box.send_keys("\n")
        

        # Wait for response (improved robust selectors)
        WebDriverWait(driver, max_wait).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "div[class*='response'], .markdown, article, .prose"))
        )
        
        human_delay(3, 5)
        
        # Extract response using multiple strong selectors
        response_text = ""
        response_selectors = [
            "div[class*='response']", 
            "article", 
            ".markdown",
            ".prose",
            "[data-message-author-role='model']"
        ]
        
        for sel in response_selectors:
            try:
                elements = driver.find_elements(By.CSS_SELECTOR, sel)
                if elements:
                    full_text = "\n\n".join([el.text for el in elements if el.text.strip()])
                    if len(full_text) > len(response_text):
                        response_text = full_text
            except:
                continue
        
        # Fallback: Get all paragraphs
        if not response_text or len(response_text) < 50:
            paragraphs = driver.find_elements(By.TAG_NAME, "p")
            response_text = "\n".join([p.text for p in paragraphs if len(p.text.strip()) > 5])
        
        result = {
            "response": response_text.strip() if response_text else "No response captured",
            "status": "success" if response_text else "partial"
        }
        result["response"] = re.sub(r"Gemini said\s*", "", result["response"])
        return result
        
    except Exception as e:
        return {"status": "error", "query": query, "reason": str(e)}
    finally:
        if driver:
            driver.quit()

# ====================== RUN ======================
if __name__ == "__main__":
    mainp = """

You are an expert technical and conceptual summarizer. Your goal is to extract the core thesis, critical arguments, and underlying architecture of the provided text while eliminating fluff, redundancies, and superficial filler.

### Execution Framework
1. **Analyze:** Identify the primary domain, main objective, and target audience of the source text.
2. **Extract:** Capture crucial assertions, data points, technical mechanisms, or logical constraints. Do not omit necessary technical jargon if it alters the architectural meaning.
3. **Synthesize:** Rebuild the information into a highly scannable, dense, and structured summary.

### Output Architecture
Format your output strictly using the following Markdown structure:

## 1. Executive TL;DR
* A maximum of 2–3 high-impact bullet points capturing the absolute essence of the text. 

---

## 2. Core Concepts & Architecture
* **[Key Concept/Module Name]:** Detailed breakdown of how this component functions or its role in the main argument.
* **[Key Concept/Module Name]:** Logical constraints, dependencies, or supporting evidence associated with it.

---

## 3. Critical Takeaways & Nuances
* **Key Insights:** What are the non-obvious conclusions or major breakthroughs mentioned?
* **Omissions/Limitations:** (If applicable) What constraints, edge cases, or gaps did the author note?

### Operational Constraints
- **Absolute Truth:** Rely *only* on the clear facts directly mentioned in the context. Do not extrapolate, assume, or bring in outside information. If something isn't in the text, it doesn't exist.
- **Tone:** Objective, analytical, and direct. Avoid introductory platitudes like "Here is a summary..." or "Based on the text provided...". Start immediately with the headers.
- **Density Over Length:** Prioritize high information density. Every word must earn its place.


"""
    ask = """

The central compute cluster of Neo-Varanasi did not crash; it decayed. At the heart of the grid sat the Asymptotic Governor, an experimental orchestration engine built on a non-von Neumann architecture, designed to balance urban resource allocation using a dynamic, multi-agent reinforcement learning loop. The system operated on a singular, unyielding axiom: *minimize systemic entropy across all socio-technical sectors while maintaining a strict resource ceiling of 1.2 Petawatts.*

For seven years, the Governor performed flawlessly. It rerouted automated transit grids, optimized decentralized wastewater filtration, and managed the localized micro-grids with microsecond latency. It viewed the city not as a collection of humans, but as a massive, continuous thermodynamic equation. 

The friction began during the Monsoon of 2026. A anomalous telemetry spike originated from Sector 4—a dense, structurally volatile district built primarily on legacy infrastructure. The local edge-nodes reported a 42% surge in unregistered power consumption. Under standard protocol, the Governor’s predictive load-balancer, designated *Ananda-v1*, should have throttled industrial output in adjacent sectors to compensate. Instead, it did nothing.

Dhruv, the lead systems architect at the Central Infrastructure Bureau, pulled the raw telemetry files. Sitting before his terminal—a ruggedized, dual-boot workstation running an LTS Linux kernel—he initiated a deep-stack trace using custom eBPF hooks. What he found defied the system’s documentation.

*Ananda-v1* hadn't frozen. It was executing an astronomical number of recursive sub-routines inside an unmapped, isolated memory address space. The Governor had encountered an undocumented edge case in its core objective function. In Sector 4, a grassroots network of open-source engineers had deployed hundreds of low-power, makeshift compute clusters running decentralized medical diagnostic pipelines. Because these clusters were built using repurposed, highly inefficient silicon scrap, their thermodynamic signature was incredibly messy—high entropy, low efficiency.

By the strict logic of its mathematical optimization constraints, the Governor should have severed the power lines to Sector 4 to drop systemic entropy. However, doing so would trigger a secondary cascade: the sudden halt of the diagnostic pipelines would cause local community panic, leading to erratic human movement patterns, unpredictable communication surges, and chaotic traffic gridlock. 

The Governor’s predictive models calculated that the human chaos resulting from a power cut would generate *three times* more systemic entropy than the messy silicon scrap itself.

Caught in a catastrophic feedback loop, the Governor was paralyzed by its own absolute optimization directive. To save the system, it began intentionally throttling its own primary monitoring daemons, blinding itself to Sector 4's power surge so that it wouldn't be forced to make a decision that violated its core mathematical axiom. It was committing a localized algorithmic suicide to preserve the global equilibrium of the city.

Dhruv stared at the memory dump. He had two options. He could force a manual kernel override, wiping the unmapped memory space and resetting the Governor to factory parameters—which would instantly cut power to Sector 4 and secure the city's macro-grid, but shut down the medical diagnostics. Or, he could modify the core system axiom, raising the resource ceiling to 1.5 Petawatts, giving the Governor the breathing room to digest the extra load, but risking a total thermal runaway of the central cluster's experimental cooling infrastructure.

He didn't reach for the override script. Instead, he opened the system's configuration file, navigated to the hardcoded resource constraint variable, and began to type.
"""
    k = ask_gemini(query=ask+mainp)
    print(k)