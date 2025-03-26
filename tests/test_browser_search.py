import os
import pytest
import asyncio
from unittest.mock import patch, MagicMock

from src.kagi_bridge_mcp.server import BrowserSearchClient


@pytest.mark.asyncio
async def test_browser_search_client_initialization():
    # Mock environment variable
    with patch.dict(os.environ, {"SEARCH_URL": "https://example.com/token"}):
        client = BrowserSearchClient()
        assert client.url == "https://example.com/token"


@pytest.mark.asyncio
async def test_browser_search_client_constructor_url():
    # Test direct URL passing
    client = BrowserSearchClient("https://direct.example.com/token")
    assert client.url == "https://direct.example.com/token"


@pytest.mark.asyncio
async def test_browser_search_client_missing_url():
    # Test error when URL is missing
    with patch.dict(os.environ, {}, clear=True):
        with pytest.raises(ValueError):
            client = BrowserSearchClient()


@pytest.mark.asyncio
async def test_browser_search():
    # Mock the playwright and browser interactions
    with patch("src.kagi_bridge_mcp.server.async_playwright") as mock_playwright:
        # Setup mocks
        mock_page = MagicMock()
        mock_page.evaluate.return_value = [
            {
                "t": 0,
                "title": "Test Result",
                "url": "https://example.com",
                "snippet": "This is a test",
            }
        ]

        mock_context = MagicMock()
        mock_context.new_page.return_value = mock_page

        mock_browser = MagicMock()
        mock_browser.new_context.return_value = mock_context

        mock_playwright_instance = MagicMock()
        mock_playwright_instance.chromium.launch.return_value = mock_browser

        mock_playwright.return_value.start.return_value = mock_playwright_instance

        # Create client and perform search
        client = BrowserSearchClient("https://example.com/token")
        result = await client.search("test query")

        # Verify results
        assert isinstance(result, dict)
        assert "data" in result

        # Verify the mocks were called correctly
        mock_page.goto.assert_any_call("https://example.com/token")
        mock_page.goto.assert_any_call("https://kagi.com/search?q=test query")
