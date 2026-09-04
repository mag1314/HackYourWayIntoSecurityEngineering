import re
from .lever import Posting

_US_STATES = ("AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND "
              "OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC").split()
_US_STATE_NAMES = ["alabama","alaska","arizona","arkansas","california","colorado","connecticut","delaware","florida",
    "georgia","hawaii","idaho","illinois","indiana","iowa","kansas","kentucky","louisiana","maine","maryland",
    "massachusetts","michigan","minnesota","mississippi","missouri","montana","nebraska","nevada","new hampshire",
    "new jersey","new mexico","new york","north carolina","north dakota","ohio","oklahoma","oregon","pennsylvania",
    "rhode island","south carolina","south dakota","tennessee","texas","utah","vermont","virginia","washington",
    "west virginia","wisconsin","wyoming"]
_STATE_ABBR_RE = re.compile(r"(?:,\s*|\b)(" + "|".join(_US_STATES) + r")\b")


def _word(kw: str, text: str) -> bool:
    """Whole-word / whole-phrase match (so 'iam' no longer hits 'Miami')."""
    return re.search(r"(?<![a-z0-9])" + re.escape(kw.lower()) + r"(?![a-z0-9])", text) is not None


def is_us_location(loc: str) -> bool:
    l = loc.lower()
    if not l.strip():
        return True  # unknown -> don't drop
    if any(t in l for t in ("united states", "usa", "u.s.", "remote", "us-", "us -", "(us)")):
        return True
    if re.search(r"\bus\b", l):
        return True
    if any(_word(s, l) for s in _US_STATE_NAMES):
        return True
    return _STATE_ABBR_RE.search(loc) is not None


def is_cyber_role(p: Posting, cfg: dict) -> tuple[bool, str]:
    """Return (match, reason)."""
    title = p.title.lower()

    for kw in cfg.get("exclude_title_keywords", []):
        if _word(kw, title):
            return False, f"excluded: '{kw}'"

    if cfg.get("us_only", False) and not is_us_location(p.location):
        return False, f"non-US location '{p.location}'"
    locs = [l.lower() for l in cfg.get("location_keywords", []) or []]
    if locs and not any(l in p.location.lower() for l in locs):
        return False, f"location '{p.location}' not in filter"

    for kw in cfg.get("title_keywords", []):
        if _word(kw, title):
            return True, f"title: '{kw}'"

    text = p.full_text.lower()
    hits = [kw for kw in cfg.get("description_keywords", []) if _word(kw, text)]
    if len(hits) >= int(cfg.get("min_description_hits", 3)):
        return True, "description: " + ", ".join(hits[:5])
    return False, "no cyber signal"
