"""`brand_chrome.py` — single source of truth for the brand stylesheet.

WHY THIS MODULE EXISTS:
The brand CSS used to live in `main.py`. Streamlit re-runs the current
page's script top-to-bottom on every navigation, so the stylesheet only
injected on `main.py` — every other page rendered without it (the user
saw "dark mode only works on the main page").

This module exposes ONE function, `apply_chrome()`, that injects the
brand stylesheet (LIGHT palette only — light mode is now permanent;
the dark-mode toggle was dropped per user request) into the running
Streamlit page.

Every page (`pages/1_Home.py`...`pages/13_What_If.py`) calls
`apply_chrome()` near the top so the CSS palette is applied across
all pages — not just on main.py. `main.py` also calls it for the
same reason.

⚠️  Test-ID-based selectors (e.g. `[data-testid="stSidebar"]`) are
Streamlit-version-fragile. If a rule breaks after a Streamlit
upgrade, open browser DevTools, find the new `data-testid` values,
and substitute them in the CSS block below.
"""

from __future__ import annotations

import streamlit as st


# =========================================================
# LIGHT palette — original brand stylesheet (forest-teal +
# system typography + sidebar redesign). Permanent: light
# mode is now hardcoded so the user sees the same surface
# on every page (no theme radio).
#
# `--brand-paper` is the body / page background colour
# (currently set: `#dde6e6` — soft warm-mint tint). Streamlit's
# `backgroundColor` in `.streamlit/config.toml` also pins
# `#f5f8f8`, which paints the Chrome streamlit wrapper while
# `var(--brand-paper)` paints the body inside it; both are
# light, so the visible page reads as one consistent off-cream.
# =========================================================
_LIGHT_CSS_BODY = r"""
/* ============================================================
   LIGHT theme — "Retirement Planner"
   Palette: forest-teal (trust + longevity) + warm amber accent.
   Typography: system stack (no CDN dependency, instant render).
   ============================================================ */
:root {
  --brand-primary:        #2a6f6f;
  --brand-primary-dark:   #1d5252;
  --brand-primary-light:  #e8f1ef;
  --brand-accent:         #a86f2a;
  --brand-ink:            #1a2533;
  --brand-muted:          #6b7785;
  --brand-paper:          #dde6e6;
  --brand-line:           #ececec;
}

/* Typography — system stack, no CDN. */
html, body,
[data-testid="stAppViewContainer"] {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI",
               Roboto, "Helvetica Neue", Arial, sans-serif;
  font-size: 17px;
  line-height: 1.55;
  color: var(--brand-ink);
  background: var(--brand-paper);
}

/* Headings — tight letter-spacing on h1, brand-dark ink. */
h1 {
  color: var(--brand-primary-dark);
  font-weight: 700;
  letter-spacing: -0.02em;
  padding-bottom: 0.25rem;
}
h2 { color: var(--brand-primary-dark); font-weight: 650; }
h3 { color: var(--brand-ink);            font-weight: 600; }

/* Sidebar — subtle gradient + soft border. */
[data-testid="stSidebar"] {
  background: linear-gradient(
    180deg, var(--brand-primary-light) 0%, #ffffff 70%);
  border-right: 1px solid var(--brand-line);
}

/* Sidebar nav links — explicit base colour so non-hovered,
   non-active items read at the expected contrast against the
   sidebar gradient (otherwise Streamlit's native dim-grey
   default overrides the inherited body colour on the inactive
   nav links). Selector list mirrors the hover + active rule
   below: test-id (Streamlit's current convention) AND
   `role="navigation"` (semantic; survives a test-id rename
   because the role attribute is part of the nav's accessibility
   contract). The base rule reserves `padding-left` + a 3px
   transparent border-left so the active rule only swaps
   `border-left-color`, never adjusts layout on page navigation. */
[data-testid="stSidebar"] [data-testid="stSidebarNav"] a,
[data-testid="stSidebar"] [role="navigation"] a {
  color: var(--brand-ink);
  border-radius: 6px;
  padding-left: 0.6rem;
  border-left: 3px solid transparent;
  transition:
    background 0.15s ease,
    border-left-color 0.15s ease;
}
[data-testid="stSidebar"] [data-testid="stSidebarNav"] a:hover,
[data-testid="stSidebar"] [role="navigation"] a:hover {
  background: var(--brand-primary-light);
}
[data-testid="stSidebar"] [data-testid="stSidebarNav"] a[aria-current="page"],
[data-testid="stSidebar"] [role="navigation"] a[aria-current="page"] {
  background: var(--brand-primary-light);
  color: var(--brand-primary-dark);
  font-weight: 600;
  border-left-color: var(--brand-primary);
}

/* Primary buttons — brand-teal CTA. `color: #ffffff` (white-on-
   teal) lands at 5.0:1 contrast on --brand-primary #2a6f6f —
   WCAG AA passes. */
.stButton > button {
  background: var(--brand-primary);
  color: #ffffff;
  border: 1px solid var(--brand-primary-dark);
  border-radius: 8px;
  font-weight: 600;
  padding: 0.45rem 0.95rem;
  transition: background 0.15s ease;
}
.stButton > button:hover {
  background: var(--brand-primary-dark);
}

/* Metric cards — value in brand-dark. */
[data-testid="stMetricValue"] {
  color: var(--brand-primary-dark);
  font-weight: 700;
}

/* Captions — muted + 13px for subtle secondary text. Selector
   list covers the test-id (Streamlit 1.30+) AND a class-
   substring fallback so caption styling survives a future
   Streamlit rename of the test-id across minor releases. */
[data-testid="stCaptionContainer"],
[class*="stCaption"] {
  color: var(--brand-muted);
  font-size: 13px;
}

/* Expander stays white (NOT --brand-paper) so the card lifts
   off the page tint — if it reverts to --brand-paper, the
   hairline border alone is too soft a differentiator. */
[data-testid="stExpander"] {
  background: #ffffff;
  border: 1px solid var(--brand-line);
  border-radius: 10px;
}
"""


def apply_chrome() -> None:
    """Inject the brand stylesheet (LIGHT palette only) into the running page.

    Light mode is now permanent — there is no theme radio, no
    `st.session_state.theme` branch, and no dark palette in this
    module. Every page calls `apply_chrome()` near the TOP after
    `import streamlit as st` (and any `st.set_page_config` the
    page issues) so the stylesheet is in place before the first
    widget paint.

    Idempotent w.r.t. multiple calls in a single script run —
    Streamlit's DOM diff collapses repeated `<style>` blocks of
    identical content, so a `main.py` + `pages/N.py` share via
    multi-page navigation handles any duplicate injection without
    visual artefacts.
    """
    st.markdown(
        f"<style>{_LIGHT_CSS_BODY}</style>",
        unsafe_allow_html=True,
    )
