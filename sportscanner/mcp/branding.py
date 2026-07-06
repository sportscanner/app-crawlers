"""
Re-skins FastMCP's OAuth consent/error pages to match the Sportscanner brand.

FastMCP doesn't expose a theming hook for these pages: colors and fonts are
hardcoded CSS constants in `fastmcp.utilities.ui`, used by
`fastmcp.server.auth.oauth_proxy.ui.create_consent_html`/`create_error_html`
(the "Application Access Request" screen shown during the OAuth flow). The
only officially parameterised things are the logo (`FastMCP(icons=...)`) and
server name/link (`FastMCP(name=..., website_url=...)`), set where `mcp` is
constructed in `sportscanner/mcp/server.py`.

This module patches `create_page` (imported into that module's namespace) to
append our own CSS after the library's — later rules win the cascade at equal
selector specificity, so this only needs to override colors/fonts, not
reimplement the page. `*args, **kwargs` avoids depending on the function's
exact positional signature.

The Inter font itself is embedded as base64 `data:` URIs (files in
`sportscanner/mcp/assets/`) rather than linked from Google Fonts, so it
renders with no external request and no CSP relaxation beyond adding
`font-src data:` (see `CONSENT_CSP_POLICY`, wired into `OIDCProxy(
consent_csp_policy=...)` in `server.py`) — the default policy's
`default-src 'none'` blocks `font-src` entirely otherwise, which is why the
font silently failed to load even though `font-family: 'Inter'` was already
declared.

Fragility: this reaches into an undocumented, internal fastmcp module path.
If a future fastmcp version renames it, `apply()` logs a warning and no-ops —
the consent page just falls back to default FastMCP styling rather than the
API failing to start. Re-check this file after bumping the `fastmcp` version.
"""

import base64
from pathlib import Path

from sportscanner.logger import logging

_ASSETS_DIR = Path(__file__).parent / "assets"

# The default CSP (`default-src 'none'`) blocks font-src entirely, so even a
# base64 data: URI font won't load without this. Kept as narrow as possible -
# only adds font-src, doesn't loosen anything else (no external hosts allowed).
CONSENT_CSP_POLICY = (
    "default-src 'none'; style-src 'unsafe-inline'; img-src https: data:; "
    "font-src data:; base-uri 'none'"
)


def _font_face_css() -> str:
    try:
        regular = base64.b64encode((_ASSETS_DIR / "Inter-Regular.woff2").read_bytes()).decode()
        semibold = base64.b64encode((_ASSETS_DIR / "Inter-SemiBold.woff2").read_bytes()).decode()
    except Exception as exc:  # pragma: no cover - defensive
        logging.warning(f"MCP consent page: Inter font assets missing, falling back to system font ({exc})")
        return ""
    return f"""
    @font-face {{
        font-family: 'Inter';
        font-style: normal;
        font-weight: 400;
        font-display: swap;
        src: url(data:font/woff2;base64,{regular}) format('woff2');
    }}
    @font-face {{
        font-family: 'Inter';
        font-style: normal;
        font-weight: 600;
        font-display: swap;
        src: url(data:font/woff2;base64,{semibold}) format('woff2');
    }}
"""


_BRAND_CSS = _font_face_css() + """
    body {
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
        background: #F7F9FC;
        color: #0B1220;
    }
    .container {
        border: 1px solid #D7E5DD;
        box-shadow: 0 12px 28px rgba(11, 18, 32, 0.06);
    }
    h1 {
        font-weight: 600;
        color: #0B1220;
    }
    .info-box {
        background: #EFF6FF;
        border-color: #D9E7FF;
        color: #0B1220;
    }
    a, .server-name-link {
        color: #2563EB;
    }
    .redirect-section {
        background: #FFFBEB;
        border-color: #FDE68A;
    }
    .redirect-section .label {
        color: #5B6675;
    }
    .redirect-section .value {
        color: #0B1220;
    }
    details summary {
        color: #5B6675;
    }
    .detail-box {
        background: #F7F9FC;
        border-color: #D7E5DD;
    }
    .btn-approve {
        background: #2563EB;
    }
    .btn-approve:hover {
        background: #1D4ED8;
    }
    .btn-deny {
        background: #5B6675;
    }
    .tooltip-link {
        color: #2563EB;
    }
"""


def apply() -> None:
    try:
        import fastmcp.server.auth.oauth_proxy.ui as _consent_ui

        original_create_page = _consent_ui.create_page

        def _branded_create_page(*args, **kwargs):
            if "additional_styles" in kwargs:
                kwargs["additional_styles"] = (kwargs["additional_styles"] or "") + _BRAND_CSS
            elif len(args) >= 3:
                args = list(args)
                args[2] = (args[2] or "") + _BRAND_CSS
                args = tuple(args)
            else:
                kwargs["additional_styles"] = _BRAND_CSS
            return original_create_page(*args, **kwargs)

        _consent_ui.create_page = _branded_create_page
    except Exception as exc:  # pragma: no cover - defensive
        logging.warning(f"MCP consent page branding not applied (fastmcp internals changed?): {exc}")
