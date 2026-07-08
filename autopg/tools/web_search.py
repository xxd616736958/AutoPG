"""Web tools."""
import json, re
import httpx
from pydantic import Field
from langchain_core.tools import tool

@tool
async def web_search(
    query: str = Field(min_length=2, description="The search query"),
) -> str:
    """Search the web. Returns result blocks with titles and URLs."""
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            resp = await c.get("https://html.duckduckgo.com/html/", params={"q": query}, headers={"User-Agent": "autopg/1.0"})
        from html.parser import HTMLParser
        class P(HTMLParser):
            def __init__(s): super().__init__(); s.r=[]; s.cur={}; s.in_r=False
            def handle_starttag(s,t,a):
                ad=dict(a)
                if t=="a" and "result__a" in ad.get("class",""): s.cur={"url":ad.get("href",""),"title":"","snippet":""}; s.in_r=True
            def handle_data(s,d):
                if s.in_r and not s.cur.get("title"): s.cur["title"]=d.strip()
            def handle_endtag(s,t):
                if t=="a" and s.in_r:
                    if s.cur.get("title"): s.cur["title"]=s.cur["title"].strip(); s.r.append(dict(s.cur))
                    s.cur={}; s.in_r=False
        p=P(); p.feed(resp.text)
        return json.dumps({"query":query,"count":len(p.r),"results":p.r[:10]})
    except Exception as e: return json.dumps(f"Error during web search: {str(e)}")

@tool
async def web_fetch(
    url: str = Field(description="The URL to fetch content from"),
) -> str:
    """Fetch a URL and convert the page to text."""
    if url.startswith("http://"): url = url.replace("http://","https://",1)
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as c:
            resp = await c.get(url, headers={"User-Agent": "autopg/1.0"})
        text = resp.text
        text = re.sub(r"<script[^>]*>.*?</script>","",text,flags=re.DOTALL|re.I)
        text = re.sub(r"<style[^>]*>.*?</style>","",text,flags=re.DOTALL|re.I)
        text = re.sub(r"<[^>]+>"," ",text); text = re.sub(r"\s+"," ",text)
        if len(text)>50000: text=text[:50000]+"\n...[truncated]"
        return json.dumps({"url":url,"content":text.strip()})
    except Exception as e: return json.dumps(f"Error fetching URL: {str(e)}")
