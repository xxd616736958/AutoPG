"""
WebSearch and WebFetch tools for db-claude.
Architecturally identical to Claude Code's WebSearchTool and WebFetchTool.
"""
from typing import Type
from pydantic import BaseModel, Field

from .base import Tool


class WebSearchInput(BaseModel):
    """Input schema for WebSearch tool."""
    query: str = Field(description="The search query to use", min_length=2)
    allowed_domains: list[str] = Field(default_factory=list, description="Only include results from these domains")
    blocked_domains: list[str] = Field(default_factory=list, description="Never include results from these domains")


class WebSearchTool(Tool):
    """Search the web and return results."""

    name = "WebSearch"
    aliases = []
    search_hint = "search the web for information"

    def input_schema(self) -> Type[BaseModel]:
        return WebSearchInput

    async def call(self, args: dict, context: dict) -> dict:
        """Search the web using a simple HTTP-based approach."""
        import httpx

        query = args.get("query", "")

        try:
            # Use DuckDuckGo's HTML search (no API key needed)
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    "https://html.duckduckgo.com/html/",
                    params={"q": query},
                    headers={"User-Agent": "db-claude/1.0"},
                )

                if resp.status_code != 200:
                    return {"data": f"Search failed with status {resp.status_code}"}

                # Basic HTML result extraction
                from html.parser import HTMLParser

                class ResultParser(HTMLParser):
                    def __init__(self):
                        super().__init__()
                        self.results = []
                        self.current = {}
                        self.in_result = False
                        self.in_snippet = False
                        self.text_content = ""

                    def handle_starttag(self, tag, attrs):
                        attrs_dict = dict(attrs)
                        if tag == "a" and "result__a" in attrs_dict.get("class", ""):
                            self.current = {"url": attrs_dict.get("href", ""), "title": "", "snippet": ""}
                            self.in_result = True
                        elif tag == "a" and "result__snippet" in attrs_dict.get("class", ""):
                            self.in_snippet = True

                    def handle_data(self, data):
                        if self.in_result and not self.current.get("title"):
                            self.current["title"] = data.strip()
                        elif self.in_snippet:
                            self.current["snippet"] += data

                    def handle_endtag(self, tag):
                        if tag == "a" and self.in_result:
                            if self.current.get("title"):
                                self.current["title"] = self.current["title"].strip()
                                self.current["snippet"] = self.current["snippet"].strip()
                                self.results.append(dict(self.current))
                            self.current = {}
                            self.in_result = False
                        elif tag == "a" and self.in_snippet:
                            self.in_snippet = False

                parser = ResultParser()
                parser.feed(resp.text)

                return {
                    "data": {
                        "query": query,
                        "count": len(parser.results),
                        "results": parser.results[:10],
                    },
                }
        except Exception as e:
            return {"data": f"Error during web search: {str(e)}\n\nNote: Web search requires internet connectivity."}

    async def description(self, input_schema: dict, options: dict) -> str:
        return "Search the web. Returns result blocks with titles and URLs."

    def is_read_only(self, input_data: dict = None) -> bool:
        return True

    def get_activity_description(self, input_data: dict = None) -> str:
        if not input_data:
            return "Searching the web"
        return f"Searching for '{input_data.get('query', '')}'"


# -- WebFetch --

class WebFetchInput(BaseModel):
    """Input schema for WebFetch tool."""
    url: str = Field(description="The URL to fetch content from")
    prompt: str = Field(description="The prompt to run on the fetched content")


class WebFetchTool(Tool):
    """Fetch a URL and convert to markdown."""

    name = "WebFetch"
    aliases = []
    search_hint = "fetch web page content and convert to text"

    def input_schema(self) -> Type[BaseModel]:
        return WebFetchInput

    async def call(self, args: dict, context: dict) -> dict:
        """Fetch a URL and extract its content."""
        import httpx

        url = args.get("url", "")
        prompt_text = args.get("prompt", "")

        # Upgrade HTTP to HTTPS
        if url.startswith("http://"):
            url = url.replace("http://", "https://", 1)

        try:
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                resp = await client.get(
                    url,
                    headers={"User-Agent": "db-claude/1.0"},
                )

                if resp.status_code != 200:
                    return {"data": f"Fetch failed: HTTP {resp.status_code}"}

                content_type = resp.headers.get("content-type", "")
                if "text/html" not in content_type:
                    return {"data": resp.text[:10000]}

                # Basic HTML to text conversion
                text = self._html_to_text(resp.text)

                # Truncate to reasonable size
                if len(text) > 50000:
                    text = text[:50000] + "\n\n... [content truncated]"

                return {
                    "data": {
                        "url": url,
                        "content_type": content_type,
                        "content": text,
                        "prompt": prompt_text if prompt_text else None,
                    },
                }
        except Exception as e:
            return {"data": f"Error fetching URL: {str(e)}"}

    def _html_to_text(self, html: str) -> str:
        """Basic HTML to text conversion."""
        import re

        # Remove scripts and styles
        html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)

        # Remove HTML tags
        text = re.sub(r"<[^>]+>", " ", html)

        # Normalize whitespace
        text = re.sub(r"\s+", " ", text)
        text = re.sub(r"\n\s*\n", "\n\n", text)

        return text.strip()

    async def description(self, input_schema: dict, options: dict) -> str:
        return "Fetches a URL and converts the page to markdown. Use for reading web content referenced in the conversation."

    def is_read_only(self, input_data: dict = None) -> bool:
        return True

    def get_activity_description(self, input_data: dict = None) -> str:
        if not input_data:
            return "Fetching URL"
        return f"Fetching {input_data.get('url', '')[:60]}"
