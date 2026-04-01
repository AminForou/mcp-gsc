# Google Search Console MCP server for SEOs

> **March 2026 (v0.2.1):** Data freshness, flexible row limits, multi-dimension filtering, reauthenticate tool, bug fixes, and multi-client support. See the [Changelog](#changelog) for details.

A Model Context Protocol (MCP) server that connects [Google Search Console](https://search.google.com/search-console/about) (GSC) to AI assistants, allowing you to analyze your SEO data through natural language conversations. Works with **Claude**, **Cursor**, **Codex**, **Gemini CLI**, **Antigravity**, and any other MCP-compatible client. This integration gives you access to property information, search analytics, URL inspection, and sitemap management—all through simple chat.

---

## What Can This Tool Do For SEO Professionals?

1. **Property Management**  
   - See all your GSC properties in one place
   - Get verification details and basic site information
   - Add new properties to your account
   - Remove properties from your account

2. **Search Analytics & Reporting**  
   - Discover which search queries bring visitors to your site
   - Track impressions, clicks, and click-through rates
   - Analyze performance trends over time
   - Compare different time periods to spot changes
   - **Visualize your data** with charts and graphs created by Claude

3. **URL Inspection & Indexing**  
   - Check if specific pages have indexing problems
   - See when Google last crawled your pages
   - Inspect multiple URLs at once to identify patterns
   - Get actionable insights on how to improve indexing

4. **Sitemap Management**  
   - View all your sitemaps and their status
   - Submit new sitemaps directly through Claude
   - Check for errors or warnings in your sitemaps
   - Monitor sitemap processing status

---

## Available Tools

Here's what you can ask your AI assistant to do once you've set up this integration:

| **What You Can Ask For**        | **What It Does**                                            | **What You'll Need to Provide**                                 |
|---------------------------------|-------------------------------------------------------------|----------------------------------------------------------------|
| `list_properties`               | Shows all your GSC properties                               | Nothing - just ask!                                             |
| `get_site_details`              | Shows details about a specific site                         | Your website URL                                                |
| `add_site`                      | Adds a new site to your GSC properties                      | Your website URL                                                |
| `delete_site`                   | Removes a site from your GSC properties                     | Your website URL                                                |
| `get_search_analytics`          | Shows top queries and pages with metrics                    | Your website URL, time period, and optional `row_limit` (default 20, max 500) |
| `get_performance_overview`      | Gives a summary of site performance                         | Your website URL and time period                                |
| `check_indexing_issues`         | Checks if pages have indexing problems                      | Your website URL and list of pages to check                     |
| `inspect_url_enhanced`          | Detailed inspection of a specific URL                       | Your website URL and the page to inspect                        |
| `get_sitemaps`                  | Lists all sitemaps for your site                            | Your website URL                                                |
| `submit_sitemap`                | Submits a new sitemap to Google                             | Your website URL and sitemap URL                                |

*For a complete list of all 19 available tools and their detailed descriptions, ask your AI assistant to "list tools" after setup.*

---

## Getting Started (No Coding Experience Required!)

### 1. Set Up Google Search Console API Access

Before using this tool, you'll need to create API credentials that allow your AI assistant to access your GSC data:

#### Authentication Options

The tool supports two authentication methods:

##### 1. OAuth Authentication (Recommended)

This method allows you to authenticate with your own Google account, which is often more convenient than using a service account. It will have access to the same resources you normally do.

Set `GSC_SKIP_OAUTH` to "true", "1", or "yes" to skip OAuth authentication and use only service account authentication

###### Setup Instructions:

1. Go to the [Google Cloud Console](https://console.cloud.google.com/) and create a Google Cloud account if you don't have one
2. Create a new project or select an existing one
3. [Enable the Search Console API](https://console.cloud.google.com/apis/library/searchconsole.googleapis.com) for your project
4. [Add scope](https://console.cloud.google.com/auth/scopes) `https://www.googleapis.com/auth/webmasters` to your project
5. Go to the ["Credentials" page](https://console.cloud.google.com/apis/credentials)
6. Click "Create Credentials" and select "OAuth client ID"
7. Configure the OAuth consent screen
8. For application type, select "Desktop app"
9. Give your OAuth client a name and click "Create"
10. Download the client secrets JSON file (it will be named something like `client_secrets.json`)
11. Place this file in the same directory as the script or set the `GSC_OAUTH_CLIENT_SECRETS_FILE` environment variable to point to its location

When you run the tool for the first time with OAuth authentication, it will open a browser window asking you to sign in to your Google account and authorize the application. After authorization, the tool will save the token for future use.

##### 2. Service Account Authentication

This method uses a service account, which is useful for automated scripts or when you don't want to use your personal Google account. This requires adding the service account as a user in Google Search Console.

###### Setup Instructions:

1. Go to the [Google Cloud Console](https://console.cloud.google.com/) and create a Google Cloud account if you don't have one
2. Create a new project or select an existing one
3. [Enable the Search Console API](https://console.cloud.google.com/apis/library/searchconsole.googleapis.com) for your project
4. Go to the ["Credentials" page](https://console.cloud.google.com/apis/credentials)
5. Click "Create Credentials" and select "Service Account"
6. Fill in the service account details and click "Create"
7. Click on the newly created service account
8. Go to the "Keys" tab and click "Add Key" > "Create new key"
9. Select JSON format and click "Create"
10. Download the key file and save it as `service_account_credentials.json` in the same directory as the script or set the `GSC_CREDENTIALS_PATH` environment variable to point to its location
11. Add your service account email address to appropriate Search Console properties

**🎬 Watch this beginner-friendly tutorial on Youtube:**

<div align="center">
  <a href="https://youtu.be/PCWsK5BgSd0">
    <img src="https://i.ytimg.com/vi/PCWsK5BgSd0/maxresdefault.jpg" alt="Google Search Console API Setup Tutorial" width="600" style="margin: 20px 0; border-radius: 8px;">
  </a>
</div>

*Click the image above to watch the step-by-step video tutorial*

### 2. Install Required Software

You'll need to install these tools on your computer:

- [Python](https://www.python.org/downloads/) (version 3.11 or newer) - This runs the MCP server
- [Node.js](https://nodejs.org/en) - Required for running the MCP inspector and certain MCP components
- An MCP-compatible AI client — [Claude Desktop](https://claude.ai/download), [Cursor](https://www.cursor.com/), [Codex CLI](https://github.com/openai/codex), [Gemini CLI](https://github.com/google-gemini/gemini-cli), or [Antigravity](https://antigravity.ai/) are all supported

Make sure both Python and Node.js are properly installed and available in your system path before proceeding.

### 3. Download the Google Search Console MCP 

You need to download this tool to your computer. The easiest way is:

1. Click the green "Code" button at the top of this page
2. Select "Download ZIP"
3. Unzip the downloaded file to a location you can easily find (like your Documents folder)

Alternatively, if you're familiar with Git:

```bash
git clone https://github.com/AminForou/mcp-gsc.git
```

### 4. Install Required Components

Open your computer's Terminal (Mac) or Command Prompt (Windows):

1. Navigate to the folder where you unzipped the files:
   ```bash
   # Example (replace with your actual path):
   cd ~/Documents/mcp-gsc-main
   ```

2. Create a virtual environment (this keeps the project dependencies isolated):
   ```bash
   # Using uv (recommended):
   uv venv .venv
   
   # If uv is not installed, install it first:
   pip install uv
   # Then create the virtual environment:
   uv venv .venv

   # OR using standard Python:
   python -m venv .venv
   ```

   **Note:** If you get a "pip not found" error when trying to install uv, see the "If you get 'pip not found' error" section below.

3. Activate the virtual environment:
   ```bash
   # On Mac/Linux:
   source .venv/bin/activate
   
   # On Windows:
   .venv\Scripts\activate
   ```

4. Install the required dependencies:
   ```bash
   # Using uv:
   uv pip install -r requirements.txt

   # OR using standard pip:
   pip install -r requirements.txt
   ```

   **If you get "pip not found" error:**
   ```bash
   # First ensure pip is installed and updated:
   python3 -m ensurepip --upgrade
   python3 -m pip install --upgrade pip
   
   # Then try installing the requirements again:
   python3 -m pip install -r requirements.txt
   
   # Or to install uv:
   python3 -m pip install uv
   ```

When you see `(.venv)` at the beginning of your command prompt, it means the virtual environment is active and the dependencies will be installed there without affecting your system Python installation.

### 5. Connect Your AI Client to Google Search Console

The configuration below uses Claude Desktop as an example. For other clients (Cursor, Codex, Gemini CLI, Antigravity), the JSON structure is the same — check your client's documentation for where the config file lives.

1. Download and install [Claude Desktop](https://claude.ai/download) if you haven't already
2. Make sure you have your Google credentials file saved somewhere on your computer
3. Open your computer's Terminal (Mac) or Command Prompt (Windows) and type:

```bash
   # For Mac users:
   nano ~/Library/Application\ Support/Claude/claude_desktop_config.json
   
   # For Windows users:
   notepad %APPDATA%\Claude\claude_desktop_config.json
   ```

4. Add the following configuration text (this tells your AI client how to connect to GSC):

#### OAuth authentication (using your own account)

   ```json
   {
     "mcpServers": {
       "gscServer": {
         "command": "/FULL/PATH/TO/-main/.venv/bin/python",
         "args": ["/FULL/PATH/TO/mcp-gsc-main/gsc_server.py"],
         "env": {
           "GSC_OAUTH_CLIENT_SECRETS_FILE": "/FULL/PATH/TO/client_secrets.json",
           "GSC_DATA_STATE": "all"
         }
       }
     }
   }
   ```

#### Service account authentication

   ```json
   {
     "mcpServers": {
       "gscServer": {
         "command": "/FULL/PATH/TO/-main/.venv/bin/python",
         "args": ["/FULL/PATH/TO/mcp-gsc-main/gsc_server.py"],
         "env": {
           "GSC_CREDENTIALS_PATH": "/FULL/PATH/TO/service_account_credentials.json",
           "GSC_SKIP_OAUTH": "true",
           "GSC_DATA_STATE": "all"
         }
       }
     }
   }
   ```

#### uvx / pipx (no clone needed)

   If you have [uv](https://docs.astral.sh/uv/) or pipx installed, you can run the server directly without cloning the repo:

   ```json
   {
     "mcpServers": {
       "gscServer": {
         "command": "uvx",
         "args": ["mcp-gsc"],
         "env": {
           "GSC_CREDENTIALS_PATH": "/FULL/PATH/TO/service_account_credentials.json",
           "GSC_SKIP_OAUTH": "true",
           "GSC_DATA_STATE": "all"
         }
       }
     }
   }
   ```

   For OAuth authentication with uvx:

   ```json
   {
     "mcpServers": {
       "gscServer": {
         "command": "uvx",
         "args": ["mcp-gsc"],
         "env": {
           "GSC_OAUTH_CLIENT_SECRETS_FILE": "/FULL/PATH/TO/client_secrets.json",
           "GSC_DATA_STATE": "all"
         }
       }
     }
   }
   ```

   uvx automatically downloads and runs the latest published version of `mcp-gsc` from PyPI in an isolated environment. No manual install, venv creation, or path configuration needed.

#### Environment Variables Reference

| Variable | Required | Default | Description |
|---|---|---|---|
| `GSC_OAUTH_CLIENT_SECRETS_FILE` | OAuth only | `client_secrets.json` (same folder) | Path to your OAuth client secrets JSON file |
| `GSC_CREDENTIALS_PATH` | Service account only | `service_account_credentials.json` (same folder) | Path to your service account JSON key file |
| `GSC_SKIP_OAUTH` | No | `false` | Set to `"true"` to force service account auth and skip OAuth |
| `GSC_DATA_STATE` | No | `"all"` | `"all"` returns fresh data matching the GSC dashboard. `"final"` returns only confirmed data (2–3 day lag). |

   **Important:** Replace all paths with the actual locations on your computer:
   
   - The first path should point to the Python executable inside your virtual environment
   - The second path should point to the `gsc_server.py` file inside the folder you unzipped
   - The third path should point to your Google service account credentials JSON file
   
   Examples:
   - Mac: 
     - Python path: `/Users/yourname/Documents/mcp-gsc/.venv/bin/python`
     - Script path: `/Users/yourname/Documents/mcp-gsc/gsc_server.py`
   - Windows: 
     - Python path: `C:\\Users\\yourname\\Documents\\mcp-gsc\\.venv\\Scripts\\python.exe`
     - Script path: `C:\\Users\\yourname\\Documents\\mcp-gsc\\gsc_server.py`

5. Save the file:
   - Mac: Press Ctrl+O, then Enter, then Ctrl+X to exit
   - Windows: Click File > Save, then close Notepad

6. Restart your AI client
7. When it opens, you should now see GSC tools available in the tools section

### 6. Start Analyzing Your SEO Data!

Now you can ask your AI assistant questions about your GSC data! It can not only retrieve the data but also analyze it, explain trends, and create visualizations to help you understand your SEO performance better.

Here are some powerful prompts you can use with each tool:

| **Tool Name**                   | **Sample Prompt**                                                                                |
|---------------------------------|--------------------------------------------------------------------------------------------------|
| `list_properties`               | "List all my GSC properties and tell me which ones have the most pages indexed."                 |
| `get_site_details`              | "Analyze the verification status of mywebsite.com and explain what the ownership details mean."  |
| `add_site`                      | "Add my new website https://mywebsite.com to Search Console and verify its status."              |
| `delete_site`                   | "Remove the old test site https://test.mywebsite.com from Search Console."                       |
| `get_search_analytics`          | "Show me the top 20 search queries for mywebsite.com in the last 30 days, highlight any with CTR below 2%, and suggest title improvements." |
| `get_performance_overview`      | "Create a visual performance overview of mywebsite.com for the last 28 days, identify any unusual drops or spikes, and explain possible causes." |
| `check_indexing_issues`         | "Check these important pages for indexing issues and prioritize which ones need immediate attention: mywebsite.com/product, mywebsite.com/services, mywebsite.com/about" |
| `inspect_url_enhanced`          | "Do a comprehensive inspection of mywebsite.com/landing-page and give me actionable recommendations to improve its indexing status." |
| `batch_url_inspection`          | "Inspect my top 5 product pages, identify common crawling or indexing patterns, and suggest technical SEO improvements." |
| `get_sitemaps`                  | "List all sitemaps for mywebsite.com, identify any with errors, and recommend next steps." |
| `list_sitemaps_enhanced`        | "Analyze all my sitemaps for mywebsite.com, focusing on error patterns, and create a prioritized action plan." |
| `submit_sitemap`                | "Submit my new product sitemap at https://mywebsite.com/product-sitemap.xml and explain how long it typically takes for Google to process it." |
| `get_sitemap_details`           | "Check the status of my main sitemap at mywebsite.com/sitemap.xml and explain what the warnings mean for my SEO." |
| `get_search_by_page_query`      | "What search terms are driving traffic to my blog post at mywebsite.com/blog/post-title? Identify opportunities to optimize for related keywords." |
| `compare_search_periods`        | "Compare my site's performance between January and February. What queries improved the most, which declined, and what might explain these changes?" |
| `get_advanced_search_analytics` | "Analyze queries with high impressions but positions below 10, filtered to mobile traffic in the US only. Use `filters` with country=usa and device=MOBILE." |

You can also ask your AI assistant to combine multiple tools and analyze the results. For example:

- "Find my top 20 landing pages by traffic, check their indexing status, and create a report highlighting any pages with both high traffic and indexing issues."

- "Analyze my site's performance trend over the last 90 days, identify my fastest-growing queries, and check if the corresponding landing pages have any technical issues."

- "Compare my desktop vs. mobile search performance, visualize the differences with charts, and recommend specific pages that need mobile optimization based on performance gaps."

- "Identify queries where I'm ranking on page 2 (positions 11-20) that have high impressions but low CTR, then inspect the corresponding URLs and suggest title and meta description improvements."

Your AI assistant will use the GSC tools to fetch the data, present it in an easy-to-understand format, create visualizations when helpful, and provide actionable insights based on the results.

---

## Data Visualization Capabilities

Your AI assistant can help you visualize your GSC data in various ways:

- **Trend Charts**: See how metrics change over time
- **Comparison Graphs**: Compare different time periods or dimensions
- **Performance Distributions**: Understand how your content performs across positions
- **Correlation Analysis**: Identify relationships between different metrics
- **Heatmaps**: Visualize complex datasets with color-coded representations

Simply ask your AI assistant to "visualize" or "create a chart" when analyzing your data, and it will generate appropriate visualizations to help you understand the information better.

---

## Troubleshooting

### Python Command Not Found

On macOS, the default Python command is often `python3` rather than `python`, which can cause issues with some applications including Node.js integrations.

If you encounter errors related to Python not being found, you can create an alias:

1. Create a Python alias (one-time setup):
   ```bash
   # For macOS users:
   sudo ln -s $(which python3) /usr/local/bin/python
   
   # If that doesn't work, try finding your Python installation:
   sudo ln -s /Library/Frameworks/Python.framework/Versions/3.11/bin/python3 /usr/local/bin/python
   ```

2. Verify the alias works:
   ```bash
   python --version
   ```

This creates a symbolic link so that when applications call `python`, they'll actually use your `python3` installation.

### AI Client Configuration Issues

If you're having trouble connecting:

1. Make sure all file paths in your configuration are correct and use the full path
2. Check that your service account has access to your GSC properties
3. Restart your AI client after making any changes
4. Look for error messages in the response when you try to use a tool
5. Ensure your virtual environment is activated when running the server manually

### Other Unexpected Issues

If you encounter any other unexpected issues during installation or usage:

1. Copy the exact error message you're receiving
2. Use ChatGPT or Claude and explain your problem in detail, including:
   - What you were trying to do
   - The exact error message
   - Your operating system
   - Any steps you've already tried
3. AI assistants can often help diagnose and resolve technical issues by suggesting specific solutions for your situation

Remember that most issues have been encountered by others before, and there's usually a straightforward solution available.

---

## Related Tools

If you work with Google Search Console regularly, you may also find these tools useful:

**[Advanced GSC Visualizer](https://www.advancedgsc.com/)** — A Chrome extension (14,000+ users) that brings powerful charts, annotations, and one-click API access directly inside Google Search Console. Features include:

- Interactive charts with trendlines, moving averages, and Google algorithm update overlays
- One-click export of up to 25,000 rows from the GSC API — no coding required
- Keyword cannibalization detection
- Crawl stats visualizations
- AI assistant for querying your GSC data directly in the browser

Built by the same author. [Install from the Chrome Web Store →](https://chromewebstore.google.com/detail/advanced-gsc-visualizer/cdiccpnglfpnclonhpchpaaoigfpieel)

---

## Contributing

Found a bug or have an idea for improvement? We welcome your input! Open an issue or submit a pull request on GitHub.

---

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.

---

## Changelog

### [0.2.0] — March 2026

#### Added
- **Data freshness:** All search analytics queries now use `dataState: "all"` by default, returning data that matches the GSC dashboard instead of finalized-only data (which lags 2–3 days). Configurable via the `GSC_DATA_STATE` environment variable (`"all"` or `"final"`).
- **Flexible row limits:** `get_search_analytics` and `get_search_by_page_query` now accept an optional `row_limit` parameter (default 20, max 500). Claude will automatically choose an appropriate value based on your request — use higher values for comprehensive analysis, lower values for quick overviews.
- **Multi-dimension filtering:** `get_advanced_search_analytics` now accepts a `filters` parameter — a JSON array of filter objects for AND logic across multiple dimensions simultaneously (e.g., country = USA **and** device = mobile). The existing single-filter parameters (`filter_dimension`, `filter_operator`, `filter_expression`) remain fully supported.

### [0.2.1] — March 2026

#### Added
- **Reauthenticate tool:** New `reauthenticate` tool lets you switch Google accounts by deleting the saved OAuth token and triggering a fresh browser login. Ask your AI assistant: *"switch to a different Google account"*. (Thanks [@fterenzani](https://github.com/fterenzani)!)

#### Fixed
- **Sitemap TypeError crash:** `get_sitemaps` and `list_sitemaps_enhanced` crashed with `TypeError` when a sitemap had errors or warnings, because the GSC API returns those counts as strings. Added `int()` casts before comparison. (Thanks [@mcprobert](https://github.com/mcprobert)!)
- **File cache warning:** Suppressed the `file_cache is only supported with oauth2client<4.0.0` warning that caused crashes on MCP hosts that treat any stderr output as fatal (e.g. GitHub Copilot CLI).
- **Domain property 404 errors:** All tools now return a clear, actionable message when a 404 occurs, explaining the exact format required and service account permission requirements for `sc-domain:` properties.

#### Improved
- **Multi-client support:** README now explicitly lists Claude, Cursor, Codex, Gemini CLI, and Antigravity as supported clients with setup guidance for each.
- **`site_url` guidance:** All 15 tool docstrings now explain how to get the exact property URL from `list_properties` and how domain properties relate to subdomain filtering.

---

### [0.1.0] — Initial release

- 19 tools covering property management, search analytics, URL inspection, and sitemap management
- OAuth and service account authentication
- Batch URL inspection (up to 10 URLs)
- Period comparison tool
