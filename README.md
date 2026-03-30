<div align="center">

# 🔍 Google Search Console MCP Server

### Bridge AI Coding Assistants with Google Search Console

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![Google Search Console](https://img.shields.io/badge/Google_Search_Console-API_v1-4285F4?style=for-the-badge&logo=google&logoColor=white)](https://search.google.com/search-console/about)
[![MCP Protocol](https://img.shields.io/badge/MCP-Protocol-FF6B35?style=for-the-badge)](https://modelcontextprotocol.io)
[![License](https://img.shields.io/github/license/hemangjoshi37a/hjLabs.in-mcp-gsc?style=for-the-badge)](LICENSE)
[![Stars](https://img.shields.io/github/stars/hemangjoshi37a/hjLabs.in-mcp-gsc?style=for-the-badge&color=yellow)](https://github.com/hemangjoshi37a/hjLabs.in-mcp-gsc/stargazers)

<br/>

**A Model Context Protocol (MCP) server that connects Google Search Console to AI assistants, enabling deep SEO analysis through natural language conversations.**

*Analyze rankings, find content opportunities, detect cannibalization, and generate health reports — all by chatting with your AI.*

<br/>

[Getting Started](#-getting-started) · [Features](#-features) · [Tools](#-mcp-tools-34) · [Configuration](#-configuration) · [Contributing](#-contributing) · [Contact](#-contact)

<br/>

---

</div>

## 🎯 What is this?

Google Search Console MCP Server is a **Model Context Protocol (MCP)** server that gives AI assistants direct access to your **Google Search Console** data. It exposes **34 tools** that let AI assistants like **Claude**, **Cursor**, **Codex**, **Gemini CLI**, and **Antigravity**:

- 📊 **Analyze** search performance — queries, pages, devices, countries, daily trends
- 🔍 **Inspect** URLs for indexing status, rich results, and crawl issues
- 📈 **Discover** growing/declining keywords and content opportunities
- 🎯 **Detect** keyword cannibalization across competing pages
- 🗺️ **Manage** sitemaps — submit, delete, monitor processing
- 📋 **Generate** comprehensive SEO health reports with recommendations
- 🏷️ **Cluster** queries into semantic topic groups
- 📱 **Break down** performance by device, country, and search appearance type

> **Think of it as giving Claude or Copilot the ability to be your SEO analyst — querying GSC data, spotting patterns, and recommending actions.**

<br/>

## ✨ Features

<table>
<tr>
<td width="50%">

### 📊 Search Analytics
- Top queries and pages with full metrics
- Advanced multi-dimensional filtering
- Period-over-period comparison
- Flexible row limits up to 25,000
- Pagination for large datasets
- Fresh data matching GSC dashboard

</td>
<td width="50%">

### 🔍 URL Inspection
- Single and batch URL inspection
- Indexing status and coverage
- Rich results detection
- Crawl state analysis
- Robots.txt status
- Referring URL discovery

</td>
</tr>
<tr>
<td>

### 📈 Growth & Opportunity Analysis
- Top growing/declining keywords
- Zero-click query detection
- Content optimization opportunities
- Keyword cannibalization detection
- Position distribution analysis
- Query clustering by topic

</td>
<td>

### 🗺️ Sitemap & Property Management
- List, submit, delete sitemaps
- Sitemap error/warning monitoring
- Property listing and management
- Site verification details
- Multi-property support

</td>
</tr>
<tr>
<td>

### 📱 Breakdown Reports
- Device breakdown (desktop/mobile/tablet)
- Country-by-country analysis
- Daily trend tracking
- Search appearance types (web/image/video/news)
- Page-query relationship matrix

</td>
<td>

### 📋 Health & Reporting
- Comprehensive SEO health reports
- Performance trend analysis
- Actionable recommendations
- Top pages ranked by any metric
- Data visualization support

</td>
</tr>
</table>

<br/>

## 🛠️ MCP Tools (34)

<details>
<summary><b>🔌 Property Management (5 tools)</b></summary>

| Tool | Description |
|------|-------------|
| `list_properties` | List all GSC properties in your account |
| `get_site_details` | Get detailed information about a specific property |
| `add_site` | Add a new site to your GSC properties |
| `delete_site` | Remove a site from your GSC properties |
| `reauthenticate` | Switch Google accounts by re-triggering OAuth flow |

</details>

<details>
<summary><b>📊 Search Analytics (5 tools)</b></summary>

| Tool | Description |
|------|-------------|
| `get_search_analytics` | Top queries/pages with clicks, impressions, CTR, position |
| `get_performance_overview` | Summary of site performance over time |
| `get_advanced_search_analytics` | Advanced queries with multi-dimensional filtering, pagination, sorting |
| `compare_search_periods` | Compare performance between two time periods |
| `get_search_by_page_query` | Get search queries driving traffic to a specific page |

</details>

<details>
<summary><b>🔍 URL Inspection (3 tools)</b></summary>

| Tool | Description |
|------|-------------|
| `inspect_url_enhanced` | Detailed URL inspection with indexing status and rich results |
| `batch_url_inspection` | Inspect multiple URLs at once (up to 10 per batch) |
| `check_indexing_issues` | Check specific indexing issues across multiple URLs |

</details>

<details>
<summary><b>🗺️ Sitemap Management (5 tools)</b></summary>

| Tool | Description |
|------|-------------|
| `get_sitemaps` | List all sitemaps for a site |
| `list_sitemaps_enhanced` | Enhanced sitemap listing with detailed info |
| `get_sitemap_details` | Get detailed information about a specific sitemap |
| `submit_sitemap` | Submit or resubmit a sitemap to Google |
| `delete_sitemap` | Delete/unsubmit a sitemap from GSC |
| `manage_sitemaps` | All-in-one sitemap management (list/details/submit/delete) |

</details>

<details>
<summary><b>📈 Growth & Opportunity Analysis (6 tools)</b></summary>

| Tool | Description |
|------|-------------|
| `get_top_growing_queries` | Find trending keywords gaining clicks/impressions |
| `get_top_declining_queries` | Identify keywords losing traction |
| `get_content_opportunities` | High-impression, low-CTR queries — quick-win targets |
| `get_keyword_cannibalization` | Detect queries where multiple pages compete |
| `get_zero_click_queries` | Queries with impressions but zero clicks — wasted visibility |
| `get_query_clusters` | Semantic grouping of related queries by shared keywords |

</details>

<details>
<summary><b>📱 Breakdown & Trend Reports (5 tools)</b></summary>

| Tool | Description |
|------|-------------|
| `get_device_breakdown` | Desktop vs Mobile vs Tablet performance |
| `get_country_breakdown` | Country-by-country traffic analysis |
| `get_daily_trend` | Day-by-day performance with optional filters |
| `get_top_pages` | Top pages ranked by clicks, impressions, CTR, or position |
| `get_search_appearance` | Performance by search type (WEB, IMAGE, VIDEO, NEWS, DISCOVER) |

</details>

<details>
<summary><b>📋 Comprehensive Reports (3 tools)</b></summary>

| Tool | Description |
|------|-------------|
| `get_seo_health_report` | Full SEO health report with performance, trends, devices, recommendations |
| `get_page_query_matrix` | Which queries drive traffic to which pages |
| `get_position_distribution` | Ranking bucket analysis (positions 1-3, 4-10, 11-20, 21-50, 50+) |

</details>

<br/>

## 🚀 Getting Started

### Prerequisites

| Requirement | Details |
|------------|---------|
| **Python** | 3.11 or newer |
| **Node.js** | Required for MCP inspector |
| **Google Cloud** | Project with Search Console API enabled |
| **AI Client** | Claude, Cursor, Codex, Gemini CLI, or Antigravity |

### 1. Set Up Google API Credentials

#### OAuth Authentication (Recommended)

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create/select a project → [Enable Search Console API](https://console.cloud.google.com/apis/library/searchconsole.googleapis.com)
3. Go to [Credentials](https://console.cloud.google.com/apis/credentials) → Create OAuth Client ID → Desktop App
4. Download `client_secrets.json` → place in the server directory

#### Service Account Authentication

1. Go to [Credentials](https://console.cloud.google.com/apis/credentials) → Create Service Account
2. Create JSON key → save as `service_account_credentials.json`
3. Add the service account email to your GSC properties under Settings → Users

### 2. Install & Run

```bash
# Clone the repository
git clone https://github.com/hemangjoshi37a/hjLabs.in-mcp-gsc.git
cd hjLabs.in-mcp-gsc

# Create virtual environment
uv venv .venv      # or: python -m venv .venv

# Activate it
source .venv/bin/activate    # Mac/Linux
# .venv\Scripts\activate     # Windows

# Install dependencies
uv pip install -r requirements.txt   # or: pip install -r requirements.txt
```

<br/>

## ⚙️ Configuration

### Claude Code (CLI)

Add to your project's `.mcp.json` or `~/.claude/settings.json`:

```json
{
  "mcpServers": {
    "mcp-gsc": {
      "command": "/path/to/.venv/bin/python",
      "args": ["/path/to/gsc_server.py"],
      "env": {
        "GSC_OAUTH_CLIENT_SECRETS_FILE": "/path/to/client_secrets.json",
        "GSC_DATA_STATE": "all"
      }
    }
  }
}
```

### Claude Desktop

Edit `~/Library/Application Support/Claude/claude_desktop_config.json` (Mac) or `%APPDATA%\Claude\claude_desktop_config.json` (Windows):

```json
{
  "mcpServers": {
    "mcp-gsc": {
      "command": "/path/to/.venv/bin/python",
      "args": ["/path/to/gsc_server.py"],
      "env": {
        "GSC_OAUTH_CLIENT_SECRETS_FILE": "/path/to/client_secrets.json",
        "GSC_DATA_STATE": "all"
      }
    }
  }
}
```

### Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `GSC_OAUTH_CLIENT_SECRETS_FILE` | OAuth only | `client_secrets.json` | Path to OAuth client secrets |
| `GSC_CREDENTIALS_PATH` | Service account only | `service_account_credentials.json` | Path to service account JSON key |
| `GSC_SKIP_OAUTH` | No | `false` | Set `"true"` to force service account auth |
| `GSC_DATA_STATE` | No | `"all"` | `"all"` = fresh data (matches GSC dashboard), `"final"` = confirmed only (2-3 day lag) |

<br/>

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────┐
│                  AI Assistant                        │
│       (Claude / Copilot / Cursor / Gemini)          │
└──────────────────┬──────────────────────────────────┘
                   │ MCP Protocol (stdio/JSON-RPC)
┌──────────────────▼──────────────────────────────────┐
│           Google Search Console MCP Server            │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────┐ │
│  │  MCP Layer  │→ │ Analytics    │→ │  GSC API   │ │
│  │ (34 Tools)  │  │  Engine      │  │    v1      │ │
│  └─────────────┘  └──────────────┘  └──────┬─────┘ │
└─────────────────────────────────────────────┼───────┘
                                              │ REST API
┌─────────────────────────────────────────────▼───────┐
│            Google Search Console                     │
│  ┌──────────┐  ┌──────────┐  ┌──────┐  ┌────────┐ │
│  │  Search   │  │   URL    │  │ Site │  │Sitemap │ │
│  │ Analytics │  │Inspection│  │ Mgmt │  │  Mgmt  │ │
│  └──────────┘  └──────────┘  └──────┘  └────────┘ │
└─────────────────────────────────────────────────────┘
```

<br/>

## 🔧 Example Prompts

<table>
<tr>
<td width="33%" valign="top">

### 📊 Performance Analysis
- "Generate a full SEO health report for my site"
- "What are my top 20 growing keywords this month?"
- "Show me queries where I rank on page 2 with high impressions"
- "Compare my mobile vs desktop performance"

</td>
<td width="33%" valign="top">

### 🎯 Optimization
- "Find content opportunities — high impressions, low CTR"
- "Detect keyword cannibalization on my site"
- "Which queries get impressions but zero clicks?"
- "Cluster my queries into topic groups"

</td>
<td width="33%" valign="top">

### 🔍 Technical SEO
- "Check indexing status of my top 10 pages"
- "Submit my new sitemap and verify processing"
- "Show daily traffic trend for the last 30 days"
- "Which countries drive the most traffic?"

</td>
</tr>
</table>

<br/>

## 📋 Changelog

### [0.3.0] — March 2026

#### Added (14 new tools)
- **`get_top_growing_queries`** — Spot trending keywords gaining traction
- **`get_top_declining_queries`** — Identify keywords losing visibility
- **`get_content_opportunities`** — High-impression, low-CTR optimization targets
- **`get_keyword_cannibalization`** — Detect pages competing for same keywords
- **`get_device_breakdown`** — Desktop/Mobile/Tablet performance split
- **`get_country_breakdown`** — Country-by-country traffic analysis
- **`get_daily_trend`** — Day-by-day performance with filters
- **`get_top_pages`** — Top pages by any metric
- **`get_page_query_matrix`** — Query-to-page relationship mapping
- **`get_seo_health_report`** — Comprehensive report with recommendations
- **`get_position_distribution`** — Ranking bucket analysis
- **`get_zero_click_queries`** — Wasted impressions detection
- **`get_query_clusters`** — Semantic query grouping
- **`get_search_appearance`** — Performance by search type

### [0.2.1] — March 2026
- **Reauthenticate tool** for switching Google accounts
- **Sitemap TypeError fix** — casts string counts to int
- **File cache warning suppression** for strict MCP hosts
- **Domain property 404** — clear, actionable error messages

### [0.2.0] — March 2026
- **Data freshness** — `dataState: "all"` default matching GSC dashboard
- **Flexible row limits** — up to 500 rows per query
- **Multi-dimension filtering** — JSON-based AND filters

### [0.1.0] — Initial release
- 19 tools: property management, search analytics, URL inspection, sitemap management
- OAuth and service account authentication
- Batch URL inspection, period comparison

<br/>

## 🤝 Contributing

Found a bug or have an idea? We welcome contributions! Open an issue or submit a pull request.

<br/>

## 📄 License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.

<br/>

---

<div align="center">

## 📬 Contact

**Hemang Joshi** — Founder, [hjLabs.in](https://hjlabs.in)

[![Email](https://img.shields.io/badge/Email-hemangjoshi37a@gmail.com-EA4335?style=for-the-badge&logo=gmail&logoColor=white)](mailto:hemangjoshi37a@gmail.com)
[![LinkedIn](https://img.shields.io/badge/LinkedIn-Hemang_Joshi-0A66C2?style=for-the-badge&logo=linkedin&logoColor=white)](https://www.linkedin.com/in/hemang-joshi-046746aa)
[![YouTube](https://img.shields.io/badge/YouTube-@HemangJoshi-FF0000?style=for-the-badge&logo=youtube&logoColor=white)](https://www.youtube.com/@HemangJoshi)
[![WhatsApp](https://img.shields.io/badge/WhatsApp-+91_7016525813-25D366?style=for-the-badge&logo=whatsapp&logoColor=white)](https://wa.me/917016525813)
[![Telegram](https://img.shields.io/badge/Telegram-@hjlabs-26A5E4?style=for-the-badge&logo=telegram&logoColor=white)](https://t.me/hjlabs)

<br/>

**hjLabs.in** — Industrial Automation | AI/ML | IoT | SEO Tools

Serving **15+ countries** with a **4.9⭐ Google rating**

[![Website](https://img.shields.io/badge/🌐_hjLabs.in-Visit_Website-4f46e5?style=for-the-badge)](https://hjlabs.in)
[![GitHub](https://img.shields.io/badge/GitHub-hemangjoshi37a-181717?style=for-the-badge&logo=github&logoColor=white)](https://github.com/hemangjoshi37a)
[![LinkTree](https://img.shields.io/badge/LinkTree-All_Links-39E09B?style=for-the-badge&logo=linktree&logoColor=white)](https://linktr.ee/hemangjoshi37a)

<br/>

---

<sub>Built with ❤️ by <a href="https://hjlabs.in">hjLabs.in</a> — Empowering SEO professionals with AI</sub>

<br/>

⭐ **If this project helps you, please give it a star!** ⭐

</div>
