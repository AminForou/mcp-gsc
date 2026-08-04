"""Configuration and environment handling for the GSC MCP server.

Implements the readonly-scope, no-implicit-credential-discovery, and timezone
contract from gsc-mcp-fork-spec-fa.md (sections 3.1, 4.8, 4.9, 4.10, 10.3, 11, 12).
"""
from __future__ import annotations

import logging
import os
from zoneinfo import ZoneInfo
from typing import Any

# --- Auth scope (spec 3.1: least privilege, read-only) ---------------------
# The ONLY scope this server ever requests. No runtime upgrade path.
SCOPES: list[str] = ["https://www.googleapis.com/auth/webmasters.readonly"]

# --- Auth mode (spec 10.3: explicit choice, no silent fallback) -------------
# Allowed: "oauth" | "service_account". Any other value is a startup error.
# OAuth→SA fallback is explicitly forbidden — a clear error beats unexpected
# credential selection.
_raw_auth_mode = os.environ.get("GSC_AUTH_MODE", "oauth").strip().lower()
if _raw_auth_mode not in ("oauth", "service_account"):
    raise ValueError(
        f"Invalid GSC_AUTH_MODE value '{_raw_auth_mode}'. "
        "Accepted values are 'oauth' or 'service_account'. "
        "Automatic fallback between modes is disabled by design (spec 10.3)."
    )
AUTH_MODE: str = _raw_auth_mode

# --- Credential paths (spec 4.9: explicit, absolute, no discovery) ----------
# The server MUST NOT search the project dir or cwd for credentials. Only these
# env vars are consulted, and they must be absolute paths.
def _require_absolute(env_var: str) -> str | None:
    """Return an absolute path from an env var, or None if unset.

    Raises ValueError if the var is set but not absolute — relative paths cause
    silent lookup failures under uvx (the script dir is an unreachable cache).
    """
    raw = os.environ.get(env_var)
    if not raw:
        return None
    expanded = os.path.expandvars(os.path.expanduser(raw))
    if not os.path.isabs(expanded):
        raise ValueError(
            f"{env_var} must be an absolute path, got: {raw!r}. "
            "Under uvx the script directory is an internal cache you cannot "
            "reach — absolute paths are required."
        )
    return expanded


OAUTH_CLIENT_SECRETS_FILE: str | None = _require_absolute("GSC_OAUTH_CLIENT_SECRETS_FILE")
CREDENTIALS_PATH: str | None = _require_absolute("GSC_CREDENTIALS_PATH")
CONFIG_DIR_ENV: str | None = _require_absolute("GSC_CONFIG_DIR")

# --- Token storage (spec 10.1) ---------------------------------------------
from platformdirs import user_config_dir  # noqa: E402

_CONFIG_DIR = CONFIG_DIR_ENV or user_config_dir("gsc-seo-analyst-mcp")
os.makedirs(_CONFIG_DIR, exist_ok=True)
TOKEN_FILE: str = os.path.join(_CONFIG_DIR, "token.json")

# --- Data state (spec 4.8) -------------------------------------------------
# Default "final" = confirmed data only (2-3 day lag). "all" matches the GSC
# dashboard but may be incomplete; only used on explicit user request.
_raw_data_state = os.environ.get("GSC_DEFAULT_DATA_STATE", "final").strip().lower()
if _raw_data_state not in ("all", "final"):
    raise ValueError(
        f"Invalid GSC_DEFAULT_DATA_STATE value '{_raw_data_state}'. "
        "Accepted values are 'final' (default, confirmed data) or 'all' "
        "(may be incomplete, matches GSC dashboard)."
    )
DEFAULT_DATA_STATE: str = _raw_data_state

# --- Pagination & context-window protection (spec 3.4) ---------------------
DEFAULT_PAGE_SIZE: int = 500
MAX_PAGE_SIZE: int = 5000
MAX_ANALYSIS_ROWS: int = 10000
INSPECTION_CONCURRENCY: int = 2
REQUEST_TIMEOUT_SECONDS: int = 30

# --- Transport (spec 4.10: stdio only) -------------------------------------
TRANSPORT: str = os.environ.get("MCP_TRANSPORT", "stdio").strip().lower()
if TRANSPORT != "stdio":
    raise ValueError(
        f"MCP_TRANSPORT='{TRANSPORT}' is not supported in v1.0. "
        "Only 'stdio' is allowed. Streamable HTTP / SSE and the DNS-rebinding "
        "protection bypass have been removed (spec 4.10)."
    )

# --- Timezone (spec 4.8) ----------------------------------------------------
# All default date math is in Pacific Time, matching GSC's data freshness cycle.
# On Windows, the stdlib zoneinfo DB is empty; pull tzdata from the backports
# package so ZoneInfo("America/Los_Angeles") resolves.
try:
    GSC_TIMEZONE: ZoneInfo = ZoneInfo("America/Los_Angeles")
except Exception:  # pragma: no cover — fallback if tzdata is somehow missing
    import tzdata  # noqa: F401 — registering the tzdata package's zones
    GSC_TIMEZONE = ZoneInfo("America/Los_Angeles")
# Strategic-report default: end = current_PT - 3 days, start = end - 27 days
# (28-day inclusive range).
DEFAULT_REPORT_LAG_DAYS: int = 3
DEFAULT_REPORT_WINDOW_DAYS: int = 28

# --- Client registry (spec 6) ----------------------------------------------
CLIENTS_CONFIG: str | None = _require_absolute("GSC_CLIENTS_CONFIG")

# --- Logging & privacy (spec 12) -------------------------------------------
LOG_LEVEL: str = os.environ.get("GSC_LOG_LEVEL", "INFO").upper()
# Default: never log user query text or full analytics output.
LOG_QUERY_VALUES: bool = os.environ.get("GSC_LOG_QUERY_VALUES", "false").lower() in ("true", "1", "yes")
LOG_PROPERTY_URLS: bool = os.environ.get("GSC_LOG_PROPERTY_URLS", "true").lower() in ("true", "1", "yes")

# --- CTR baseline (spec 8.7) -----------------------------------------------
# Conservative position→expected-CTR buckets used only as a *starting point*
# for the high_impression_low_ctr opportunity type. Override via clients.yaml.
# The baseline version is surfaced in tool output so consumers know which
# numbers were used. These are rough industry heuristics, NOT hard truths.
CTR_BASELINE_VERSION: str = "v1-heuristic-2026"
CTR_BASELINE: dict[int, float] = {
    1: 0.30,
    2: 0.15,
    3: 0.10,
    4: 0.07,
    5: 0.05,
    6: 0.04,
    7: 0.03,
    8: 0.025,
    9: 0.02,
    10: 0.015,
}


def expected_ctr_for_position(position: float, baseline: dict[int, float] | None = None) -> float:
    """Return the baseline CTR for a given position, using the nearest bucket."""
    table = baseline or CTR_BASELINE
    bucket = max(1, min(10, round(position)))
    return table.get(bucket, 0.015)


# --- Logging setup ---------------------------------------------------------
def _redact_filter(record: logging.LogRecord) -> bool:
    """Attachment point for redaction; spec 12 forbids tokens/credentials in logs."""
    return True


def configure_logging() -> None:
    """Configure logging with privacy-preserving defaults (spec 12)."""
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger("gsc_mcp")
    if not root.handlers:
        root.addHandler(handler)
    root.setLevel(LOG_LEVEL)
    root.addFilter(_redact_filter)
    # Suppress noisy googleapiclient discovery cache warnings (some MCP hosts
    # treat any stderr as a fatal error).
    logging.getLogger("googleapiclient.discovery_cache").setLevel(logging.ERROR)


# Valid dimensions/operators for Search Analytics (spec 8.3).
VALID_DIMENSIONS: tuple[str, ...] = (
    "query", "page", "country", "device", "date", "hour", "searchAppearance",
)
VALID_FILTER_OPERATORS: tuple[str, ...] = (
    "contains", "equals", "notContains", "notEquals",
    "includingRegex", "excludingRegex",
)
VALID_SEARCH_TYPES: tuple[str, ...] = ("web", "image", "video", "news", "discover")

# Constant warning emitted in analytics output (spec 8.3).
GSC_TOP_ROWS_WARNING: str = (
    "Google Search Console API may return top rows rather than every possible row."
)

__all__ = [
    "SCOPES", "AUTH_MODE", "OAUTH_CLIENT_SECRETS_FILE", "CREDENTIALS_PATH",
    "CONFIG_DIR_ENV", "TOKEN_FILE", "DEFAULT_DATA_STATE", "DEFAULT_PAGE_SIZE",
    "MAX_PAGE_SIZE", "MAX_ANALYSIS_ROWS", "INSPECTION_CONCURRENCY",
    "REQUEST_TIMEOUT_SECONDS", "TRANSPORT", "GSC_TIMEZONE",
    "DEFAULT_REPORT_LAG_DAYS", "DEFAULT_REPORT_WINDOW_DAYS",
    "CLIENTS_CONFIG", "LOG_LEVEL", "LOG_QUERY_VALUES", "LOG_PROPERTY_URLS",
    "CTR_BASELINE_VERSION", "CTR_BASELINE", "expected_ctr_for_position",
    "configure_logging", "VALID_DIMENSIONS", "VALID_FILTER_OPERATORS",
    "VALID_SEARCH_TYPES", "GSC_TOP_ROWS_WARNING",
]
