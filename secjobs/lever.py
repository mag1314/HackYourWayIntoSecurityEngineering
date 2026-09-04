"""Read-only access to Lever's public postings API (no auth, no scraping)."""
import requests
from dataclasses import dataclass, field

API = "https://api.lever.co/v0/postings/{slug}?mode=json"


@dataclass
class Posting:
    id: str
    company: str
    title: str
    location: str
    team: str
    commitment: str
    hosted_url: str
    apply_url: str
    description: str
    lists: list = field(default_factory=list)

    @property
    def full_text(self) -> str:
        parts = [self.description]
        for section in self.lists:
            parts.append(section.get("text", ""))
            # Lever returns list bodies as HTML <li> strings; strip crudely
            body = section.get("content", "")
            parts.append(_strip_html(body))
        return "\n".join(p for p in parts if p)


def _strip_html(s: str) -> str:
    import re
    s = re.sub(r"<li>", "\n- ", s)
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"[ \t]+", " ", s).strip()


def fetch_postings(slug: str, timeout: int = 20) -> list[Posting]:
    r = requests.get(API.format(slug=slug), timeout=timeout,
                     headers={"User-Agent": "secjobs/0.1 (personal job search)"})
    r.raise_for_status()
    out = []
    for p in r.json():
        cats = p.get("categories", {}) or {}
        out.append(Posting(
            id=p["id"],
            company=slug,
            title=p.get("text", ""),
            location=cats.get("location", "") or "",
            team=cats.get("team", "") or "",
            commitment=cats.get("commitment", "") or "",
            hosted_url=p.get("hostedUrl", ""),
            apply_url=p.get("applyUrl", ""),
            description=p.get("descriptionPlain", "") or _strip_html(p.get("description", "")),
            lists=p.get("lists", []) or [],
        ))
    return out
