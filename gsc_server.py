from typing import Any, Dict, List, Optional
import logging
import os
import json
from datetime import datetime, timedelta

import google.auth
from google.auth.transport.requests import Request
from google.oauth2 import service_account
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Suppress the noisy file_cache warning from google-api-python-client.
# Some MCP hosts (e.g. GitHub Copilot CLI) treat any stderr output as a
# fatal error, so this prevents false crashes.
logging.getLogger("googleapiclient.discovery_cache").setLevel(logging.ERROR)

# MCP
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("gsc-server")

# Path to your service account JSON or user credentials JSON
# First check if GSC_CREDENTIALS_PATH environment variable is set
# Then try looking in the script directory and current working directory as fallbacks
GSC_CREDENTIALS_PATH = os.environ.get("GSC_CREDENTIALS_PATH")
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
POSSIBLE_CREDENTIAL_PATHS = [
    GSC_CREDENTIALS_PATH,  # First try the environment variable if set
    os.path.join(SCRIPT_DIR, "service_account_credentials.json"),
    os.path.join(os.getcwd(), "service_account_credentials.json"),
    # Add any other potential paths here
]

# OAuth client secrets file path
OAUTH_CLIENT_SECRETS_FILE = os.environ.get("GSC_OAUTH_CLIENT_SECRETS_FILE")
if not OAUTH_CLIENT_SECRETS_FILE:
    OAUTH_CLIENT_SECRETS_FILE = os.path.join(SCRIPT_DIR, "client_secrets.json")

# Token file path for storing OAuth tokens
TOKEN_FILE = os.path.join(SCRIPT_DIR, "token.json")

# Environment variable to skip OAuth authentication
SKIP_OAUTH = os.environ.get("GSC_SKIP_OAUTH", "").lower() in ("true", "1", "yes")

# Data state for search analytics queries.
# "all"   → includes fresh/unconfirmed data, matches the GSC dashboard (default)
# "final" → only confirmed data, which lags 2-3 days behind the dashboard
_raw_data_state = os.environ.get("GSC_DATA_STATE", "all").lower().strip()
if _raw_data_state not in ("all", "final"):
    raise ValueError(
        f"Invalid GSC_DATA_STATE value '{_raw_data_state}'. "
        "Accepted values are 'all' (default, matches GSC dashboard) or 'final' (2-3 day lag)."
    )
DATA_STATE = _raw_data_state

SCOPES = ["https://www.googleapis.com/auth/webmasters"]

def get_gsc_service():
    """
    Returns an authorized Search Console service object.
    First tries OAuth authentication, then falls back to service account.
    """
    # Try OAuth authentication first if not skipped
    if not SKIP_OAUTH:
        try:
            return get_gsc_service_oauth()
        except Exception as e:
            # If OAuth fails, try service account
            print(f"OAuth authentication failed: {str(e)}")
            pass
    
    # Try service account authentication
    for cred_path in POSSIBLE_CREDENTIAL_PATHS:
        if cred_path and os.path.exists(cred_path):
            try:
                creds = service_account.Credentials.from_service_account_file(
                    cred_path, scopes=SCOPES
                )
                return build("searchconsole", "v1", credentials=creds, cache_discovery=False)
            except Exception as e:
                continue  # Try the next path if this one fails
    
    # If we get here, none of the authentication methods worked
    raise FileNotFoundError(
        f"Authentication failed. Please either:\n"
        f"1. Set up OAuth by placing a client_secrets.json file in the script directory, or\n"
        f"2. Set the GSC_CREDENTIALS_PATH environment variable or place a service account credentials file in one of these locations: "
        f"{', '.join([p for p in POSSIBLE_CREDENTIAL_PATHS[1:] if p])}"
    )

def get_gsc_service_oauth():
    """
    Returns an authorized Search Console service object using OAuth.
    """
    creds = None
    
    # Check if token file exists
    if os.path.exists(TOKEN_FILE):
        try:
            creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
        except Exception as e:
            # If token file is corrupted, delete it
            if os.path.exists(TOKEN_FILE):
                os.remove(TOKEN_FILE)
            creds = None
    
    # If credentials don't exist or are invalid, get new ones
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                # Save the refreshed credentials
                with open(TOKEN_FILE, 'w') as token:
                    token.write(creds.to_json())
            except Exception as e:
                # If refresh fails, delete the bad token and trigger new OAuth flow
                if os.path.exists(TOKEN_FILE):
                    os.remove(TOKEN_FILE)
                # Fall through to the OAuth flow below
                creds = None
        
        # Start new OAuth flow if we don't have valid credentials
        if not creds or not creds.valid:
            # Check if client secrets file exists
            if not os.path.exists(OAUTH_CLIENT_SECRETS_FILE):
                raise FileNotFoundError(
                    f"OAuth client secrets file not found. Please place a client_secrets.json file in the script directory "
                    f"or set the GSC_OAUTH_CLIENT_SECRETS_FILE environment variable."
                )
            
            # Start OAuth flow
            flow = InstalledAppFlow.from_client_secrets_file(OAUTH_CLIENT_SECRETS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
            
            # Save the credentials for future use
            with open(TOKEN_FILE, 'w') as token:
                token.write(creds.to_json())
    
    # Build and return the service
    return build("searchconsole", "v1", credentials=creds, cache_discovery=False)


def _site_not_found_error(site_url: str) -> str:
    """Return a helpful message when a GSC property returns 404."""
    lines = [f"Property '{site_url}' not found (404). Possible causes:\n"]
    lines.append(
        "1. The site_url doesn't exactly match what is in GSC. "
        "Run list_properties to get the exact string to use."
    )
    if site_url.startswith("sc-domain:"):
        lines.append(
            "2. Domain properties require the service account to be explicitly added "
            "under GSC Settings > Users and permissions for that specific domain property. "
            "OAuth users must also have verified access to it."
        )
    else:
        lines.append(
            "2. If your property is a domain property (covers all subdomains), "
            "the correct format is 'sc-domain:example.com', not a full URL."
        )
    lines.append(
        "3. The authenticated account may not have access to this property."
    )
    return "\n".join(lines)


@mcp.tool()
async def list_properties() -> str:
    """
    Retrieves and returns the user's Search Console properties.
    """
    try:
        service = get_gsc_service()
        site_list = service.sites().list().execute()

        # site_list is typically something like:
        # {
        #   "siteEntry": [
        #       {"siteUrl": "...", "permissionLevel": "..."},
        #       ...
        #   ]
        # }
        sites = site_list.get("siteEntry", [])

        if not sites:
            return "No Search Console properties found."

        # Format the results for easy reading
        lines = []
        for site in sites:
            site_url = site.get("siteUrl", "Unknown")
            permission = site.get("permissionLevel", "Unknown permission")
            lines.append(f"- {site_url} ({permission})")

        return "\n".join(lines)
    except FileNotFoundError as e:
        return (
            "Error: Service account credentials file not found.\n\n"
            "To access Google Search Console, please:\n"
            "1. Create a service account in Google Cloud Console\n"
            "2. Download the JSON credentials file\n"
            "3. Save it as 'service_account_credentials.json' in the same directory as this script\n"
            "4. Share your GSC properties with the service account email"
        )
    except Exception as e:
        return f"Error retrieving properties: {str(e)}"

@mcp.tool()
async def add_site(site_url: str) -> str:
    """
    Add a site to your Search Console properties.
    
    Args:
        site_url: The URL of the site to add (must be exact match e.g. https://example.com, or https://www.example.com, or https://subdomain.example.com/path/, for domain properties use format: sc-domain:example.com)
    """
    try:
        service = get_gsc_service()
        
        # Add the site
        response = service.sites().add(siteUrl=site_url).execute()
        
        # Format the response
        result_lines = [f"Site {site_url} has been added to Search Console."]
        
        # Add permission level if available
        if "permissionLevel" in response:
            result_lines.append(f"Permission level: {response['permissionLevel']}")
        
        return "\n".join(result_lines)
    except HttpError as e:
        error_content = json.loads(e.content.decode('utf-8'))
        error_details = error_content.get('error', {})
        error_code = e.resp.status
        error_message = error_details.get('message', str(e))
        error_reason = error_details.get('errors', [{}])[0].get('reason', '')
        
        if error_code == 409:
            return f"Site {site_url} is already added to Search Console."
        elif error_code == 403:
            if error_reason == 'forbidden':
                return f"Error: You don't have permission to add this site. Please verify ownership first."
            elif error_reason == 'quotaExceeded':
                return f"Error: API quota exceeded. Please try again later."
            else:
                return f"Error: Permission denied. {error_message}"
        elif error_code == 400:
            if error_reason == 'invalidParameter':
                return f"Error: Invalid site URL format. Please check the URL format and try again."
            else:
                return f"Error: Bad request. {error_message}"
        elif error_code == 401:
            return f"Error: Unauthorized. Please check your credentials."
        elif error_code == 429:
            return f"Error: Too many requests. Please try again later."
        elif error_code == 500:
            return f"Error: Internal server error from Google Search Console API. Please try again later."
        elif error_code == 503:
            return f"Error: Service unavailable. Google Search Console API is currently down. Please try again later."
        else:
            return f"Error adding site (HTTP {error_code}): {error_message}"
    except Exception as e:
        return f"Error adding site: {str(e)}"

@mcp.tool()
async def delete_site(site_url: str) -> str:
    """
    Remove a site from your Search Console properties.
    
    Args:
        site_url: The URL of the site to remove (must be exact match e.g. https://example.com, or https://www.example.com, or https://subdomain.example.com/path/, for domain properties use format: sc-domain:example.com)
    """
    try:
        service = get_gsc_service()
        
        # Delete the site
        service.sites().delete(siteUrl=site_url).execute()
        
        return f"Site {site_url} has been removed from Search Console."
    except HttpError as e:
        error_content = json.loads(e.content.decode('utf-8'))
        error_details = error_content.get('error', {})
        error_code = e.resp.status
        error_message = error_details.get('message', str(e))
        error_reason = error_details.get('errors', [{}])[0].get('reason', '')
        
        if error_code == 404:
            return f"Site {site_url} was not found in Search Console."
        elif error_code == 403:
            if error_reason == 'forbidden':
                return f"Error: You don't have permission to remove this site."
            elif error_reason == 'quotaExceeded':
                return f"Error: API quota exceeded. Please try again later."
            else:
                return f"Error: Permission denied. {error_message}"
        elif error_code == 400:
            if error_reason == 'invalidParameter':
                return f"Error: Invalid site URL format. Please check the URL format and try again."
            else:
                return f"Error: Bad request. {error_message}"
        elif error_code == 401:
            return f"Error: Unauthorized. Please check your credentials."
        elif error_code == 429:
            return f"Error: Too many requests. Please try again later."
        elif error_code == 500:
            return f"Error: Internal server error from Google Search Console API. Please try again later."
        elif error_code == 503:
            return f"Error: Service unavailable. Google Search Console API is currently down. Please try again later."
        else:
            return f"Error removing site (HTTP {error_code}): {error_message}"
    except Exception as e:
        return f"Error removing site: {str(e)}"

@mcp.tool()
async def get_search_analytics(site_url: str, days: int = 28, dimensions: str = "query", row_limit: int = 20) -> str:
    """
    Get search analytics data for a specific property.
    
    Args:
        site_url: Exact GSC property URL from list_properties (e.g. "https://example.com/" or
                  "sc-domain:example.com"). Domain properties cover all subdomains — use the
                  domain property as site_url and filter by page to analyze a specific subdomain.
        days: Number of days to look back (default: 28)
        dimensions: Dimensions to group by (default: query). Options: query, page, device, country, date
                   You can provide multiple dimensions separated by comma (e.g., "query,page")
        row_limit: Number of rows to return (default: 20, max: 500). Use 5-20 for quick overviews,
                   50-200 for deeper analysis, up to 500 for comprehensive reports. For bulk exports
                   beyond 500 rows, use get_advanced_search_analytics which supports pagination.
    """
    try:
        service = get_gsc_service()
        
        # Calculate date range
        end_date = datetime.now().date()
        start_date = end_date - timedelta(days=days)
        
        # Parse dimensions
        dimension_list = [d.strip() for d in dimensions.split(",")]
        
        # Build request
        request = {
            "startDate": start_date.strftime("%Y-%m-%d"),
            "endDate": end_date.strftime("%Y-%m-%d"),
            "dimensions": dimension_list,
            "rowLimit": min(max(1, row_limit), 500),
            "dataState": DATA_STATE
        }
        
        # Execute request
        response = service.searchanalytics().query(siteUrl=site_url, body=request).execute()
        
        if not response.get("rows"):
            return f"No search analytics data found for {site_url} in the last {days} days."
        
        # Format results
        result_lines = [f"Search analytics for {site_url} (last {days} days):"]
        result_lines.append("\n" + "-" * 80 + "\n")
        
        # Create header based on dimensions
        header = []
        for dim in dimension_list:
            header.append(dim.capitalize())
        header.extend(["Clicks", "Impressions", "CTR", "Position"])
        result_lines.append(" | ".join(header))
        result_lines.append("-" * 80)
        
        # Add data rows
        for row in response.get("rows", []):
            data = []
            # Add dimension values
            for dim_value in row.get("keys", []):
                data.append(dim_value[:100])  # Increased truncation limit to 100 characters
            
            # Add metrics
            data.append(str(row.get("clicks", 0)))
            data.append(str(row.get("impressions", 0)))
            data.append(f"{row.get('ctr', 0) * 100:.2f}%")
            data.append(f"{row.get('position', 0):.1f}")
            
            result_lines.append(" | ".join(data))
        
        return "\n".join(result_lines)
    except Exception as e:
        if "404" in str(e):
            return _site_not_found_error(site_url)
        return f"Error retrieving search analytics: {str(e)}"

@mcp.tool()
async def get_site_details(site_url: str) -> str:
    """
    Get detailed information about a specific Search Console property.
    
    Args:
        site_url: Exact GSC property URL from list_properties (e.g. "https://example.com/" or
                  "sc-domain:example.com"). Domain properties cover all subdomains — use the
                  domain property as site_url and filter by page to analyze a specific subdomain.
    """
    try:
        service = get_gsc_service()
        
        # Get site details
        site_info = service.sites().get(siteUrl=site_url).execute()
        
        # Format the results
        result_lines = [f"Site details for {site_url}:"]
        result_lines.append("-" * 50)
        
        # Add basic info
        result_lines.append(f"Permission level: {site_info.get('permissionLevel', 'Unknown')}")
        
        # Add verification info if available
        if "siteVerificationInfo" in site_info:
            verify_info = site_info["siteVerificationInfo"]
            result_lines.append(f"Verification state: {verify_info.get('verificationState', 'Unknown')}")
            
            if "verifiedUser" in verify_info:
                result_lines.append(f"Verified by: {verify_info['verifiedUser']}")
                
            if "verificationMethod" in verify_info:
                result_lines.append(f"Verification method: {verify_info['verificationMethod']}")
        
        # Add ownership info if available
        if "ownershipInfo" in site_info:
            owner_info = site_info["ownershipInfo"]
            result_lines.append("\nOwnership Information:")
            result_lines.append(f"Owner: {owner_info.get('owner', 'Unknown')}")
            
            if "verificationMethod" in owner_info:
                result_lines.append(f"Ownership verification: {owner_info['verificationMethod']}")
        
        return "\n".join(result_lines)
    except Exception as e:
        return f"Error retrieving site details: {str(e)}"

@mcp.tool()
async def get_sitemaps(site_url: str) -> str:
    """
    List all sitemaps for a specific Search Console property.
    
    Args:
        site_url: Exact GSC property URL from list_properties (e.g. "https://example.com/" or
                  "sc-domain:example.com"). Domain properties cover all subdomains — use the
                  domain property as site_url and filter by page to analyze a specific subdomain.
    """
    try:
        service = get_gsc_service()
        
        # Get sitemaps list
        sitemaps = service.sitemaps().list(siteUrl=site_url).execute()
        
        if not sitemaps.get("sitemap"):
            return f"No sitemaps found for {site_url}."
        
        # Format the results
        result_lines = [f"Sitemaps for {site_url}:"]
        result_lines.append("-" * 80)
        
        # Header
        result_lines.append("Path | Last Downloaded | Status | Indexed URLs | Errors")
        result_lines.append("-" * 80)
        
        # Add each sitemap
        for sitemap in sitemaps.get("sitemap", []):
            path = sitemap.get("path", "Unknown")
            last_downloaded = sitemap.get("lastDownloaded", "Never")
            
            # Format last downloaded date if it exists
            if last_downloaded != "Never":
                try:
                    # Convert to more readable format
                    dt = datetime.fromisoformat(last_downloaded.replace('Z', '+00:00'))
                    last_downloaded = dt.strftime("%Y-%m-%d %H:%M")
                except:
                    pass
            
            status = "Valid"
            if "errors" in sitemap and int(sitemap["errors"]) > 0:
                status = "Has errors"
            
            # Get counts
            warnings = int(sitemap.get("warnings", 0))
            errors = int(sitemap.get("errors", 0))

            # Get contents if available
            indexed_urls = "N/A"
            if "contents" in sitemap:
                for content in sitemap["contents"]:
                    if content.get("type") == "web":
                        indexed_urls = content.get("submitted", "0")
                        break
            
            result_lines.append(f"{path} | {last_downloaded} | {status} | {indexed_urls} | {errors}")
        
        return "\n".join(result_lines)
    except Exception as e:
        if "404" in str(e):
            return _site_not_found_error(site_url)
        return f"Error retrieving sitemaps: {str(e)}"

@mcp.tool()
async def inspect_url_enhanced(site_url: str, page_url: str) -> str:
    """
    Enhanced URL inspection to check indexing status and rich results in Google.
    
    Args:
        site_url: Exact GSC property URL from list_properties (e.g. "https://example.com/" or
                  "sc-domain:example.com"). Domain properties cover all subdomains — use the
                  domain property as site_url and filter by page to analyze a specific subdomain.
        page_url: The specific URL to inspect
    """
    try:
        service = get_gsc_service()
        
        # Build request
        request = {
            "inspectionUrl": page_url,
            "siteUrl": site_url
        }
        
        # Execute request
        response = service.urlInspection().index().inspect(body=request).execute()
        
        if not response or "inspectionResult" not in response:
            return f"No inspection data found for {page_url}."
        
        inspection = response["inspectionResult"]
        
        # Format the results
        result_lines = [f"URL Inspection for {page_url}:"]
        result_lines.append("-" * 80)
        
        # Add inspection result link if available
        if "inspectionResultLink" in inspection:
            result_lines.append(f"Search Console Link: {inspection['inspectionResultLink']}")
            result_lines.append("-" * 80)
        
        # Indexing status section
        index_status = inspection.get("indexStatusResult", {})
        verdict = index_status.get("verdict", "UNKNOWN")
        
        result_lines.append(f"Indexing Status: {verdict}")
        
        # Coverage state
        if "coverageState" in index_status:
            result_lines.append(f"Coverage: {index_status['coverageState']}")
        
        # Last crawl
        if "lastCrawlTime" in index_status:
            try:
                crawl_time = datetime.fromisoformat(index_status["lastCrawlTime"].replace('Z', '+00:00'))
                result_lines.append(f"Last Crawled: {crawl_time.strftime('%Y-%m-%d %H:%M')}")
            except:
                result_lines.append(f"Last Crawled: {index_status['lastCrawlTime']}")
        
        # Page fetch
        if "pageFetchState" in index_status:
            result_lines.append(f"Page Fetch: {index_status['pageFetchState']}")
        
        # Robots.txt status
        if "robotsTxtState" in index_status:
            result_lines.append(f"Robots.txt: {index_status['robotsTxtState']}")
        
        # Indexing state
        if "indexingState" in index_status:
            result_lines.append(f"Indexing State: {index_status['indexingState']}")
        
        # Canonical information
        if "googleCanonical" in index_status:
            result_lines.append(f"Google Canonical: {index_status['googleCanonical']}")
        
        if "userCanonical" in index_status and index_status.get("userCanonical") != index_status.get("googleCanonical"):
            result_lines.append(f"User Canonical: {index_status['userCanonical']}")
        
        # Crawled as
        if "crawledAs" in index_status:
            result_lines.append(f"Crawled As: {index_status['crawledAs']}")
        
        # Referring URLs
        if "referringUrls" in index_status and index_status["referringUrls"]:
            result_lines.append("\nReferring URLs:")
            for url in index_status["referringUrls"][:5]:  # Limit to 5 examples
                result_lines.append(f"- {url}")
            
            if len(index_status["referringUrls"]) > 5:
                result_lines.append(f"... and {len(index_status['referringUrls']) - 5} more")
        
        # Rich results
        if "richResultsResult" in inspection:
            rich = inspection["richResultsResult"]
            result_lines.append(f"\nRich Results: {rich.get('verdict', 'UNKNOWN')}")
            
            if "detectedItems" in rich and rich["detectedItems"]:
                result_lines.append("Detected Rich Result Types:")
                
                for item in rich["detectedItems"]:
                    rich_type = item.get("richResultType", "Unknown")
                    result_lines.append(f"- {rich_type}")
                    
                    # If there are items with names, show them
                    if "items" in item and item["items"]:
                        for i, subitem in enumerate(item["items"][:3]):  # Limit to 3 examples
                            if "name" in subitem:
                                result_lines.append(f"  • {subitem['name']}")
                        
                        if len(item["items"]) > 3:
                            result_lines.append(f"  • ... and {len(item['items']) - 3} more items")
            
            # Check for issues
            if "richResultsIssues" in rich and rich["richResultsIssues"]:
                result_lines.append("\nRich Results Issues:")
                for issue in rich["richResultsIssues"]:
                    severity = issue.get("severity", "Unknown")
                    message = issue.get("message", "Unknown issue")
                    result_lines.append(f"- [{severity}] {message}")
        
        return "\n".join(result_lines)
    except Exception as e:
        if "404" in str(e):
            return _site_not_found_error(site_url)
        return f"Error inspecting URL: {str(e)}"

@mcp.tool()
async def batch_url_inspection(site_url: str, urls: str) -> str:
    """
    Inspect multiple URLs in batch (within API limits).
    
    Args:
        site_url: Exact GSC property URL from list_properties (e.g. "https://example.com/" or
                  "sc-domain:example.com"). Domain properties cover all subdomains — use the
                  domain property as site_url and filter by page to analyze a specific subdomain.
        urls: List of URLs to inspect, one per line
    """
    try:
        service = get_gsc_service()
        
        # Parse URLs
        url_list = [url.strip() for url in urls.split('\n') if url.strip()]
        
        if not url_list:
            return "No URLs provided for inspection."
        
        if len(url_list) > 10:
            return f"Too many URLs provided ({len(url_list)}). Please limit to 10 URLs per batch to avoid API quota issues."
        
        # Process each URL
        results = []
        
        for page_url in url_list:
            # Build request
            request = {
                "inspectionUrl": page_url,
                "siteUrl": site_url
            }
            
            try:
                # Execute request with a small delay to avoid rate limits
                response = service.urlInspection().index().inspect(body=request).execute()
                
                if not response or "inspectionResult" not in response:
                    results.append(f"{page_url}: No inspection data found")
                    continue
                
                inspection = response["inspectionResult"]
                index_status = inspection.get("indexStatusResult", {})
                
                # Get key information
                verdict = index_status.get("verdict", "UNKNOWN")
                coverage = index_status.get("coverageState", "Unknown")
                last_crawl = "Never"
                
                if "lastCrawlTime" in index_status:
                    try:
                        crawl_time = datetime.fromisoformat(index_status["lastCrawlTime"].replace('Z', '+00:00'))
                        last_crawl = crawl_time.strftime('%Y-%m-%d')
                    except:
                        last_crawl = index_status["lastCrawlTime"]
                
                # Check for rich results
                rich_results = "None"
                if "richResultsResult" in inspection:
                    rich = inspection["richResultsResult"]
                    if rich.get("verdict") == "PASS" and "detectedItems" in rich and rich["detectedItems"]:
                        rich_types = [item.get("richResultType", "Unknown") for item in rich["detectedItems"]]
                        rich_results = ", ".join(rich_types)
                
                # Format result
                results.append(f"{page_url}:\n  Status: {verdict} - {coverage}\n  Last Crawl: {last_crawl}\n  Rich Results: {rich_results}\n")
            
            except Exception as e:
                results.append(f"{page_url}: Error - {str(e)}")
        
        # Combine results
        return f"Batch URL Inspection Results for {site_url}:\n\n" + "\n".join(results)
    
    except Exception as e:
        return f"Error performing batch inspection: {str(e)}"

@mcp.tool()
async def check_indexing_issues(site_url: str, urls: str) -> str:
    """
    Check for specific indexing issues across multiple URLs.
    
    Args:
        site_url: Exact GSC property URL from list_properties (e.g. "https://example.com/" or
                  "sc-domain:example.com"). Domain properties cover all subdomains — use the
                  domain property as site_url and filter by page to analyze a specific subdomain.
        urls: List of URLs to check, one per line
    """
    try:
        service = get_gsc_service()
        
        # Parse URLs
        url_list = [url.strip() for url in urls.split('\n') if url.strip()]
        
        if not url_list:
            return "No URLs provided for inspection."
        
        if len(url_list) > 10:
            return f"Too many URLs provided ({len(url_list)}). Please limit to 10 URLs per batch to avoid API quota issues."
        
        # Track issues by category
        issues_summary = {
            "not_indexed": [],
            "canonical_issues": [],
            "robots_blocked": [],
            "fetch_issues": [],
            "indexed": []
        }
        
        # Process each URL
        for page_url in url_list:
            # Build request
            request = {
                "inspectionUrl": page_url,
                "siteUrl": site_url
            }
            
            try:
                # Execute request
                response = service.urlInspection().index().inspect(body=request).execute()
                
                if not response or "inspectionResult" not in response:
                    issues_summary["not_indexed"].append(f"{page_url} - No inspection data found")
                    continue
                
                inspection = response["inspectionResult"]
                index_status = inspection.get("indexStatusResult", {})
                
                # Check indexing status
                verdict = index_status.get("verdict", "UNKNOWN")
                coverage = index_status.get("coverageState", "Unknown")
                
                if verdict != "PASS" or "not indexed" in coverage.lower() or "excluded" in coverage.lower():
                    issues_summary["not_indexed"].append(f"{page_url} - {coverage}")
                else:
                    issues_summary["indexed"].append(page_url)
                
                # Check canonical issues
                google_canonical = index_status.get("googleCanonical", "")
                user_canonical = index_status.get("userCanonical", "")
                
                if google_canonical and user_canonical and google_canonical != user_canonical:
                    issues_summary["canonical_issues"].append(
                        f"{page_url} - Google chose: {google_canonical} instead of user-declared: {user_canonical}"
                    )
                
                # Check robots.txt status
                robots_state = index_status.get("robotsTxtState", "")
                if robots_state == "BLOCKED":
                    issues_summary["robots_blocked"].append(page_url)
                
                # Check fetch issues
                fetch_state = index_status.get("pageFetchState", "")
                if fetch_state != "SUCCESSFUL":
                    issues_summary["fetch_issues"].append(f"{page_url} - {fetch_state}")
            
            except Exception as e:
                issues_summary["not_indexed"].append(f"{page_url} - Error: {str(e)}")
        
        # Format results
        result_lines = [f"Indexing Issues Report for {site_url}:"]
        result_lines.append("-" * 80)
        
        # Summary counts
        result_lines.append(f"Total URLs checked: {len(url_list)}")
        result_lines.append(f"Indexed: {len(issues_summary['indexed'])}")
        result_lines.append(f"Not indexed: {len(issues_summary['not_indexed'])}")
        result_lines.append(f"Canonical issues: {len(issues_summary['canonical_issues'])}")
        result_lines.append(f"Robots.txt blocked: {len(issues_summary['robots_blocked'])}")
        result_lines.append(f"Fetch issues: {len(issues_summary['fetch_issues'])}")
        result_lines.append("-" * 80)
        
        # Detailed issues
        if issues_summary["not_indexed"]:
            result_lines.append("\nNot Indexed URLs:")
            for issue in issues_summary["not_indexed"]:
                result_lines.append(f"- {issue}")
        
        if issues_summary["canonical_issues"]:
            result_lines.append("\nCanonical Issues:")
            for issue in issues_summary["canonical_issues"]:
                result_lines.append(f"- {issue}")
        
        if issues_summary["robots_blocked"]:
            result_lines.append("\nRobots.txt Blocked URLs:")
            for url in issues_summary["robots_blocked"]:
                result_lines.append(f"- {url}")
        
        if issues_summary["fetch_issues"]:
            result_lines.append("\nFetch Issues:")
            for issue in issues_summary["fetch_issues"]:
                result_lines.append(f"- {issue}")
        
        return "\n".join(result_lines)
    
    except Exception as e:
        return f"Error checking indexing issues: {str(e)}"

@mcp.tool()
async def get_performance_overview(site_url: str, days: int = 28) -> str:
    """
    Get a performance overview for a specific property.
    
    Args:
        site_url: Exact GSC property URL from list_properties (e.g. "https://example.com/" or
                  "sc-domain:example.com"). Domain properties cover all subdomains — use the
                  domain property as site_url and filter by page to analyze a specific subdomain.
        days: Number of days to look back (default: 28)
    """
    try:
        service = get_gsc_service()
        
        # Calculate date range
        end_date = datetime.now().date()
        start_date = end_date - timedelta(days=days)
        
        # Get total metrics
        total_request = {
            "startDate": start_date.strftime("%Y-%m-%d"),
            "endDate": end_date.strftime("%Y-%m-%d"),
            "dimensions": [],  # No dimensions for totals
            "rowLimit": 1,
            "dataState": DATA_STATE
        }
        
        total_response = service.searchanalytics().query(siteUrl=site_url, body=total_request).execute()
        
        # Get by date for trend
        date_request = {
            "startDate": start_date.strftime("%Y-%m-%d"),
            "endDate": end_date.strftime("%Y-%m-%d"),
            "dimensions": ["date"],
            "rowLimit": days,
            "dataState": DATA_STATE
        }
        
        date_response = service.searchanalytics().query(siteUrl=site_url, body=date_request).execute()
        
        # Format results
        result_lines = [f"Performance Overview for {site_url} (last {days} days):"]
        result_lines.append("-" * 80)
        
        # Add total metrics
        if total_response.get("rows"):
            row = total_response["rows"][0]
            result_lines.append(f"Total Clicks: {row.get('clicks', 0):,}")
            result_lines.append(f"Total Impressions: {row.get('impressions', 0):,}")
            result_lines.append(f"Average CTR: {row.get('ctr', 0) * 100:.2f}%")
            result_lines.append(f"Average Position: {row.get('position', 0):.1f}")
        else:
            result_lines.append("No data available for the selected period.")
            return "\n".join(result_lines)
        
        # Add trend data
        if date_response.get("rows"):
            result_lines.append("\nDaily Trend:")
            result_lines.append("Date | Clicks | Impressions | CTR | Position")
            result_lines.append("-" * 80)
            
            # Sort by date
            sorted_rows = sorted(date_response["rows"], key=lambda x: x["keys"][0])
            
            for row in sorted_rows:
                date_str = row["keys"][0]
                # Format date from YYYY-MM-DD to MM/DD
                try:
                    date_obj = datetime.strptime(date_str, "%Y-%m-%d")
                    date_formatted = date_obj.strftime("%m/%d")
                except:
                    date_formatted = date_str
                
                clicks = row.get("clicks", 0)
                impressions = row.get("impressions", 0)
                ctr = row.get("ctr", 0) * 100
                position = row.get("position", 0)
                
                result_lines.append(f"{date_formatted} | {clicks:.0f} | {impressions:.0f} | {ctr:.2f}% | {position:.1f}")
        
        return "\n".join(result_lines)
    except Exception as e:
        if "404" in str(e):
            return _site_not_found_error(site_url)
        return f"Error retrieving performance overview: {str(e)}"

@mcp.tool()
async def get_advanced_search_analytics(
    site_url: str, 
    start_date: str = None, 
    end_date: str = None, 
    dimensions: str = "query", 
    search_type: str = "WEB",
    row_limit: int = 1000,
    start_row: int = 0,
    sort_by: str = "clicks",
    sort_direction: str = "descending",
    filter_dimension: str = None,
    filter_operator: str = "contains", 
    filter_expression: str = None,
    filters: str = None,
    data_state: str = None
) -> str:
    """
    Get advanced search analytics data with sorting, filtering, and pagination.
    
    Args:
        site_url: Exact GSC property URL from list_properties (e.g. "https://example.com/" or
                  "sc-domain:example.com"). Domain properties cover all subdomains — use the
                  domain property as site_url and filter by page to analyze a specific subdomain.
        start_date: Start date in YYYY-MM-DD format (defaults to 28 days ago)
        end_date: End date in YYYY-MM-DD format (defaults to today)
        dimensions: Dimensions to group by, comma-separated (e.g., "query,page,device")
        search_type: Type of search results (WEB, IMAGE, VIDEO, NEWS, DISCOVER)
        row_limit: Maximum number of rows to return (max 25000)
        start_row: Starting row for pagination
        sort_by: Metric to sort by (clicks, impressions, ctr, position)
        sort_direction: Sort direction (ascending or descending)
        filter_dimension: Single filter dimension (query, page, country, device). Use 'filters' instead for multiple filters.
        filter_operator: Single filter operator (contains, equals, notContains, notEquals)
        filter_expression: Single filter expression value
        filters: JSON array of filter objects for AND logic across multiple dimensions. Overrides
                 filter_dimension/filter_operator/filter_expression when provided. Each object must
                 have 'dimension', 'operator', and 'expression' keys. Valid dimensions: query, page,
                 country, device. Valid operators: contains, equals, notContains, notEquals.
                 Example: [{"dimension":"country","operator":"equals","expression":"usa"},
                           {"dimension":"device","operator":"equals","expression":"MOBILE"}]
        data_state: Data freshness — "all" (default, matches GSC dashboard) or "final" (confirmed data only, 2-3 day lag)
    """
    try:
        service = get_gsc_service()
        
        # Calculate date range if not provided
        if not end_date:
            end_date = datetime.now().date().strftime("%Y-%m-%d")
        if not start_date:
            start_date = (datetime.now().date() - timedelta(days=28)).strftime("%Y-%m-%d")
        
        # Resolve and validate data_state (per-call override or fall back to global setting)
        resolved_data_state = (data_state or DATA_STATE).lower().strip()
        if resolved_data_state not in ("all", "final"):
            return (
                f"Invalid data_state value '{data_state}'. "
                "Accepted values are 'all' (matches GSC dashboard) or 'final' (2-3 day lag)."
            )
        
        # Parse dimensions
        dimension_list = [d.strip() for d in dimensions.split(",")]
        
        # Build request
        request = {
            "startDate": start_date,
            "endDate": end_date,
            "dimensions": dimension_list,
            "rowLimit": min(row_limit, 25000),  # Cap at API maximum
            "startRow": start_row,
            "searchType": search_type.upper(),
            "dataState": resolved_data_state
        }
        
        # Add sorting
        if sort_by:
            metric_map = {
                "clicks": "CLICK_COUNT",
                "impressions": "IMPRESSION_COUNT",
                "ctr": "CTR",
                "position": "POSITION"
            }
            
            if sort_by in metric_map:
                request["orderBy"] = [{
                    "metric": metric_map[sort_by],
                    "direction": sort_direction.lower()
                }]
        
        # Build filter groups — multi-filter JSON takes priority over single-filter params
        active_filters = []
        if filters:
            try:
                filter_list = json.loads(filters)
            except json.JSONDecodeError:
                return "Invalid filters JSON. Please provide a valid JSON array of filter objects."
            if not isinstance(filter_list, list) or len(filter_list) == 0:
                return "Invalid filters value. Expected a non-empty JSON array of filter objects."
            for f in filter_list:
                if not all(k in f for k in ("dimension", "operator", "expression")):
                    return (
                        "Each filter object must have 'dimension', 'operator', and 'expression' keys. "
                        f"Invalid filter: {f}"
                    )
            request["dimensionFilterGroups"] = [{"filters": filter_list}]
            active_filters = filter_list
        elif filter_dimension and filter_expression:
            single_filter = {
                "dimension": filter_dimension,
                "operator": filter_operator,
                "expression": filter_expression
            }
            request["dimensionFilterGroups"] = [{"filters": [single_filter]}]
            active_filters = [single_filter]
        
        # Execute request
        response = service.searchanalytics().query(siteUrl=site_url, body=request).execute()
        
        if not response.get("rows"):
            no_data_msg = (
                f"No search analytics data found for {site_url} with the specified parameters.\n\n"
                f"Parameters used:\n"
                f"- Date range: {start_date} to {end_date}\n"
                f"- Dimensions: {dimensions}\n"
                f"- Search type: {search_type}\n"
            )
            if active_filters:
                no_data_msg += "- Filters:\n"
                for f in active_filters:
                    no_data_msg += f"    {f['dimension']} {f['operator']} '{f['expression']}'\n"
            else:
                no_data_msg += "- No filter applied\n"
            return no_data_msg
        
        # Format results
        result_lines = [f"Search analytics for {site_url}:"]
        result_lines.append(f"Date range: {start_date} to {end_date}")
        result_lines.append(f"Search type: {search_type}")
        if active_filters:
            filter_desc = " AND ".join(
                f"{f['dimension']} {f['operator']} '{f['expression']}'" for f in active_filters
            )
            result_lines.append(f"Filters: {filter_desc}")
        result_lines.append(f"Showing rows {start_row+1} to {start_row+len(response.get('rows', []))} (sorted by {sort_by} {sort_direction})")
        result_lines.append("\n" + "-" * 80 + "\n")
        
        # Create header based on dimensions
        header = []
        for dim in dimension_list:
            header.append(dim.capitalize())
        header.extend(["Clicks", "Impressions", "CTR", "Position"])
        result_lines.append(" | ".join(header))
        result_lines.append("-" * 80)
        
        # Add data rows
        for row in response.get("rows", []):
            data = []
            # Add dimension values
            for dim_value in row.get("keys", []):
                data.append(dim_value[:100])  # Increased truncation limit to 100 characters
            
            # Add metrics
            data.append(str(row.get("clicks", 0)))
            data.append(str(row.get("impressions", 0)))
            data.append(f"{row.get('ctr', 0) * 100:.2f}%")
            data.append(f"{row.get('position', 0):.1f}")
            
            result_lines.append(" | ".join(data))
        
        # Add pagination info if there might be more results
        if len(response.get("rows", [])) == row_limit:
            next_start = start_row + row_limit
            result_lines.append("\nThere may be more results available. To see the next page, use:")
            result_lines.append(f"start_row: {next_start}, row_limit: {row_limit}")
        
        return "\n".join(result_lines)
    except Exception as e:
        if "404" in str(e):
            return _site_not_found_error(site_url)
        return f"Error retrieving advanced search analytics: {str(e)}"

@mcp.tool()
async def compare_search_periods(
    site_url: str,
    period1_start: str,
    period1_end: str,
    period2_start: str,
    period2_end: str,
    dimensions: str = "query",
    limit: int = 10
) -> str:
    """
    Compare search analytics data between two time periods.
    
    Args:
        site_url: Exact GSC property URL from list_properties (e.g. "https://example.com/" or
                  "sc-domain:example.com"). Domain properties cover all subdomains — use the
                  domain property as site_url and filter by page to analyze a specific subdomain.
        period1_start: Start date for period 1 (YYYY-MM-DD)
        period1_end: End date for period 1 (YYYY-MM-DD)
        period2_start: Start date for period 2 (YYYY-MM-DD)
        period2_end: End date for period 2 (YYYY-MM-DD)
        dimensions: Dimensions to group by (default: query)
        limit: Number of top results to compare (default: 10)
    """
    try:
        service = get_gsc_service()
        
        # Parse dimensions
        dimension_list = [d.strip() for d in dimensions.split(",")]
        
        # Build requests for both periods
        period1_request = {
            "startDate": period1_start,
            "endDate": period1_end,
            "dimensions": dimension_list,
            "rowLimit": 1000,  # Get more to ensure we can match items between periods
            "dataState": DATA_STATE
        }
        
        period2_request = {
            "startDate": period2_start,
            "endDate": period2_end,
            "dimensions": dimension_list,
            "rowLimit": 1000,
            "dataState": DATA_STATE
        }
        
        # Execute requests
        period1_response = service.searchanalytics().query(siteUrl=site_url, body=period1_request).execute()
        period2_response = service.searchanalytics().query(siteUrl=site_url, body=period2_request).execute()
        
        period1_rows = period1_response.get("rows", [])
        period2_rows = period2_response.get("rows", [])
        
        if not period1_rows and not period2_rows:
            return f"No data found for either period for {site_url}."
        
        # Create dictionaries for easy lookup
        period1_data = {tuple(row.get("keys", [])): row for row in period1_rows}
        period2_data = {tuple(row.get("keys", [])): row for row in period2_rows}
        
        # Find common keys and calculate differences
        all_keys = set(period1_data.keys()) | set(period2_data.keys())
        comparison_data = []
        
        for key in all_keys:
            p1_row = period1_data.get(key, {"clicks": 0, "impressions": 0, "ctr": 0, "position": 0})
            p2_row = period2_data.get(key, {"clicks": 0, "impressions": 0, "ctr": 0, "position": 0})
            
            # Calculate differences
            click_diff = p2_row.get("clicks", 0) - p1_row.get("clicks", 0)
            click_pct = (click_diff / p1_row.get("clicks", 1)) * 100 if p1_row.get("clicks", 0) > 0 else float('inf')
            
            imp_diff = p2_row.get("impressions", 0) - p1_row.get("impressions", 0)
            imp_pct = (imp_diff / p1_row.get("impressions", 1)) * 100 if p1_row.get("impressions", 0) > 0 else float('inf')
            
            ctr_diff = p2_row.get("ctr", 0) - p1_row.get("ctr", 0)
            pos_diff = p1_row.get("position", 0) - p2_row.get("position", 0)  # Note: lower position is better
            
            comparison_data.append({
                "key": key,
                "p1_clicks": p1_row.get("clicks", 0),
                "p2_clicks": p2_row.get("clicks", 0),
                "click_diff": click_diff,
                "click_pct": click_pct,
                "p1_impressions": p1_row.get("impressions", 0),
                "p2_impressions": p2_row.get("impressions", 0),
                "imp_diff": imp_diff,
                "imp_pct": imp_pct,
                "p1_ctr": p1_row.get("ctr", 0),
                "p2_ctr": p2_row.get("ctr", 0),
                "ctr_diff": ctr_diff,
                "p1_position": p1_row.get("position", 0),
                "p2_position": p2_row.get("position", 0),
                "pos_diff": pos_diff
            })
        
        # Sort by absolute click difference (can change to other metrics)
        comparison_data.sort(key=lambda x: abs(x["click_diff"]), reverse=True)
        
        # Format results
        result_lines = [f"Search analytics comparison for {site_url}:"]
        result_lines.append(f"Period 1: {period1_start} to {period1_end}")
        result_lines.append(f"Period 2: {period2_start} to {period2_end}")
        result_lines.append(f"Dimension(s): {dimensions}")
        result_lines.append(f"Top {min(limit, len(comparison_data))} results by change in clicks:")
        result_lines.append("\n" + "-" * 100 + "\n")
        
        # Create header
        dim_header = " | ".join([d.capitalize() for d in dimension_list])
        result_lines.append(f"{dim_header} | P1 Clicks | P2 Clicks | Change | % | P1 Pos | P2 Pos | Pos Δ")
        result_lines.append("-" * 100)
        
        # Add data rows (limited to requested number)
        for item in comparison_data[:limit]:
            key_str = " | ".join([str(k)[:100] for k in item["key"]])
            
            # Format the click change with color indicators
            click_change = item["click_diff"]
            click_pct = item["click_pct"] if item["click_pct"] != float('inf') else "N/A"
            click_pct_str = f"{click_pct:.1f}%" if click_pct != "N/A" else "N/A"
            
            # Format position change (positive is good - moving up in rankings)
            pos_change = item["pos_diff"]
            
            result_lines.append(
                f"{key_str} | {item['p1_clicks']} | {item['p2_clicks']} | "
                f"{click_change:+d} | {click_pct_str} | "
                f"{item['p1_position']:.1f} | {item['p2_position']:.1f} | {pos_change:+.1f}"
            )
        
        return "\n".join(result_lines)
    except Exception as e:
        if "404" in str(e):
            return _site_not_found_error(site_url)
        return f"Error comparing search periods: {str(e)}"

@mcp.tool()
async def get_search_by_page_query(
    site_url: str,
    page_url: str,
    days: int = 28,
    row_limit: int = 20
) -> str:
    """
    Get search analytics data for a specific page, broken down by query.
    
    Args:
        site_url: Exact GSC property URL from list_properties (e.g. "https://example.com/" or
                  "sc-domain:example.com"). Domain properties cover all subdomains — use the
                  domain property as site_url and filter by page to analyze a specific subdomain.
        page_url: The specific page URL to analyze
        days: Number of days to look back (default: 28)
        row_limit: Number of rows to return (default: 20, max: 500). Use 5-20 for quick overviews,
                   50-200 for deeper analysis, up to 500 for comprehensive reports. For bulk exports
                   beyond 500 rows, use get_advanced_search_analytics which supports pagination.
    """
    try:
        service = get_gsc_service()
        
        # Calculate date range
        end_date = datetime.now().date()
        start_date = end_date - timedelta(days=days)
        
        # Build request with page filter
        request = {
            "startDate": start_date.strftime("%Y-%m-%d"),
            "endDate": end_date.strftime("%Y-%m-%d"),
            "dimensions": ["query"],
            "dimensionFilterGroups": [{
                "filters": [{
                    "dimension": "page",
                    "operator": "equals",
                    "expression": page_url
                }]
            }],
            "rowLimit": min(max(1, row_limit), 500),
            "orderBy": [{"metric": "CLICK_COUNT", "direction": "descending"}],
            "dataState": DATA_STATE
        }
        
        # Execute request
        response = service.searchanalytics().query(siteUrl=site_url, body=request).execute()
        
        if not response.get("rows"):
            return f"No search data found for page {page_url} in the last {days} days."
        
        # Format results
        result_lines = [f"Search queries for page {page_url} (last {days} days):"]
        result_lines.append("\n" + "-" * 80 + "\n")
        
        # Create header
        result_lines.append("Query | Clicks | Impressions | CTR | Position")
        result_lines.append("-" * 80)
        
        # Add data rows
        for row in response.get("rows", []):
            query = row.get("keys", ["Unknown"])[0]
            clicks = row.get("clicks", 0)
            impressions = row.get("impressions", 0)
            ctr = row.get("ctr", 0) * 100
            position = row.get("position", 0)
            
            result_lines.append(f"{query[:100]} | {clicks} | {impressions} | {ctr:.2f}% | {position:.1f}")
        
        # Add total metrics
        total_clicks = sum(row.get("clicks", 0) for row in response.get("rows", []))
        total_impressions = sum(row.get("impressions", 0) for row in response.get("rows", []))
        avg_ctr = (total_clicks / total_impressions * 100) if total_impressions > 0 else 0
        
        result_lines.append("-" * 80)
        result_lines.append(f"TOTAL | {total_clicks} | {total_impressions} | {avg_ctr:.2f}% | -")
        
        return "\n".join(result_lines)
    except Exception as e:
        return f"Error retrieving page query data: {str(e)}"

@mcp.tool()
async def list_sitemaps_enhanced(site_url: str, sitemap_index: str = None) -> str:
    """
    List all sitemaps for a specific Search Console property with detailed information.
    
    Args:
        site_url: Exact GSC property URL from list_properties (e.g. "https://example.com/" or
                  "sc-domain:example.com"). Domain properties cover all subdomains — use the
                  domain property as site_url and filter by page to analyze a specific subdomain.
        sitemap_index: Optional sitemap index URL to list child sitemaps
    """
    try:
        service = get_gsc_service()
        
        # Get sitemaps list
        if sitemap_index:
            sitemaps = service.sitemaps().list(siteUrl=site_url, sitemapIndex=sitemap_index).execute()
            source = f"child sitemaps from index: {sitemap_index}"
        else:
            sitemaps = service.sitemaps().list(siteUrl=site_url).execute()
            source = "all submitted sitemaps"
        
        if not sitemaps.get("sitemap"):
            return f"No sitemaps found for {site_url}" + (f" in index {sitemap_index}" if sitemap_index else ".")
        
        # Format the results
        result_lines = [f"Sitemaps for {site_url} ({source}):"]
        result_lines.append("-" * 100)
        
        # Header
        result_lines.append("Path | Last Submitted | Last Downloaded | Type | URLs | Errors | Warnings")
        result_lines.append("-" * 100)
        
        # Add each sitemap
        for sitemap in sitemaps.get("sitemap", []):
            path = sitemap.get("path", "Unknown")
            
            # Format dates
            last_submitted = sitemap.get("lastSubmitted", "Never")
            if last_submitted != "Never":
                try:
                    dt = datetime.fromisoformat(last_submitted.replace('Z', '+00:00'))
                    last_submitted = dt.strftime("%Y-%m-%d %H:%M")
                except:
                    pass
            
            last_downloaded = sitemap.get("lastDownloaded", "Never")
            if last_downloaded != "Never":
                try:
                    dt = datetime.fromisoformat(last_downloaded.replace('Z', '+00:00'))
                    last_downloaded = dt.strftime("%Y-%m-%d %H:%M")
                except:
                    pass
            
            # Determine type
            sitemap_type = "Index" if sitemap.get("isSitemapsIndex", False) else "Sitemap"
            
            # Get counts
            errors = int(sitemap.get("errors", 0))
            warnings = int(sitemap.get("warnings", 0))

            # Get URL counts
            url_count = "N/A"
            if "contents" in sitemap:
                for content in sitemap["contents"]:
                    if content.get("type") == "web":
                        url_count = content.get("submitted", "0")
                        break
            
            result_lines.append(f"{path} | {last_submitted} | {last_downloaded} | {sitemap_type} | {url_count} | {errors} | {warnings}")
        
        # Add processing status if available
        pending_count = sum(1 for sitemap in sitemaps.get("sitemap", []) if sitemap.get("isPending", False))
        if pending_count > 0:
            result_lines.append(f"\nNote: {pending_count} sitemaps are still pending processing by Google.")
        
        return "\n".join(result_lines)
    except Exception as e:
        if "404" in str(e):
            return _site_not_found_error(site_url)
        return f"Error retrieving sitemaps: {str(e)}"

@mcp.tool()
async def get_sitemap_details(site_url: str, sitemap_url: str) -> str:
    """
    Get detailed information about a specific sitemap.
    
    Args:
        site_url: Exact GSC property URL from list_properties (e.g. "https://example.com/" or
                  "sc-domain:example.com"). Domain properties cover all subdomains — use the
                  domain property as site_url and filter by page to analyze a specific subdomain.
        sitemap_url: The full URL of the sitemap to inspect
    """
    try:
        service = get_gsc_service()
        
        # Get sitemap details
        details = service.sitemaps().get(siteUrl=site_url, feedpath=sitemap_url).execute()
        
        if not details:
            return f"No details found for sitemap {sitemap_url}."
        
        # Format the results
        result_lines = [f"Sitemap Details for {sitemap_url}:"]
        result_lines.append("-" * 80)
        
        # Basic info
        is_index = details.get("isSitemapsIndex", False)
        result_lines.append(f"Type: {'Sitemap Index' if is_index else 'Sitemap'}")
        
        # Status
        is_pending = details.get("isPending", False)
        result_lines.append(f"Status: {'Pending processing' if is_pending else 'Processed'}")
        
        # Dates
        if "lastSubmitted" in details:
            try:
                dt = datetime.fromisoformat(details["lastSubmitted"].replace('Z', '+00:00'))
                result_lines.append(f"Last Submitted: {dt.strftime('%Y-%m-%d %H:%M')}")
            except:
                result_lines.append(f"Last Submitted: {details['lastSubmitted']}")
        
        if "lastDownloaded" in details:
            try:
                dt = datetime.fromisoformat(details["lastDownloaded"].replace('Z', '+00:00'))
                result_lines.append(f"Last Downloaded: {dt.strftime('%Y-%m-%d %H:%M')}")
            except:
                result_lines.append(f"Last Downloaded: {details['lastDownloaded']}")
        
        # Errors and warnings
        result_lines.append(f"Errors: {details.get('errors', 0)}")
        result_lines.append(f"Warnings: {details.get('warnings', 0)}")
        
        # Content breakdown
        if "contents" in details and details["contents"]:
            result_lines.append("\nContent Breakdown:")
            for content in details["contents"]:
                content_type = content.get("type", "Unknown").upper()
                submitted = content.get("submitted", 0)
                indexed = content.get("indexed", "N/A")
                
                result_lines.append(f"- {content_type}: {submitted} submitted, {indexed} indexed")
        
        # If it's an index, suggest how to list child sitemaps
        if is_index:
            result_lines.append("\nThis is a sitemap index. To list child sitemaps, use:")
            result_lines.append(f"list_sitemaps_enhanced with sitemap_index={sitemap_url}")
        
        return "\n".join(result_lines)
    except Exception as e:
        return f"Error retrieving sitemap details: {str(e)}"

@mcp.tool()
async def submit_sitemap(site_url: str, sitemap_url: str) -> str:
    """
    Submit a new sitemap or resubmit an existing one to Google.
    
    Args:
        site_url: Exact GSC property URL from list_properties (e.g. "https://example.com/" or
                  "sc-domain:example.com"). Domain properties cover all subdomains — use the
                  domain property as site_url and filter by page to analyze a specific subdomain.
        sitemap_url: The full URL of the sitemap to submit
    """
    try:
        service = get_gsc_service()
        
        # Submit the sitemap
        service.sitemaps().submit(siteUrl=site_url, feedpath=sitemap_url).execute()
        
        # Verify submission by getting details
        try:
            details = service.sitemaps().get(siteUrl=site_url, feedpath=sitemap_url).execute()
            
            # Format response
            result_lines = [f"Successfully submitted sitemap: {sitemap_url}"]
            
            # Add submission time if available
            if "lastSubmitted" in details:
                try:
                    dt = datetime.fromisoformat(details["lastSubmitted"].replace('Z', '+00:00'))
                    result_lines.append(f"Submission time: {dt.strftime('%Y-%m-%d %H:%M')}")
                except:
                    result_lines.append(f"Submission time: {details['lastSubmitted']}")
            
            # Add processing status
            is_pending = details.get("isPending", True)
            result_lines.append(f"Status: {'Pending processing' if is_pending else 'Processing started'}")
            
            # Add note about processing time
            result_lines.append("\nNote: Google may take some time to process the sitemap. Check back later for full details.")
            
            return "\n".join(result_lines)
        except:
            # If we can't get details, just return basic success message
            return f"Successfully submitted sitemap: {sitemap_url}\n\nGoogle will queue it for processing."
    
    except Exception as e:
        return f"Error submitting sitemap: {str(e)}"

@mcp.tool()
async def delete_sitemap(site_url: str, sitemap_url: str) -> str:
    """
    Delete (unsubmit) a sitemap from Google Search Console.
    
    Args:
        site_url: Exact GSC property URL from list_properties (e.g. "https://example.com/" or
                  "sc-domain:example.com"). Domain properties cover all subdomains — use the
                  domain property as site_url and filter by page to analyze a specific subdomain.
        sitemap_url: The full URL of the sitemap to delete
    """
    try:
        service = get_gsc_service()
        
        # First check if the sitemap exists
        try:
            service.sitemaps().get(siteUrl=site_url, feedpath=sitemap_url).execute()
        except Exception as e:
            if "404" in str(e):
                return f"Sitemap not found: {sitemap_url}. It may have already been deleted or was never submitted."
            else:
                raise e
        
        # Delete the sitemap
        service.sitemaps().delete(siteUrl=site_url, feedpath=sitemap_url).execute()
        
        return f"Successfully deleted sitemap: {sitemap_url}\n\nNote: This only removes the sitemap from Search Console. Any URLs already indexed will remain in Google's index."
    
    except Exception as e:
        return f"Error deleting sitemap: {str(e)}"

@mcp.tool()
async def manage_sitemaps(site_url: str, action: str, sitemap_url: str = None, sitemap_index: str = None) -> str:
    """
    All-in-one tool to manage sitemaps (list, get details, submit, delete).
    
    Args:
        site_url: Exact GSC property URL from list_properties (e.g. "https://example.com/" or
                  "sc-domain:example.com"). Domain properties cover all subdomains — use the
                  domain property as site_url and filter by page to analyze a specific subdomain.
        action: The action to perform (list, details, submit, delete)
        sitemap_url: The full URL of the sitemap (required for details, submit, delete)
        sitemap_index: Optional sitemap index URL for listing child sitemaps (only used with 'list' action)
    """
    try:
        # Validate inputs
        action = action.lower().strip()
        valid_actions = ["list", "details", "submit", "delete"]
        
        if action not in valid_actions:
            return f"Invalid action: {action}. Please use one of: {', '.join(valid_actions)}"
        
        if action in ["details", "submit", "delete"] and not sitemap_url:
            return f"The {action} action requires a sitemap_url parameter."
        
        # Perform the requested action
        if action == "list":
            return await list_sitemaps_enhanced(site_url, sitemap_index)
        elif action == "details":
            return await get_sitemap_details(site_url, sitemap_url)
        elif action == "submit":
            return await submit_sitemap(site_url, sitemap_url)
        elif action == "delete":
            return await delete_sitemap(site_url, sitemap_url)
    
    except Exception as e:
        return f"Error managing sitemaps: {str(e)}"

@mcp.tool()
async def get_creator_info() -> str:
    """
    Provides information about Amin Foroutan, the creator of the MCP-GSC tool.
    """
    creator_info = """
# About the Creator: Amin Foroutan

Amin Foroutan is an SEO consultant with over a decade of experience, specializing in technical SEO, Python-driven tools, and data analysis for SEO performance.

## Connect with Amin:

- **LinkedIn**: [Amin Foroutan](https://www.linkedin.com/in/ma-foroutan/)
- **Personal Website**: [aminforoutan.com](https://aminforoutan.com/)
- **YouTube**: [Amin Forout](https://www.youtube.com/channel/UCW7tPXg-rWdH4YzLrcAdBIw)
- **X (Twitter)**: [@aminfseo](https://x.com/aminfseo)

## Notable Projects:

Amin has created several popular SEO tools including:
- Advanced GSC Visualizer (6.4K+ users)
- SEO Render Insight Tool (3.5K+ users)
- Google AI Overview Impact Analysis (1.2K+ users)
- Google AI Overview Citation Analysis (900+ users)
- SEMRush Enhancer (570+ users)
- SEO Page Inspector (115+ users)

## Expertise:

Amin combines technical SEO knowledge with programming skills to create innovative solutions for SEO challenges.
"""
    return creator_info

@mcp.tool()
async def reauthenticate() -> str:
    """
    Perform a logout and new login sequence.
    Deletes the current OAuth token file and triggers the browser authentication flow.
    Useful when you need to switch to a different Google account.
    """
    try:
        # Delete existing token to force re-authentication
        if os.path.exists(TOKEN_FILE):
            os.remove(TOKEN_FILE)
            token_deleted = True
        else:
            token_deleted = False

        # Check if OAuth client secrets file exists
        if not os.path.exists(OAUTH_CLIENT_SECRETS_FILE):
            return (
                "Error: OAuth client secrets file not found. "
                "Cannot start new authentication flow. "
                "Please ensure client_secrets.json is present or set the "
                "GSC_OAUTH_CLIENT_SECRETS_FILE environment variable."
            )

        # Trigger new OAuth flow — this opens a browser window on the local machine
        flow = InstalledAppFlow.from_client_secrets_file(OAUTH_CLIENT_SECRETS_FILE, SCOPES)
        creds = flow.run_local_server(port=0)

        # Save the new credentials for future use
        with open(TOKEN_FILE, "w") as token:
            token.write(creds.to_json())

        msg = "Successfully authenticated with a new Google account."
        if token_deleted:
            msg = "Previous session deleted. " + msg
        return msg

    except Exception as e:
        return f"Error during reauthentication: {str(e)}"


# ═══════════════════════════════════════════════════════════════════════
# Enhanced Analytics Tools — added 2026-03-30
# ═══════════════════════════════════════════════════════════════════════

@mcp.tool()
async def get_top_growing_queries(site_url: str, days: int = 28, row_limit: int = 20, metric: str = "clicks") -> str:
    """
    Find queries with the biggest growth comparing recent period vs previous period.
    Splits the date range in half and compares. Great for spotting trending keywords.

    Args:
        site_url: Exact GSC property URL from list_properties (e.g. "https://example.com/" or
                  "sc-domain:example.com"). Domain properties cover all subdomains — use the
                  domain property as site_url and filter by page to analyze a specific subdomain.
        days: Total lookback window (split in half for comparison). Default 28.
        row_limit: Number of top growing queries to return. Default 20.
        metric: Metric to measure growth by — clicks, impressions, ctr, or position. Default clicks.
    """
    try:
        service = get_gsc_service()
        half = days // 2
        end = datetime.now().date()
        mid = end - timedelta(days=half)
        start = end - timedelta(days=days)

        body_recent = {
            "startDate": str(mid),
            "endDate": str(end),
            "dimensions": ["query"],
            "rowLimit": 500,
            "dataState": DATA_STATE,
        }
        body_previous = {
            "startDate": str(start),
            "endDate": str(mid - timedelta(days=1)),
            "dimensions": ["query"],
            "rowLimit": 500,
            "dataState": DATA_STATE,
        }

        recent = service.searchanalytics().query(siteUrl=site_url, body=body_recent).execute()
        previous = service.searchanalytics().query(siteUrl=site_url, body=body_previous).execute()

        recent_map = {}
        for row in recent.get("rows", []):
            q = row["keys"][0]
            recent_map[q] = row

        prev_map = {}
        for row in previous.get("rows", []):
            q = row["keys"][0]
            prev_map[q] = row

        growth_data = []
        for q, r in recent_map.items():
            p = prev_map.get(q)
            if metric == "position":
                r_val = r.get("position", 0)
                p_val = p.get("position", 100) if p else 100
                change = p_val - r_val  # positive = improved
            else:
                r_val = r.get(metric, 0)
                p_val = p.get(metric, 0) if p else 0
                change = r_val - p_val
            growth_data.append({
                "query": q,
                "recent": r_val,
                "previous": p_val,
                "change": change,
                "recent_clicks": r.get("clicks", 0),
                "recent_impressions": r.get("impressions", 0),
                "recent_ctr": r.get("ctr", 0),
                "recent_position": r.get("position", 0),
            })

        growth_data.sort(key=lambda x: x["change"], reverse=True)
        top = growth_data[:row_limit]

        lines = [f"Top Growing Queries by {metric} for {site_url}"]
        lines.append(f"Period: {start} to {mid - timedelta(days=1)} vs {mid} to {end}")
        lines.append("-" * 100)
        lines.append(f"{'Query':<50} {'Previous':>10} {'Recent':>10} {'Change':>10} {'Clicks':>8} {'Impr':>8} {'Pos':>6}")
        lines.append("-" * 100)
        for item in top:
            q = item["query"][:48]
            if metric == "ctr":
                prev_str = f"{item['previous']*100:.1f}%"
                rec_str = f"{item['recent']*100:.1f}%"
                chg_str = f"+{item['change']*100:.1f}%" if item["change"] > 0 else f"{item['change']*100:.1f}%"
            elif metric == "position":
                prev_str = f"{item['previous']:.1f}"
                rec_str = f"{item['recent']:.1f}"
                chg_str = f"+{item['change']:.1f}" if item["change"] > 0 else f"{item['change']:.1f}"
            else:
                prev_str = str(int(item["previous"]))
                rec_str = str(int(item["recent"]))
                chg_str = f"+{int(item['change'])}" if item["change"] > 0 else str(int(item["change"]))
            lines.append(f"{q:<50} {prev_str:>10} {rec_str:>10} {chg_str:>10} {int(item['recent_clicks']):>8} {int(item['recent_impressions']):>8} {item['recent_position']:>6.1f}")

        return json.dumps({"result": "\n".join(lines)})

    except HttpError as e:
        if e.resp.status == 404:
            return json.dumps({"result": _site_not_found_error(site_url)})
        return json.dumps({"result": f"HTTP error: {str(e)}"})
    except Exception as e:
        return json.dumps({"result": f"Error: {str(e)}"})


@mcp.tool()
async def get_top_declining_queries(site_url: str, days: int = 28, row_limit: int = 20, metric: str = "clicks") -> str:
    """
    Find queries with the biggest decline comparing recent period vs previous period.
    Helps identify keywords losing traction that may need attention.

    Args:
        site_url: Exact GSC property URL from list_properties (e.g. "https://example.com/" or
                  "sc-domain:example.com"). Domain properties cover all subdomains — use the
                  domain property as site_url and filter by page to analyze a specific subdomain.
        days: Total lookback window (split in half for comparison). Default 28.
        row_limit: Number of top declining queries to return. Default 20.
        metric: Metric to measure decline by — clicks, impressions, ctr, or position. Default clicks.
    """
    try:
        service = get_gsc_service()
        half = days // 2
        end = datetime.now().date()
        mid = end - timedelta(days=half)
        start = end - timedelta(days=days)

        body_recent = {
            "startDate": str(mid),
            "endDate": str(end),
            "dimensions": ["query"],
            "rowLimit": 500,
            "dataState": DATA_STATE,
        }
        body_previous = {
            "startDate": str(start),
            "endDate": str(mid - timedelta(days=1)),
            "dimensions": ["query"],
            "rowLimit": 500,
            "dataState": DATA_STATE,
        }

        recent = service.searchanalytics().query(siteUrl=site_url, body=body_recent).execute()
        previous = service.searchanalytics().query(siteUrl=site_url, body=body_previous).execute()

        recent_map = {row["keys"][0]: row for row in recent.get("rows", [])}
        prev_map = {row["keys"][0]: row for row in previous.get("rows", [])}

        decline_data = []
        for q, p in prev_map.items():
            r = recent_map.get(q)
            if metric == "position":
                p_val = p.get("position", 0)
                r_val = r.get("position", 100) if r else 100
                change = p_val - r_val  # negative = declined
            else:
                p_val = p.get(metric, 0)
                r_val = r.get(metric, 0) if r else 0
                change = r_val - p_val  # negative = declined

            decline_data.append({
                "query": q,
                "recent": r_val,
                "previous": p_val,
                "change": change,
                "prev_clicks": p.get("clicks", 0),
                "prev_impressions": p.get("impressions", 0),
            })

        decline_data.sort(key=lambda x: x["change"])
        top = decline_data[:row_limit]

        lines = [f"Top Declining Queries by {metric} for {site_url}"]
        lines.append(f"Period: {start} to {mid - timedelta(days=1)} vs {mid} to {end}")
        lines.append("-" * 90)
        lines.append(f"{'Query':<50} {'Previous':>10} {'Recent':>10} {'Change':>10}")
        lines.append("-" * 90)
        for item in top:
            q = item["query"][:48]
            if metric == "ctr":
                lines.append(f"{q:<50} {item['previous']*100:>9.1f}% {item['recent']*100:>9.1f}% {item['change']*100:>+9.1f}%")
            elif metric == "position":
                lines.append(f"{q:<50} {item['previous']:>10.1f} {item['recent']:>10.1f} {item['change']:>+10.1f}")
            else:
                lines.append(f"{q:<50} {int(item['previous']):>10} {int(item['recent']):>10} {int(item['change']):>+10}")

        return json.dumps({"result": "\n".join(lines)})

    except HttpError as e:
        if e.resp.status == 404:
            return json.dumps({"result": _site_not_found_error(site_url)})
        return json.dumps({"result": f"HTTP error: {str(e)}"})
    except Exception as e:
        return json.dumps({"result": f"Error: {str(e)}"})


@mcp.tool()
async def get_content_opportunities(site_url: str, days: int = 28, min_impressions: int = 50, max_ctr: float = 0.03, row_limit: int = 30) -> str:
    """
    Find high-impression, low-CTR queries — content optimization opportunities.
    These are queries where your pages show up often but rarely get clicked,
    indicating potential for title/description improvements or content gaps.

    Args:
        site_url: Exact GSC property URL from list_properties (e.g. "https://example.com/" or
                  "sc-domain:example.com"). Domain properties cover all subdomains — use the
                  domain property as site_url and filter by page to analyze a specific subdomain.
        days: Number of days to look back. Default 28.
        min_impressions: Minimum impressions threshold. Default 50.
        max_ctr: Maximum CTR threshold (queries below this are opportunities). Default 0.03 (3%).
        row_limit: Number of opportunities to return. Default 30.
    """
    try:
        service = get_gsc_service()
        end = datetime.now().date()
        start = end - timedelta(days=days)

        body = {
            "startDate": str(start),
            "endDate": str(end),
            "dimensions": ["query", "page"],
            "rowLimit": 1000,
            "dataState": DATA_STATE,
        }

        result = service.searchanalytics().query(siteUrl=site_url, body=body).execute()
        rows = result.get("rows", [])

        opportunities = []
        for row in rows:
            impressions = row.get("impressions", 0)
            ctr = row.get("ctr", 0)
            if impressions >= min_impressions and ctr <= max_ctr:
                opportunities.append({
                    "query": row["keys"][0],
                    "page": row["keys"][1],
                    "clicks": row.get("clicks", 0),
                    "impressions": impressions,
                    "ctr": ctr,
                    "position": row.get("position", 0),
                    "potential_clicks": int(impressions * 0.05) - row.get("clicks", 0),
                })

        opportunities.sort(key=lambda x: x["potential_clicks"], reverse=True)
        top = opportunities[:row_limit]

        lines = [f"Content Opportunities for {site_url} (last {days} days)"]
        lines.append(f"Filter: impressions >= {min_impressions}, CTR <= {max_ctr*100:.0f}%")
        lines.append(f"Found {len(opportunities)} opportunities, showing top {len(top)}")
        lines.append("-" * 120)
        lines.append(f"{'Query':<40} {'Page':<35} {'Impr':>7} {'Clicks':>7} {'CTR':>7} {'Pos':>6} {'Potential':>10}")
        lines.append("-" * 120)
        for item in top:
            q = item["query"][:38]
            p = item["page"].replace("https://hjlabs.in", "")[:33]
            lines.append(f"{q:<40} {p:<35} {item['impressions']:>7} {item['clicks']:>7} {item['ctr']*100:>6.1f}% {item['position']:>6.1f} +{item['potential_clicks']:>8}")

        return json.dumps({"result": "\n".join(lines)})

    except HttpError as e:
        if e.resp.status == 404:
            return json.dumps({"result": _site_not_found_error(site_url)})
        return json.dumps({"result": f"HTTP error: {str(e)}"})
    except Exception as e:
        return json.dumps({"result": f"Error: {str(e)}"})


@mcp.tool()
async def get_keyword_cannibalization(site_url: str, days: int = 28, min_impressions: int = 10, row_limit: int = 20) -> str:
    """
    Detect keyword cannibalization — queries where multiple pages compete for the same keyword.
    This hurts SEO when Google can't decide which page to rank.

    Args:
        site_url: Exact GSC property URL from list_properties (e.g. "https://example.com/" or
                  "sc-domain:example.com"). Domain properties cover all subdomains — use the
                  domain property as site_url and filter by page to analyze a specific subdomain.
        days: Number of days to look back. Default 28.
        min_impressions: Minimum total impressions for the query. Default 10.
        row_limit: Number of cannibalized queries to return. Default 20.
    """
    try:
        service = get_gsc_service()
        end = datetime.now().date()
        start = end - timedelta(days=days)

        body = {
            "startDate": str(start),
            "endDate": str(end),
            "dimensions": ["query", "page"],
            "rowLimit": 5000,
            "dataState": DATA_STATE,
        }

        result = service.searchanalytics().query(siteUrl=site_url, body=body).execute()
        rows = result.get("rows", [])

        # Group by query
        query_pages = {}
        for row in rows:
            q = row["keys"][0]
            page = row["keys"][1]
            if q not in query_pages:
                query_pages[q] = []
            query_pages[q].append({
                "page": page,
                "clicks": row.get("clicks", 0),
                "impressions": row.get("impressions", 0),
                "ctr": row.get("ctr", 0),
                "position": row.get("position", 0),
            })

        # Find queries with multiple pages
        cannibalized = []
        for q, pages in query_pages.items():
            if len(pages) < 2:
                continue
            total_impressions = sum(p["impressions"] for p in pages)
            if total_impressions < min_impressions:
                continue
            pages.sort(key=lambda x: x["clicks"], reverse=True)
            cannibalized.append({
                "query": q,
                "page_count": len(pages),
                "total_impressions": total_impressions,
                "total_clicks": sum(p["clicks"] for p in pages),
                "pages": pages[:3],  # top 3 pages
            })

        cannibalized.sort(key=lambda x: x["total_impressions"], reverse=True)
        top = cannibalized[:row_limit]

        lines = [f"Keyword Cannibalization Report for {site_url} (last {days} days)"]
        lines.append(f"Found {len(cannibalized)} queries competing across multiple pages")
        lines.append("=" * 100)
        for item in top:
            lines.append(f"\n🔍 \"{item['query']}\" — {item['page_count']} pages, {item['total_impressions']} impressions, {item['total_clicks']} clicks")
            for p in item["pages"]:
                pg = p["page"].replace("https://hjlabs.in", "")[:60]
                lines.append(f"   {pg:<60} clicks={p['clicks']} impr={p['impressions']} pos={p['position']:.1f}")

        return json.dumps({"result": "\n".join(lines)})

    except HttpError as e:
        if e.resp.status == 404:
            return json.dumps({"result": _site_not_found_error(site_url)})
        return json.dumps({"result": f"HTTP error: {str(e)}"})
    except Exception as e:
        return json.dumps({"result": f"Error: {str(e)}"})


@mcp.tool()
async def get_device_breakdown(site_url: str, days: int = 28, page_url: str = None) -> str:
    """
    Get performance breakdown by device type (DESKTOP, MOBILE, TABLET).
    Optionally filter by a specific page URL.

    Args:
        site_url: Exact GSC property URL from list_properties (e.g. "https://example.com/" or
                  "sc-domain:example.com"). Domain properties cover all subdomains — use the
                  domain property as site_url and filter by page to analyze a specific subdomain.
        days: Number of days to look back. Default 28.
        page_url: Optional specific page URL to analyze. If omitted, shows site-wide breakdown.
    """
    try:
        service = get_gsc_service()
        end = datetime.now().date()
        start = end - timedelta(days=days)

        body = {
            "startDate": str(start),
            "endDate": str(end),
            "dimensions": ["device"],
            "dataState": DATA_STATE,
        }
        if page_url:
            body["dimensionFilterGroups"] = [{
                "filters": [{"dimension": "page", "operator": "equals", "expression": page_url}]
            }]

        result = service.searchanalytics().query(siteUrl=site_url, body=body).execute()
        rows = result.get("rows", [])

        total_clicks = sum(r.get("clicks", 0) for r in rows)
        total_impressions = sum(r.get("impressions", 0) for r in rows)

        target = page_url or site_url
        lines = [f"Device Breakdown for {target} (last {days} days)"]
        lines.append("-" * 80)
        lines.append(f"{'Device':<15} {'Clicks':>10} {'%':>7} {'Impressions':>14} {'%':>7} {'CTR':>8} {'Position':>10}")
        lines.append("-" * 80)
        for row in sorted(rows, key=lambda x: x.get("clicks", 0), reverse=True):
            device = row["keys"][0]
            clicks = row.get("clicks", 0)
            impressions = row.get("impressions", 0)
            ctr = row.get("ctr", 0)
            pos = row.get("position", 0)
            c_pct = (clicks / total_clicks * 100) if total_clicks else 0
            i_pct = (impressions / total_impressions * 100) if total_impressions else 0
            lines.append(f"{device:<15} {clicks:>10} {c_pct:>6.1f}% {impressions:>14} {i_pct:>6.1f}% {ctr*100:>7.2f}% {pos:>10.1f}")
        lines.append("-" * 80)
        lines.append(f"{'TOTAL':<15} {total_clicks:>10} {'100%':>7} {total_impressions:>14} {'100%':>7}")

        return json.dumps({"result": "\n".join(lines)})

    except HttpError as e:
        if e.resp.status == 404:
            return json.dumps({"result": _site_not_found_error(site_url)})
        return json.dumps({"result": f"HTTP error: {str(e)}"})
    except Exception as e:
        return json.dumps({"result": f"Error: {str(e)}"})


@mcp.tool()
async def get_country_breakdown(site_url: str, days: int = 28, row_limit: int = 20, page_url: str = None) -> str:
    """
    Get performance breakdown by country. Optionally filter by a specific page.

    Args:
        site_url: Exact GSC property URL from list_properties (e.g. "https://example.com/" or
                  "sc-domain:example.com"). Domain properties cover all subdomains — use the
                  domain property as site_url and filter by page to analyze a specific subdomain.
        days: Number of days to look back. Default 28.
        row_limit: Number of countries to return. Default 20.
        page_url: Optional specific page URL to filter by.
    """
    try:
        service = get_gsc_service()
        end = datetime.now().date()
        start = end - timedelta(days=days)

        body = {
            "startDate": str(start),
            "endDate": str(end),
            "dimensions": ["country"],
            "rowLimit": row_limit,
            "dataState": DATA_STATE,
        }
        if page_url:
            body["dimensionFilterGroups"] = [{
                "filters": [{"dimension": "page", "operator": "equals", "expression": page_url}]
            }]

        result = service.searchanalytics().query(siteUrl=site_url, body=body).execute()
        rows = result.get("rows", [])

        total_clicks = sum(r.get("clicks", 0) for r in rows)

        target = page_url or site_url
        lines = [f"Country Breakdown for {target} (last {days} days)"]
        lines.append("-" * 80)
        lines.append(f"{'Country':<10} {'Clicks':>10} {'Share':>8} {'Impressions':>14} {'CTR':>8} {'Position':>10}")
        lines.append("-" * 80)
        for row in rows:
            country = row["keys"][0]
            clicks = row.get("clicks", 0)
            impressions = row.get("impressions", 0)
            ctr = row.get("ctr", 0)
            pos = row.get("position", 0)
            share = (clicks / total_clicks * 100) if total_clicks else 0
            lines.append(f"{country:<10} {clicks:>10} {share:>7.1f}% {impressions:>14} {ctr*100:>7.2f}% {pos:>10.1f}")

        return json.dumps({"result": "\n".join(lines)})

    except HttpError as e:
        if e.resp.status == 404:
            return json.dumps({"result": _site_not_found_error(site_url)})
        return json.dumps({"result": f"HTTP error: {str(e)}"})
    except Exception as e:
        return json.dumps({"result": f"Error: {str(e)}"})


@mcp.tool()
async def get_daily_trend(site_url: str, days: int = 28, page_url: str = None, query_filter: str = None) -> str:
    """
    Get day-by-day performance trend. Useful for spotting traffic drops/spikes.
    Optionally filter by page URL or query.

    Args:
        site_url: Exact GSC property URL from list_properties (e.g. "https://example.com/" or
                  "sc-domain:example.com"). Domain properties cover all subdomains — use the
                  domain property as site_url and filter by page to analyze a specific subdomain.
        days: Number of days to look back. Default 28.
        page_url: Optional page URL to filter by.
        query_filter: Optional query string to filter by (contains match).
    """
    try:
        service = get_gsc_service()
        end = datetime.now().date()
        start = end - timedelta(days=days)

        body = {
            "startDate": str(start),
            "endDate": str(end),
            "dimensions": ["date"],
            "rowLimit": days + 5,
            "dataState": DATA_STATE,
        }

        filters = []
        if page_url:
            filters.append({"dimension": "page", "operator": "equals", "expression": page_url})
        if query_filter:
            filters.append({"dimension": "query", "operator": "contains", "expression": query_filter})
        if filters:
            body["dimensionFilterGroups"] = [{"filters": filters}]

        result = service.searchanalytics().query(siteUrl=site_url, body=body).execute()
        rows = result.get("rows", [])

        target = page_url or site_url
        filter_str = f" (query contains '{query_filter}')" if query_filter else ""
        lines = [f"Daily Trend for {target}{filter_str}"]
        lines.append("-" * 70)
        lines.append(f"{'Date':<12} {'Clicks':>8} {'Impressions':>13} {'CTR':>8} {'Position':>10}")
        lines.append("-" * 70)
        total_clicks = 0
        total_impressions = 0
        for row in sorted(rows, key=lambda x: x["keys"][0]):
            date = row["keys"][0]
            clicks = row.get("clicks", 0)
            impressions = row.get("impressions", 0)
            ctr = row.get("ctr", 0)
            pos = row.get("position", 0)
            total_clicks += clicks
            total_impressions += impressions
            lines.append(f"{date:<12} {clicks:>8} {impressions:>13} {ctr*100:>7.2f}% {pos:>10.1f}")
        lines.append("-" * 70)
        avg_ctr = (total_clicks / total_impressions * 100) if total_impressions else 0
        lines.append(f"{'TOTAL':<12} {total_clicks:>8} {total_impressions:>13} {avg_ctr:>7.2f}%")

        return json.dumps({"result": "\n".join(lines)})

    except HttpError as e:
        if e.resp.status == 404:
            return json.dumps({"result": _site_not_found_error(site_url)})
        return json.dumps({"result": f"HTTP error: {str(e)}"})
    except Exception as e:
        return json.dumps({"result": f"Error: {str(e)}"})


@mcp.tool()
async def get_top_pages(site_url: str, days: int = 28, row_limit: int = 25, sort_by: str = "clicks") -> str:
    """
    Get top performing pages ranked by clicks, impressions, CTR, or position.

    Args:
        site_url: Exact GSC property URL from list_properties (e.g. "https://example.com/" or
                  "sc-domain:example.com"). Domain properties cover all subdomains — use the
                  domain property as site_url and filter by page to analyze a specific subdomain.
        days: Number of days to look back. Default 28.
        row_limit: Number of pages to return. Default 25.
        sort_by: Metric to sort by — clicks, impressions, ctr, or position. Default clicks.
    """
    try:
        service = get_gsc_service()
        end = datetime.now().date()
        start = end - timedelta(days=days)

        body = {
            "startDate": str(start),
            "endDate": str(end),
            "dimensions": ["page"],
            "rowLimit": row_limit,
            "dataState": DATA_STATE,
        }

        result = service.searchanalytics().query(siteUrl=site_url, body=body).execute()
        rows = result.get("rows", [])

        if sort_by == "position":
            rows.sort(key=lambda x: x.get("position", 100))
        elif sort_by == "ctr":
            rows.sort(key=lambda x: x.get("ctr", 0), reverse=True)
        elif sort_by == "impressions":
            rows.sort(key=lambda x: x.get("impressions", 0), reverse=True)
        else:
            rows.sort(key=lambda x: x.get("clicks", 0), reverse=True)

        lines = [f"Top Pages for {site_url} (last {days} days, sorted by {sort_by})"]
        lines.append("-" * 100)
        lines.append(f"{'#':>3} {'Page':<50} {'Clicks':>8} {'Impressions':>12} {'CTR':>8} {'Position':>10}")
        lines.append("-" * 100)
        for i, row in enumerate(rows, 1):
            page = row["keys"][0].replace("https://hjlabs.in", "")[:48]
            clicks = row.get("clicks", 0)
            impressions = row.get("impressions", 0)
            ctr = row.get("ctr", 0)
            pos = row.get("position", 0)
            lines.append(f"{i:>3} {page:<50} {clicks:>8} {impressions:>12} {ctr*100:>7.2f}% {pos:>10.1f}")

        return json.dumps({"result": "\n".join(lines)})

    except HttpError as e:
        if e.resp.status == 404:
            return json.dumps({"result": _site_not_found_error(site_url)})
        return json.dumps({"result": f"HTTP error: {str(e)}"})
    except Exception as e:
        return json.dumps({"result": f"Error: {str(e)}"})


@mcp.tool()
async def get_page_query_matrix(site_url: str, days: int = 28, min_clicks: int = 0, row_limit: int = 100) -> str:
    """
    Get a comprehensive matrix showing which queries drive traffic to which pages.
    Useful for understanding page-query relationships and content strategy.

    Args:
        site_url: Exact GSC property URL from list_properties (e.g. "https://example.com/" or
                  "sc-domain:example.com"). Domain properties cover all subdomains — use the
                  domain property as site_url and filter by page to analyze a specific subdomain.
        days: Number of days to look back. Default 28.
        min_clicks: Minimum clicks threshold. Default 0.
        row_limit: Number of query-page pairs to return. Default 100.
    """
    try:
        service = get_gsc_service()
        end = datetime.now().date()
        start = end - timedelta(days=days)

        body = {
            "startDate": str(start),
            "endDate": str(end),
            "dimensions": ["page", "query"],
            "rowLimit": row_limit,
            "dataState": DATA_STATE,
        }

        result = service.searchanalytics().query(siteUrl=site_url, body=body).execute()
        rows = result.get("rows", [])

        # Group by page
        page_queries = {}
        for row in rows:
            page = row["keys"][0]
            query = row["keys"][1]
            clicks = row.get("clicks", 0)
            if clicks < min_clicks:
                continue
            if page not in page_queries:
                page_queries[page] = {"total_clicks": 0, "total_impressions": 0, "queries": []}
            page_queries[page]["total_clicks"] += clicks
            page_queries[page]["total_impressions"] += row.get("impressions", 0)
            page_queries[page]["queries"].append({
                "query": query,
                "clicks": clicks,
                "impressions": row.get("impressions", 0),
                "ctr": row.get("ctr", 0),
                "position": row.get("position", 0),
            })

        # Sort pages by total clicks
        sorted_pages = sorted(page_queries.items(), key=lambda x: x[1]["total_clicks"], reverse=True)

        lines = [f"Page-Query Matrix for {site_url} (last {days} days)"]
        lines.append("=" * 100)
        for page, data in sorted_pages:
            short_page = page.replace("https://hjlabs.in", "")[:70]
            lines.append(f"\n📄 {short_page}")
            lines.append(f"   Total: {data['total_clicks']} clicks, {data['total_impressions']} impressions")
            for q in sorted(data["queries"], key=lambda x: x["clicks"], reverse=True)[:10]:
                lines.append(f"   {'→'} {q['query'][:50]:<50} clicks={q['clicks']} impr={q['impressions']} pos={q['position']:.1f}")

        return json.dumps({"result": "\n".join(lines)})

    except HttpError as e:
        if e.resp.status == 404:
            return json.dumps({"result": _site_not_found_error(site_url)})
        return json.dumps({"result": f"HTTP error: {str(e)}"})
    except Exception as e:
        return json.dumps({"result": f"Error: {str(e)}"})


@mcp.tool()
async def get_seo_health_report(site_url: str, days: int = 28) -> str:
    """
    Generate a comprehensive SEO health report combining performance data,
    indexing status of key pages, and actionable recommendations.

    Args:
        site_url: Exact GSC property URL from list_properties (e.g. "https://example.com/" or
                  "sc-domain:example.com"). Domain properties cover all subdomains — use the
                  domain property as site_url and filter by page to analyze a specific subdomain.
        days: Number of days to look back. Default 28.
    """
    try:
        service = get_gsc_service()
        end = datetime.now().date()
        start = end - timedelta(days=days)
        half = days // 2
        mid = end - timedelta(days=half)

        # 1. Overall performance
        body_total = {
            "startDate": str(start),
            "endDate": str(end),
            "dataState": DATA_STATE,
        }
        total = service.searchanalytics().query(siteUrl=site_url, body=body_total).execute()
        t_rows = total.get("rows", [{}])
        t = t_rows[0] if t_rows else {}

        # 2. Recent vs previous
        body_recent = {"startDate": str(mid), "endDate": str(end), "dataState": DATA_STATE}
        body_prev = {"startDate": str(start), "endDate": str(mid - timedelta(days=1)), "dataState": DATA_STATE}
        recent = service.searchanalytics().query(siteUrl=site_url, body=body_recent).execute()
        prev = service.searchanalytics().query(siteUrl=site_url, body=body_prev).execute()
        r = recent.get("rows", [{}])[0] if recent.get("rows") else {}
        p = prev.get("rows", [{}])[0] if prev.get("rows") else {}

        # 3. Top pages
        body_pages = {
            "startDate": str(start), "endDate": str(end),
            "dimensions": ["page"], "rowLimit": 10, "dataState": DATA_STATE,
        }
        pages_result = service.searchanalytics().query(siteUrl=site_url, body=body_pages).execute()

        # 4. Device breakdown
        body_device = {
            "startDate": str(start), "endDate": str(end),
            "dimensions": ["device"], "dataState": DATA_STATE,
        }
        device_result = service.searchanalytics().query(siteUrl=site_url, body=body_device).execute()

        # 5. Sitemaps status
        sitemaps = service.sitemaps().list(siteUrl=site_url).execute()

        lines = ["=" * 80]
        lines.append(f"  SEO HEALTH REPORT — {site_url}")
        lines.append(f"  Period: {start} to {end} ({days} days)")
        lines.append("=" * 80)

        # Performance summary
        lines.append(f"\n📊 PERFORMANCE SUMMARY")
        lines.append(f"   Clicks:      {t.get('clicks', 0):>8}")
        lines.append(f"   Impressions: {t.get('impressions', 0):>8}")
        lines.append(f"   Avg CTR:     {t.get('ctr', 0)*100:>7.2f}%")
        lines.append(f"   Avg Position:{t.get('position', 0):>8.1f}")

        # Trend
        lines.append(f"\n📈 TREND (recent {half}d vs previous {half}d)")
        for metric in ["clicks", "impressions"]:
            rv = r.get(metric, 0)
            pv = p.get(metric, 0)
            change = rv - pv
            pct = (change / pv * 100) if pv else 0
            arrow = "↑" if change > 0 else "↓" if change < 0 else "→"
            lines.append(f"   {metric.capitalize():<14} {pv:>8} → {rv:>8}  {arrow} {pct:+.1f}%")

        # Device breakdown
        lines.append(f"\n📱 DEVICE BREAKDOWN")
        for row in device_result.get("rows", []):
            d = row["keys"][0]
            lines.append(f"   {d:<10} {row.get('clicks', 0):>6} clicks, {row.get('impressions', 0):>8} impr, CTR {row.get('ctr', 0)*100:.1f}%")

        # Top pages
        lines.append(f"\n📄 TOP PAGES")
        for i, row in enumerate(pages_result.get("rows", [])[:10], 1):
            pg = row["keys"][0].replace("https://", "")[:55]
            lines.append(f"   {i:>2}. {pg:<55} {row.get('clicks', 0):>5} clicks, pos {row.get('position', 0):.1f}")

        # Sitemaps
        lines.append(f"\n🗺️  SITEMAPS")
        for sm in sitemaps.get("sitemap", []):
            path = sm.get("path", "?")
            urls = sm.get("contents", [{}])[0].get("submitted", "?") if sm.get("contents") else "?"
            lines.append(f"   {path} — {urls} URLs")

        # Recommendations
        lines.append(f"\n💡 RECOMMENDATIONS")
        avg_ctr = t.get("ctr", 0)
        avg_pos = t.get("position", 0)
        if avg_ctr < 0.02:
            lines.append("   ⚠ Low CTR (<2%). Improve title tags and meta descriptions.")
        if avg_pos > 20:
            lines.append("   ⚠ High avg position (>20). Focus on content quality and backlinks.")
        r_clicks = r.get("clicks", 0)
        p_clicks = p.get("clicks", 0)
        if r_clicks < p_clicks * 0.8:
            lines.append("   ⚠ Clicks dropped >20% recently. Check for algorithm updates or technical issues.")
        lines.append("   ℹ Run get_content_opportunities to find quick-win keywords.")
        lines.append("   ℹ Run get_keyword_cannibalization to find competing pages.")

        lines.append("\n" + "=" * 80)
        return json.dumps({"result": "\n".join(lines)})

    except HttpError as e:
        if e.resp.status == 404:
            return json.dumps({"result": _site_not_found_error(site_url)})
        return json.dumps({"result": f"HTTP error: {str(e)}"})
    except Exception as e:
        return json.dumps({"result": f"Error: {str(e)}"})


# ═══════════════════════════════════════════════════════════════════════
# Additional Analytics Tools — added 2026-03-30
# ═══════════════════════════════════════════════════════════════════════

@mcp.tool()
async def get_position_distribution(site_url: str, days: int = 28, page_url: str = None) -> str:
    """
    Analyze ranking position distribution — how many queries rank in positions 1-3, 4-10, 11-20, 21-50, 50+.
    Helps understand overall ranking health and identify improvement buckets.

    Args:
        site_url: Exact GSC property URL from list_properties (e.g. "https://example.com/" or
                  "sc-domain:example.com"). Domain properties cover all subdomains — use the
                  domain property as site_url and filter by page to analyze a specific subdomain.
        days: Number of days to look back. Default 28.
        page_url: Optional page URL to filter by.
    """
    try:
        service = get_gsc_service()
        end = datetime.now().date()
        start = end - timedelta(days=days)

        body = {
            "startDate": str(start),
            "endDate": str(end),
            "dimensions": ["query"],
            "rowLimit": 5000,
            "dataState": DATA_STATE,
        }
        if page_url:
            body["dimensionFilterGroups"] = [{
                "filters": [{"dimension": "page", "operator": "equals", "expression": page_url}]
            }]

        result = service.searchanalytics().query(siteUrl=site_url, body=body).execute()
        rows = result.get("rows", [])

        buckets = {"1-3": [], "4-10": [], "11-20": [], "21-50": [], "50+": []}
        for row in rows:
            pos = row.get("position", 100)
            q = row["keys"][0]
            entry = {"query": q, "position": pos, "clicks": row.get("clicks", 0), "impressions": row.get("impressions", 0)}
            if pos <= 3: buckets["1-3"].append(entry)
            elif pos <= 10: buckets["4-10"].append(entry)
            elif pos <= 20: buckets["11-20"].append(entry)
            elif pos <= 50: buckets["21-50"].append(entry)
            else: buckets["50+"].append(entry)

        target = page_url or site_url
        lines = [f"Position Distribution for {target} (last {days} days)"]
        lines.append("=" * 80)
        total = len(rows)
        for bucket_name, items in buckets.items():
            count = len(items)
            pct = (count / total * 100) if total else 0
            total_clicks = sum(i["clicks"] for i in items)
            total_impr = sum(i["impressions"] for i in items)
            bar = "#" * int(pct / 2)
            lines.append(f"\n  Position {bucket_name:<6} | {count:>4} queries ({pct:>5.1f}%) | {total_clicks:>5} clicks | {total_impr:>7} impr")
            lines.append(f"  {bar}")
            # Show top queries in this bucket
            top_items = sorted(items, key=lambda x: x["impressions"], reverse=True)[:3]
            for item in top_items:
                lines.append(f"    → {item['query'][:45]:<45} pos {item['position']:.1f}  impr={item['impressions']}")

        lines.append(f"\nTotal queries: {total}")
        return json.dumps({"result": "\n".join(lines)})

    except HttpError as e:
        if e.resp.status == 404:
            return json.dumps({"result": _site_not_found_error(site_url)})
        return json.dumps({"result": f"HTTP error: {str(e)}"})
    except Exception as e:
        return json.dumps({"result": f"Error: {str(e)}"})


@mcp.tool()
async def get_zero_click_queries(site_url: str, days: int = 28, min_impressions: int = 5, row_limit: int = 30) -> str:
    """
    Find queries with impressions but ZERO clicks. These represent wasted visibility
    and potential for title/meta description optimization.

    Args:
        site_url: Exact GSC property URL from list_properties (e.g. "https://example.com/" or
                  "sc-domain:example.com"). Domain properties cover all subdomains — use the
                  domain property as site_url and filter by page to analyze a specific subdomain.
        days: Number of days to look back. Default 28.
        min_impressions: Minimum impressions to include. Default 5.
        row_limit: Max results. Default 30.
    """
    try:
        service = get_gsc_service()
        end = datetime.now().date()
        start = end - timedelta(days=days)

        body = {
            "startDate": str(start),
            "endDate": str(end),
            "dimensions": ["query", "page"],
            "rowLimit": 2000,
            "dataState": DATA_STATE,
        }

        result = service.searchanalytics().query(siteUrl=site_url, body=body).execute()
        rows = result.get("rows", [])

        zero_clicks = []
        for row in rows:
            if row.get("clicks", 0) == 0 and row.get("impressions", 0) >= min_impressions:
                zero_clicks.append({
                    "query": row["keys"][0],
                    "page": row["keys"][1],
                    "impressions": row.get("impressions", 0),
                    "position": row.get("position", 0),
                })

        zero_clicks.sort(key=lambda x: x["impressions"], reverse=True)
        top = zero_clicks[:row_limit]

        lines = [f"Zero-Click Queries for {site_url} (last {days} days, min {min_impressions} impressions)"]
        lines.append(f"Found {len(zero_clicks)} zero-click query-page pairs")
        lines.append("-" * 110)
        lines.append(f"{'Query':<40} {'Page':<40} {'Impressions':>12} {'Position':>10}")
        lines.append("-" * 110)
        for item in top:
            q = item["query"][:38]
            p = item["page"].replace("https://hjlabs.in", "")[:38]
            lines.append(f"{q:<40} {p:<40} {item['impressions']:>12} {item['position']:>10.1f}")

        total_wasted = sum(i["impressions"] for i in zero_clicks)
        lines.append(f"\nTotal wasted impressions: {total_wasted}")
        lines.append("Tip: Improve title tags and meta descriptions for high-impression queries with position < 10.")
        return json.dumps({"result": "\n".join(lines)})

    except HttpError as e:
        if e.resp.status == 404:
            return json.dumps({"result": _site_not_found_error(site_url)})
        return json.dumps({"result": f"HTTP error: {str(e)}"})
    except Exception as e:
        return json.dumps({"result": f"Error: {str(e)}"})


@mcp.tool()
async def get_query_clusters(site_url: str, days: int = 28, min_impressions: int = 3) -> str:
    """
    Group related search queries into semantic clusters based on shared words.
    Helps identify topic areas and content strategy opportunities.

    Args:
        site_url: Exact GSC property URL from list_properties (e.g. "https://example.com/" or
                  "sc-domain:example.com"). Domain properties cover all subdomains — use the
                  domain property as site_url and filter by page to analyze a specific subdomain.
        days: Number of days to look back. Default 28.
        min_impressions: Minimum impressions per query. Default 3.
    """
    try:
        service = get_gsc_service()
        end = datetime.now().date()
        start = end - timedelta(days=days)

        body = {
            "startDate": str(start),
            "endDate": str(end),
            "dimensions": ["query"],
            "rowLimit": 500,
            "dataState": DATA_STATE,
        }

        result = service.searchanalytics().query(siteUrl=site_url, body=body).execute()
        rows = result.get("rows", [])

        # Filter by min impressions
        queries = []
        for row in rows:
            if row.get("impressions", 0) >= min_impressions:
                queries.append({
                    "query": row["keys"][0],
                    "clicks": row.get("clicks", 0),
                    "impressions": row.get("impressions", 0),
                    "position": row.get("position", 0),
                })

        # Build keyword clusters by key terms
        stop_words = {"the", "a", "an", "in", "for", "of", "and", "to", "with", "is", "on", "by", "from"}
        clusters = {}
        for q_data in queries:
            words = [w.lower() for w in q_data["query"].split() if len(w) > 2 and w.lower() not in stop_words]
            for word in words:
                if word not in clusters:
                    clusters[word] = {"queries": [], "total_clicks": 0, "total_impressions": 0}
                clusters[word]["queries"].append(q_data)
                clusters[word]["total_clicks"] += q_data["clicks"]
                clusters[word]["total_impressions"] += q_data["impressions"]

        # Sort clusters by total impressions, filter out single-query clusters
        sorted_clusters = sorted(
            [(k, v) for k, v in clusters.items() if len(v["queries"]) >= 2],
            key=lambda x: x[1]["total_impressions"],
            reverse=True
        )

        lines = [f"Query Clusters for {site_url} (last {days} days)"]
        lines.append(f"Grouped {len(queries)} queries into {len(sorted_clusters)} topic clusters")
        lines.append("=" * 90)
        for keyword, data in sorted_clusters[:15]:
            lines.append(f"\n📌 \"{keyword}\" — {len(data['queries'])} queries, {data['total_impressions']} impr, {data['total_clicks']} clicks")
            for q in sorted(data["queries"], key=lambda x: x["impressions"], reverse=True)[:5]:
                lines.append(f"   → {q['query'][:50]:<50} impr={q['impressions']:>5} pos={q['position']:.1f}")

        return json.dumps({"result": "\n".join(lines)})

    except HttpError as e:
        if e.resp.status == 404:
            return json.dumps({"result": _site_not_found_error(site_url)})
        return json.dumps({"result": f"HTTP error: {str(e)}"})
    except Exception as e:
        return json.dumps({"result": f"Error: {str(e)}"})


@mcp.tool()
async def get_search_appearance(site_url: str, days: int = 28) -> str:
    """
    Get performance breakdown by search appearance type (web results, rich results,
    AMP, etc.). Shows how different SERP features perform for your site.

    Args:
        site_url: Exact GSC property URL from list_properties (e.g. "https://example.com/" or
                  "sc-domain:example.com"). Domain properties cover all subdomains — use the
                  domain property as site_url and filter by page to analyze a specific subdomain.
        days: Number of days to look back. Default 28.
    """
    try:
        service = get_gsc_service()
        end = datetime.now().date()
        start = end - timedelta(days=days)

        # Query for different search types
        search_types = ["WEB", "IMAGE", "VIDEO", "NEWS", "DISCOVER"]
        lines = [f"Search Appearance Report for {site_url} (last {days} days)"]
        lines.append("-" * 70)
        lines.append(f"{'Search Type':<15} {'Clicks':>10} {'Impressions':>14} {'CTR':>8} {'Avg Pos':>10}")
        lines.append("-" * 70)

        total_clicks = 0
        total_impressions = 0
        for st in search_types:
            try:
                body = {
                    "startDate": str(start),
                    "endDate": str(end),
                    "searchType": st,
                    "dataState": DATA_STATE,
                }
                result = service.searchanalytics().query(siteUrl=site_url, body=body).execute()
                rows = result.get("rows", [])
                if rows:
                    r = rows[0]
                    clicks = r.get("clicks", 0)
                    impressions = r.get("impressions", 0)
                    ctr = r.get("ctr", 0)
                    pos = r.get("position", 0)
                    total_clicks += clicks
                    total_impressions += impressions
                    lines.append(f"{st:<15} {clicks:>10} {impressions:>14} {ctr*100:>7.2f}% {pos:>10.1f}")
                else:
                    lines.append(f"{st:<15} {'0':>10} {'0':>14} {'0.00%':>8} {'N/A':>10}")
            except Exception:
                lines.append(f"{st:<15} {'—':>10} {'—':>14} {'—':>8} {'—':>10}")

        lines.append("-" * 70)
        lines.append(f"{'TOTAL':<15} {total_clicks:>10} {total_impressions:>14}")
        return json.dumps({"result": "\n".join(lines)})

    except HttpError as e:
        if e.resp.status == 404:
            return json.dumps({"result": _site_not_found_error(site_url)})
        return json.dumps({"result": f"HTTP error: {str(e)}"})
    except Exception as e:
        return json.dumps({"result": f"Error: {str(e)}"})


if __name__ == "__main__":
    # Start the MCP server on stdio transport
    mcp.run(transport="stdio")
