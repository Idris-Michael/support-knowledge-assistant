from pathlib import Path

import pytest

from support_knowledge_assistant import corpus

PAGE = """<html><body><div id="docContent">
<div class="navheader">Prev Next</div>
<div class="sect1" id="RUNTIME-CONFIG-WAL">
  <div class="titlepage"><h2 class="title">19.5. Write Ahead Log <a class="id_link" href="#x">#</a></h2></div>
  <div class="toc"><dl><dt>19.5.1. Settings</dt></dl></div>
  <p>This section covers <code>WAL</code> settings for the server as a whole.</p>
  <div class="sect2" id="RUNTIME-CONFIG-WAL-CHECKPOINTS">
    <div class="titlepage"><h3 class="title">19.5.2. Checkpoints</h3></div>
    <p>Checkpoint settings control how often dirty pages are flushed to disk.</p>
    <div class="note"><h3 class="title">Note</h3><p>Notes keep their text in the section.</p></div>
    <div class="variablelist"><dl>
      <dt id="GUC-MAX-WAL-SIZE"><span class="term"><code>max_wal_size</code> (<code>integer</code>)</span></dt>
      <dd><p>Maximum size to let the WAL grow during automatic checkpoints. This is a soft limit.</p></dd>
    </dl></div>
    <table><tr><th>Code</th><th>Name</th></tr><tr><td>40P01</td><td>deadlock_detected</td></tr></table>
  </div>
</div>
<div class="navfooter">Prev Next</div>
</div></body></html>"""


def test_page_becomes_sections_with_anchors_headings_and_parameters() -> None:
    sections = {s.id: s for s in corpus.parse_page("runtime-config-wal", PAGE)}
    assert set(sections) == {
        "runtime-config-wal#RUNTIME-CONFIG-WAL",
        "runtime-config-wal#RUNTIME-CONFIG-WAL-CHECKPOINTS",
        "runtime-config-wal#GUC-MAX-WAL-SIZE",
    }
    top = sections["runtime-config-wal#RUNTIME-CONFIG-WAL"]
    assert top.heading == "Write Ahead Log"
    assert "covers WAL settings" in top.text  # inline <code> stays in its sentence
    assert "Checkpoint settings" not in top.text  # nested sections are not repeated
    assert "Prev" not in top.text and "19.5.1" not in top.text  # navigation and TOC dropped

    ckpt = sections["runtime-config-wal#RUNTIME-CONFIG-WAL-CHECKPOINTS"]
    assert ckpt.heading == "Write Ahead Log › Checkpoints"  # not the Note's title
    assert "Notes keep their text" in ckpt.text
    assert "40P01 | deadlock_detected" in ckpt.text  # table rows survive as rows
    assert "soft limit" not in ckpt.text  # the parameter is its own unit

    guc = sections["runtime-config-wal#GUC-MAX-WAL-SIZE"]
    assert guc.heading == "Write Ahead Log › Checkpoints › max_wal_size (integer)"
    assert guc.url.endswith("/docs/18/runtime-config-wal.html#GUC-MAX-WAL-SIZE")
    assert guc.acl == ["public"]


def test_page_without_content_gives_nothing() -> None:
    assert corpus.parse_page("x", "<html><body><p>no docs here</p></body></html>") == []


def _note(tmp_path: Path, body: str, name: str = "note.md") -> Path:
    p = tmp_path / name
    p.write_bytes(body.encode())
    return p


def test_internal_note_is_split_redacted_and_restricted(tmp_path: Path) -> None:
    note = _note(
        tmp_path,
        "---\r\ntitle: Restores\r\nacl: support, sre\r\n---\r\nPreamble text that is long enough to keep.\r\n"
        "## Contact\r\nWrite to jo@example.com or call 07700 900123 about the restore window.\r\n",
    )
    sections = corpus.parse_internal(note)
    assert [s.id for s in sections] == ["internal/note#overview", "internal/note#contact"]
    contact = sections[1]
    assert contact.acl == ["support", "sre"]
    assert contact.source == "internal"
    assert "jo@example.com" not in contact.text and "[EMAIL]" in contact.text
    assert "[PHONE]" in contact.text
    assert contact.heading == "Restores › Contact"


@pytest.mark.parametrize("acl", ["", "public", "public, support"])
def test_internal_note_must_not_be_public(tmp_path: Path, acl: str) -> None:
    with pytest.raises(ValueError, match="non-public acl"):
        corpus.parse_internal(
            _note(tmp_path, f"---\ntitle: T\nacl: {acl}\n---\n## A\nlong enough body text here.\n")
        )


def test_internal_note_needs_header(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="missing --- header"):
        corpus.parse_internal(_note(tmp_path, "## A\nno header\n"))


def test_build_and_round_trip(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "runtime-config-wal.html").write_text(PAGE, encoding="utf-8")
    internal = tmp_path / "internal"
    internal.mkdir()
    _note(
        internal,
        "---\ntitle: T\nacl: sre\n---\n## A\nSome internal text that is long enough to index.\n",
        "a.md",
    )
    sections = corpus.build_sections(["runtime-config-wal", "runtime-config-wal", "missing"], raw, internal)
    assert len(sections) == 4  # duplicates in the page list do not duplicate sections
    out = tmp_path / "sections.jsonl"
    corpus.write_jsonl(sections, out)
    assert corpus.read_jsonl(out) == sections


def test_page_list_ignores_comments(tmp_path: Path) -> None:
    p = tmp_path / "pages.txt"
    p.write_text("# comment\nruntime\n\n  backup  \n", encoding="utf-8")
    assert corpus.read_page_list(p) == ["runtime", "backup"]
