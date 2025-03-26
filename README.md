# Kagi Bridge MCP

This is a MCP (Multichannel Protocol) server that provides search capability using a headless browser. It simulates browser-based searches without requiring a Kagi API key.

## Usage

The MCP server requires a Session Token search service. You can get this by clicking on the "Copy" button aside of "Session Link" in Kage's [Control Center](https://kagi.com/settings?p=user_details). Only put the token part of the URL, not the full URL.

Then use the following command to start the server:

```bash
uvx kagi-bridge-mcp
```
