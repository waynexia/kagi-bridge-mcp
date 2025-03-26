import textwrap
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import os
import argparse
import urllib.parse
import atexit
import signal
import threading
from typing import Optional
import time
import logging  # Add logging module

from playwright.async_api import async_playwright
from pydantic import Field

from mcp.server.fastmcp import FastMCP

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Global variables for search client and asyncio event loop
search_client = None
_loop = None
_loop_thread = None


def get_event_loop():
    """Get or create an event loop running in a background thread."""
    global _loop, _loop_thread

    if _loop is None:
        # Create a new loop
        _loop = asyncio.new_event_loop()

        # Define the thread target function
        def loop_thread_func():
            asyncio.set_event_loop(_loop)
            _loop.run_forever()

        # Start the thread
        _loop_thread = threading.Thread(target=loop_thread_func, daemon=True)
        _loop_thread.start()

    return _loop


def run_async(coro):
    """Run an async function from a synchronous context."""
    loop = get_event_loop()
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result()


class BrowserSearchClient:
    """A client that performs searches using a headless browser."""

    def __init__(self, url: Optional[str] = None):
        """Initialize with an optional URL that contains the authentication token."""
        token = os.environ.get("SESSION_TOKEN") or ""
        # self.url = url or os.environ.get("SESSION_TOKEN")
        self.url = f"https://kagi.com/search?token={token}" if not url else url
        if not self.url:
            raise ValueError(
                "Search URL must be provided either in constructor or as SESSION_TOKEN environment variable"
            )
        logger.info(f"Initialized BrowserSearchClient with URL type: {type(self.url)}")
        self.browser = None
        self.context = None

    async def initialize(self):
        """Initialize the browser and context."""
        logger.info("Initializing browser and context")
        playwright = await async_playwright().start()
        self.browser = await playwright.chromium.launch(headless=True)
        self.context = await self.browser.new_context()

        # Handle authentication by visiting the URL that sets cookies
        page = await self.context.new_page()
        try:
            logger.info(
                f"Navigating to authentication URL: {self.url} (type: {type(self.url)})"
            )
            if isinstance(self.url, dict):
                # If URL is accidentally a dict, try to extract the string URL
                logger.warning(f"URL is a dictionary instead of string: {self.url}")
                if "url" in self.url:
                    self.url = self.url["url"]
                    logger.info(f"Extracted URL from dictionary: {self.url}")
                else:
                    raise ValueError(f"Invalid URL object: {self.url}")

            # auth_url = f"https://kagi.com/search?token={self.url}"
            await page.goto(self.url)
            await page.wait_for_load_state("networkidle")
        except Exception as e:
            logger.error(f"Error during initialization: {str(e)}")
            raise
        finally:
            await page.close()

    async def close(self):
        """Close the browser and clean up resources."""
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()

    async def search(self, query: str) -> dict:
        """Perform a search using the headless browser and extract search results."""
        if not self.browser or not self.context:
            await self.initialize()

        page = await self.context.new_page()
        try:
            # Navigate to the search page with the query
            encoded_query = urllib.parse.quote(query)
            search_url = f"{self.url}&q={encoded_query}"
            logger.info(f"Searching with query: '{query}'")
            logger.info(f"Search URL: {search_url}")

            await page.goto(search_url)
            await page.wait_for_load_state("networkidle")

            # Extract search results
            results = await page.evaluate(
                """
                () => {
                    const results = [];
                    
                    // New extraction logic based on the example HTML structure
                    const resultElements = document.querySelectorAll('div.search-result, div._0_result-item');
                    
                    resultElements.forEach(element => {
                        // Try to find title and URL
                        const titleElement = element.querySelector('.heading a, ._0_result-title a');
                        
                        // Look for URL element or extract from title's href
                        const urlElement = element.querySelector('.url, .__sri-url');
                        const url = urlElement ? 
                            (urlElement.href || urlElement.getAttribute('href')) : 
                            (titleElement ? titleElement.href : null);
                            
                        // Try various selectors for snippet content
                        const snippetElement = element.querySelector('.snippet, ._0_DESC, .__sri-desc div');
                        
                        // Try to find published date
                        const publishedElement = element.querySelector('.published');
                        
                        if (titleElement && (snippetElement || url)) {
                            results.push({
                                t: 0,  // Mimicking the original API's type identifier for search results
                                title: titleElement.textContent.trim(),
                                url: url,
                                snippet: snippetElement ? snippetElement.textContent.trim() : "",
                                published: publishedElement ? publishedElement.textContent.trim() : null
                            });
                        }
                    });
                    
                    // If no results found, try an even more general approach
                    if (results.length === 0) {
                        // Look for any article or result-like elements
                        document.querySelectorAll('article, ._ext_a, div[class*="result"]').forEach(element => {
                            // Try to extract anything that looks like a result
                            const titleElement = element.querySelector('h3 a, h2 a, a[class*="title"]');
                            const contentElement = element.querySelector('p, div[class*="desc"], div[class*="content"]');
                            const linkElement = element.querySelector('a[href]');
                            
                            const title = titleElement ? titleElement.textContent.trim() : 
                                         (element.querySelector('h3, h2') ? element.querySelector('h3, h2').textContent.trim() : null);
                            const url = titleElement ? titleElement.href : 
                                      (linkElement ? linkElement.href : null);
                            const snippet = contentElement ? contentElement.textContent.trim() : "";
                            
                            if ((title || url) && snippet) {
                                results.push({
                                    t: 0,
                                    title: title || "No title",
                                    url: url || "",
                                    snippet: snippet,
                                    published: null
                                });
                            }
                        });
                    }
                    
                    return results;
                }
            """
            )

            return {"data": results}

        finally:
            await page.close()


# Initialize the MCP server
mcp = FastMCP("kagi-bridge-mcp", dependencies=["playwright", "mcp[cli]"])


# Cleanup function to ensure browser is closed
def cleanup():
    global search_client, _loop
    if search_client:
        try:
            if _loop:
                # Schedule the close in the event loop
                future = asyncio.run_coroutine_threadsafe(search_client.close(), _loop)
                future.result(timeout=30)  # Wait for up to 5 seconds

                # Stop the loop
                _loop.call_soon_threadsafe(_loop.stop)
        except Exception as e:
            print(f"Error closing browser: {str(e)}")


# Register cleanup handlers
atexit.register(cleanup)
signal.signal(signal.SIGINT, lambda sig, frame: (cleanup(), exit(0)))
signal.signal(signal.SIGTERM, lambda sig, frame: (cleanup(), exit(0)))


@mcp.tool()
def search(
    queries: list[str] = Field(
        description="One or more concise, keyword-focused search queries. Include essential context within each query for standalone use."
    ),
) -> str:
    """Perform web search based on one or more queries. Results are from all queries given. They are numbered continuously, so that a user may be able to refer to a result by a specific number."""
    global search_client

    try:
        if not queries:
            raise ValueError("Search called with no queries.")

        logger.info(f"Search tool called with queries: {queries}")

        # Initialize the search client if not already done
        if not search_client:
            token = os.environ.get("SESSION_TOKEN")
            search_url = f"https://kagi.com/search?token={token}" if token else None
            if not search_url:
                raise ValueError("No SESSION_TOKEN found in environment variables.")
            logger.info(
                f"Creating search client with URL from env: {search_url} (type: {type(search_url)})"
            )
            search_client = BrowserSearchClient(search_url)

        # Define the async search function
        async def search_all():
            # Initialize client if needed
            await search_client.initialize()

            # Search for each query
            results = []
            for query in queries:
                max_retries = 3
                for attempt in range(max_retries):
                    try:
                        logger.info(
                            f"Attempting search for '{query}', attempt {attempt+1}/{max_retries}"
                        )
                        result = await search_client.search(query)
                        results.append(result)
                        break
                    except Exception as e:
                        logger.error(
                            f"Search attempt {attempt+1} for '{query}' failed: {str(e)}"
                        )
                        if attempt == max_retries - 1:
                            # Last attempt failed, re-raise the exception
                            raise
                        # Log the error and retry
                        print(
                            f"Search attempt {attempt+1} for '{query}' failed: {str(e)}. Retrying..."
                        )
                        # Reinitialize browser in case of issues
                        await search_client.close()
                        await search_client.initialize()
            return results

        # Run the async function using our utility
        results = run_async(search_all())
        return format_search_results(queries, results)

    except Exception as e:
        error_msg = f"Error: {str(e) or repr(e)}"
        logger.error(error_msg)
        return error_msg


def format_search_results(queries: list[str], responses) -> str:
    """Formatting of results for response. Need to consider both LLM and human parsing."""

    result_template = textwrap.dedent(
        """
        {result_number}: {title}
        {url}
        Published Date: {published}
        {snippet}
    """
    ).strip()

    query_response_template = textwrap.dedent(
        """
        -----
        Results for search query \"{query}\":
        -----
        {formatted_search_results}
    """
    ).strip()

    per_query_response_strs = []

    start_index = 1
    for query, response in zip(queries, responses):
        # t == 0 is search result, t == 1 is related searches
        results = [result for result in response["data"] if result["t"] == 0]

        # published date is not always present
        formatted_results_list = [
            result_template.format(
                result_number=result_number,
                title=result["title"],
                url=result["url"],
                published=result.get("published", "Not Available"),
                snippet=result["snippet"],
            )
            for result_number, result in enumerate(results, start=start_index)
        ]

        start_index += len(results)

        formatted_results_str = "\n\n".join(formatted_results_list)
        query_response_str = query_response_template.format(
            query=query,
            formatted_search_results=formatted_results_str,
        )
        per_query_response_strs.append(query_response_str)

    return "\n\n".join(per_query_response_strs)


def main():
    mcp.run()


if __name__ == "__main__":
    main()
