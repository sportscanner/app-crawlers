"""Generative UI for the website's Agent mode (OpenUI Lang, https://www.openui.com).

The prompt section is generated from the frontend's component spec
(app-frontend/lib/genui/spec.ts -> scripts/genui-prompt.mjs -> openui_prompt.md),
so the agent is only taught components the page can render. Components take
venue refs ("s1v2") rather than data, and the page fills them from the search
results we stream alongside, so the model can't put invented times, prices or
links on screen.
"""

from functools import lru_cache
from pathlib import Path
from typing import Optional

PROMPT_PATH = Path(__file__).with_name("openui_prompt.md")


@lru_cache(maxsize=1)
def _prompt_text() -> str:
    text = PROMPT_PATH.read_text()
    return text.split("-->", 1)[1].strip() if text.startswith("<!--") else text


def system_extra(sport: Optional[str] = None) -> str:
    """Appended to the agent's system prompt for website requests."""
    lines = [
        "",
        "",
        "## On the website",
        "- The person is using the Sportscanner website. Answer in markdown and follow \"Visual answers\" "
        "below instead of the plain-text answer format above.",
        "- Use only locations supplied by the user in this conversation. Never assume a saved home "
        "postcode, browser location or a location from an earlier assistant assumption. If the user "
        "hasn't given a location and it can't be inferred from their earlier messages, ask one short "
        "follow-up question for an area or postcode before searching. A place name is enough: use "
        "resolve_place to find its postcode.",
    ]
    if sport:
        lines.append(f"- They're looking at {sport} right now. Assume it when they don't name a sport.")
    lines += ["", "## Visual answers", _prompt_text()]
    return "\n".join(lines)
