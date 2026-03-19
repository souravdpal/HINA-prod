import requests
from bs4 import BeautifulSoup
import itertools
import time

from web_crwaler import summarize_web_data
HEADERS = {
    "User-Agent": "Mozilla/5.0"
}

# -----------------------
# expand messy queries
# -----------------------
def expand_query(q):
    words = q.lower().split()
    combos=set()

    for r in range(2, min(len(words),4)+1):
        for p in itertools.permutations(words,r):
            combos.add(" ".join(p))

    combos.add(q)
    return list(combos)

# -----------------------
# search duckduckgo
# -----------------------
def search_ddg(query):

    url="https://html.duckduckgo.com/html/"
    r=requests.post(url,data={"q":query},headers=HEADERS)

    soup=BeautifulSoup(r.text,"html.parser")

    links=[]
    for a in soup.select("a.result__a"):
        links.append(a["href"])

    return links[:5]

# -----------------------
# fetch page
# -----------------------
def fetch_page(url):

    try:
        r=requests.get(url,headers=HEADERS,timeout=10)
        return r.text
    except:
        return ""

# -----------------------
# extract readable text
# -----------------------
def extract_text(html):

    soup=BeautifulSoup(html,"html.parser")

    paragraphs=soup.find_all("p")

    text=[]
    for p in paragraphs:
        t=p.get_text().strip()

        if len(t)>80:
            text.append(t)

    return " ".join(text)

# -----------------------
# research pipeline
# -----------------------
def research(query):

    queries=expand_query(query)

    all_links=set()
    collected=""

    for q in queries:

        links=search_ddg(q)

        for link in links:

            if link in all_links:
                continue

            all_links.add(link)

            html=fetch_page(link)

            if not html:
                continue

            text=extract_text(html)

            if text:
                collected+=text[:2000]+"\n\n"

            time.sleep(1)

        if len(all_links)>=6:
            break

    return collected

def web_return(q):
    print("searching.....")
    data=research(query=q)
    print("searching...")
    if not data:
        print("No text extracted")
    else:
        print("summarizing...")
        return_dat = data[:2000]
        print(return_dat)
        rt = summarize_web_data(user_query=q,web_data=return_dat)
        from hina_brain import model_res
        model_res(up=q,sec_data=str(rt))

