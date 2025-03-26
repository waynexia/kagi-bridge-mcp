# Kagi Bridge MCP

This is a MCP (Multichannel Protocol) server that provides search capability using a headless browser. It simulates browser-based searches without requiring a Kagi API key.

## Installation

This project uses `uv` for dependency management:

```bash
# Install the package with dependencies
uv pip install .

# Install the browser binary
python -m playwright install chromium
```

## Usage

The MCP server requires a URL that contains an authentication token for the search service. This URL is used to initialize cookies that will be used for subsequent searches.

You can provide the URL in two ways:

1. Environment variable:
```bash
export SEARCH_URL="https://kagi.com/your_token_url"
kagi-bridge-mcp
```

2. Command-line argument:
```bash
kagi-bridge-mcp --url "https://kagi.com/your_token_url"
```

## Features

- Browser-based search that simulates real user interaction
- Handles 302 redirects and cookie-based authentication
- Compatible with existing MCP format for seamless integration

## Development

```bash
# Set up a development environment
uv venv
source .venv/bin/activate
uv sync
```