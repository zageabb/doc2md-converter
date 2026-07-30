from pathlib import Path

from docx import Document

from doc2md_watcher.revisions import RevisionManager


def write_docx(path: Path, text: str) -> None:
    document = Document()
    document.add_heading("Title", level=1)
    document.add_paragraph(text)
    document.save(path)


def test_creates_and_archives_revisions(tmp_path: Path) -> None:
    nested = tmp_path / "client" / "reports"
    nested.mkdir(parents=True)
    source = nested / "summary.docx"
    manager = RevisionManager(tmp_path)

    write_docx(source, "first")
    first = manager.process(source)
    assert first == nested / "summary_r001.md"
    assert first.read_text(encoding="utf-8") == "# Title\nfirst\n"

    write_docx(source, "second")
    second = manager.process(source)
    assert second == nested / "summary_r002.md"
    assert not first.exists()
    assert (tmp_path / "98_archive/client/reports/summary_r001.md").exists()


def test_generated_output_does_not_loop(tmp_path: Path) -> None:
    source = tmp_path / "notes.md"
    source.write_text("# Notes\n\nHello\n", encoding="utf-8")
    manager = RevisionManager(tmp_path)
    output = manager.process(source)

    assert output == tmp_path / "notes_r001.docx"
    assert manager.process(output) is None
    assert not (tmp_path / "notes_r001_r001.md").exists()


def test_archive_revision_is_considered_after_restart(tmp_path: Path) -> None:
    source = tmp_path / "data.csv"
    source.write_text("a,b\n1,2\n", encoding="utf-8")
    manager = RevisionManager(tmp_path)
    manager.process(source)
    source.write_text("a,b\n3,4\n", encoding="utf-8")
    manager.process(source)

    restarted = RevisionManager(tmp_path)
    source.write_text("a,b\n5,6\n", encoding="utf-8")
    third = restarted.process(source)
    assert third == tmp_path / "data_r003.xlsx"
