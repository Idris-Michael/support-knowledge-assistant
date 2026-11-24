"""The document set: PostgreSQL 18 docs (public) plus the support desk's internal notes (restricted).

Each citable unit is a *section*: a docs section with its own anchor, or one configuration parameter
or command option (their `<dt id=…>` entries), so a citation can point at `max_wal_size` itself rather
than at a 40-parameter page. Internal notes are split on `##` headings and redacted before storage.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import time
import unicodedata
from collections.abc import Iterator
from dataclasses import asdict, dataclass, field
from pathlib import Path

import httpx
from bs4 import BeautifulSoup, NavigableString, Tag

from .redact import redact

DOCS_VERSION = "18"
DOCS_BASE = f"https://www.postgresql.org/docs/{DOCS_VERSION}/"
SECTION_CLASSES = {
    "chapter",
    "appendix",
    "sect1",
    "sect2",
    "sect3",
    "sect4",
    "refentry",
    "refsect1",
    "refsect2",
}
NUMBERING = re.compile(r"^(?:[A-Z]?\d+(?:\.\d+)*\.|[A-Z]\.\d+(?:\.\d+)*\.)\s*")
PUBLIC = "public"


@dataclass(frozen=True)
class Section:
    id: str  # "runtime-config-wal#GUC-MAX-WAL-SIZE" or "internal/escalation#out-of-hours"
    url: str
    title: str  # page or note title
    heading: str  # "Write Ahead Log › Checkpoints › max_wal_size (integer)"
    text: str
    acl: list[str] = field(default_factory=lambda: [PUBLIC])
    source: str = f"postgresql-{DOCS_VERSION}-docs"


# ---------------------------------------------------------------- fetching


def read_page_list(path: Path) -> list[str]:
    lines = (ln.strip() for ln in path.read_text(encoding="utf-8").splitlines())
    return [ln for ln in lines if ln and not ln.startswith("#")]


def fetch_pages(pages: list[str], raw_dir: Path, *, delay_s: float = 1.0) -> dict[str, object]:
    """Download each page once (politely, one a second) and record its hash, so a rebuild can tell
    whether postgresql.org has changed the text since the benchmark was run."""
    raw_dir.mkdir(parents=True, exist_ok=True)
    entries: list[dict[str, object]] = []
    with httpx.Client(headers={"user-agent": "support-knowledge-assistant corpus fetch"}, timeout=30) as http:
        for page in pages:
            target = raw_dir / f"{page}.html"
            if not target.exists():
                res = http.get(f"{DOCS_BASE}{page}.html")
                if res.status_code != 200:
                    entries.append({"page": page, "status": res.status_code})
                    continue
                target.write_bytes(res.content)
                time.sleep(delay_s)
            entries.append(
                {
                    "page": page,
                    "status": 200,
                    "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                }
            )
    return {
        "version": DOCS_VERSION,
        "base": DOCS_BASE,
        "fetched": time.strftime("%Y-%m-%d"),
        "pages": entries,
    }


# ---------------------------------------------------------------- parsing


def clean(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    lines = (re.sub(r"[ \t]+", " ", ln).strip() for ln in text.splitlines())
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


BOXES = [
    "note",
    "tip",
    "warning",
    "caution",
    "important",
    "table",
    "example",
    "figure",
    "informaltable",
]
BLOCKS = ["p", "div", "dt", "dd", "li", "pre", "h1", "h2", "h3", "h4", "h5", "tr", "br"]


def heading_tag(div: Tag) -> Tag | None:
    """The section's own heading: the first h1–h5 that belongs to this section and is not the title
    of a note, table or example inside it."""
    for h in div.find_all(["h1", "h2", "h3", "h4", "h5"]):
        if h.find_parent(_is_section) in (div, None) and not h.find_parent(class_=BOXES):
            return h
    return None


def heading_of(div: Tag) -> str:
    title = heading_tag(div)
    if title is None:
        return ""
    return NUMBERING.sub("", " ".join(title.get_text("").split()).rstrip(" #")).strip()


def text_of(tag: Tag) -> str:
    """Text with line breaks only where the HTML has blocks, so inline `<code>` stays in its sentence."""
    work = copy.copy(tag)
    for block in work.find_all(BLOCKS):
        block.append("\n")
    return clean(work.get_text(""))


def _flatten_tables(root: Tag) -> None:
    for tr in root.find_all("tr"):
        cells = [clean(c.get_text(" ", strip=True)) for c in tr.find_all(["td", "th"])]
        tr.replace_with(NavigableString(" | ".join(cells) + "\n"))


def _is_section(tag: Tag) -> bool:
    return tag.name == "div" and bool(tag.get("id")) and bool(SECTION_CLASSES & set(tag.get("class") or []))


def parse_page(page: str, html: str) -> list[Section]:
    soup = BeautifulSoup(html, "lxml")
    content = soup.find(id="docContent")
    if not isinstance(content, Tag):
        return []
    for junk in content.select("div.navheader, div.navfooter, div.toc, a.id_link, a.indexterm"):
        junk.decompose()
    _flatten_tables(content)
    top = next((d for d in content.find_all("div") if _is_section(d)), None)
    if top is None:
        return []
    page_title = heading_of(top)
    return list(_walk(page, page_title, top, []))


def _walk(page: str, page_title: str, div: Tag, path: list[str]) -> Iterator[Section]:
    here = [*path, heading_of(div)]
    own = copy.copy(div)
    for nested in own.find_all(_is_section):
        nested.decompose()
    for dt in own.find_all("dt", id=True):
        dd = dt.find_next_sibling("dd")
        if dd:
            dd.decompose()
        dt.decompose()
    title = heading_tag(own)
    if title:
        title.decompose()
    text = text_of(own)
    anchor = str(div["id"])
    if len(text) >= 40:
        yield _section(page, anchor, page_title, here, text)

    # Parameters and options directly in this section (not in nested ones) become their own units.
    for dt in div.find_all("dt", id=True):
        if dt.find_parent(_is_section) is not div:
            continue
        dd = dt.find_next_sibling("dd")
        term = " ".join(dt.get_text("").split()).rstrip(" #")
        body = text_of(dd) if dd else ""
        yield _section(page, str(dt["id"]), page_title, [*here, term], f"{term}\n{body}")

    for child in div.find_all(_is_section):
        if child.find_parent(_is_section) is div:
            yield from _walk(page, page_title, child, here)


def _section(page: str, anchor: str, title: str, path: list[str], text: str) -> Section:
    return Section(
        id=f"{page}#{anchor}",
        url=f"{DOCS_BASE}{page}.html#{anchor}",
        title=title,
        heading=" › ".join(p for p in path if p),
        text=text,
    )


# ---------------------------------------------------------------- internal notes


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def parse_internal(path: Path) -> list[Section]:
    """An internal note: a `---` header with `title:` and `acl:` (comma separated), then `##` sections.
    Text is redacted here, so personal data in the source never reaches the index."""
    raw = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    match = re.match(r"---\n(.*?)\n---\n(.*)", raw, re.DOTALL)
    if not match:
        raise ValueError(f"{path.name}: missing --- header")
    meta = dict(ln.split(":", 1) for ln in match.group(1).splitlines() if ":" in ln)
    title = meta.get("title", path.stem).strip()
    acl = [a.strip() for a in meta.get("acl", "").split(",") if a.strip()]
    if not acl or PUBLIC in acl:
        raise ValueError(f"{path.name}: internal notes need a non-public acl")
    out: list[Section] = []
    for block in re.split(r"\n(?=## )", match.group(2)):
        if block.startswith("## "):
            heading, _, body = block.partition("\n")
            heading = heading.removeprefix("## ").strip()
        else:
            heading, body = "Overview", block
        text = clean(redact(body).text)
        if len(text) < 40:
            continue
        anchor = _slug(heading)
        out.append(
            Section(
                id=f"internal/{path.stem}#{anchor}",
                url=f"internal://{path.stem}#{anchor}",
                title=title,
                heading=f"{title} › {heading}",
                text=text,
                acl=acl,
                source="internal",
            )
        )
    return out


# ---------------------------------------------------------------- build


def build_sections(pages: list[str], raw_dir: Path, internal_dir: Path) -> list[Section]:
    sections: list[Section] = []
    for page in pages:
        file = raw_dir / f"{page}.html"
        if file.exists():
            sections.extend(parse_page(page, file.read_text(encoding="utf-8")))
    for note in sorted(internal_dir.glob("*.md")):
        sections.extend(parse_internal(note))
    seen: set[str] = set()
    unique = []
    for s in sections:
        if s.id not in seen:
            seen.add(s.id)
            unique.append(s)
    return unique


def write_jsonl(sections: list[Section], path: Path) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for s in sections:
            f.write(json.dumps(asdict(s), ensure_ascii=False) + "\n")


def read_jsonl(path: Path) -> list[Section]:
    with path.open(encoding="utf-8") as f:
        return [Section(**json.loads(line)) for line in f if line.strip()]
