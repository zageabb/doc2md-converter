from pathlib import Path

from docx import Document

from doc2md_watcher.folder_links import FolderLinks, parse_linked_folder
from doc2md_watcher.revisions import RevisionManager


def _write_docx(path: Path, value: str) -> None:
    document = Document()
    document.add_paragraph(value)
    document.save(path)


def test_numbered_docx_and_md_folders_are_linked(tmp_path: Path) -> None:
    docx_folder = tmp_path / "02_Business_Context_DOCX"
    md_folder = tmp_path / "03_Business_Context_MD"
    nested = docx_folder / "policies"
    nested.mkdir(parents=True)
    md_folder.mkdir()
    source = nested / "approval.docx"
    _write_docx(source, "approved")

    links = FolderLinks(tmp_path)
    assert len(links.pairs) == 1
    assert links.pairs[0].key == "business_context"
    assert links.destination_for(source) == md_folder / "policies"


def test_linked_revisions_archive_under_destination_path(tmp_path: Path) -> None:
    docx_folder = tmp_path / "02_Business_Context_DOCX"
    md_folder = tmp_path / "03_Business_Context_MD"
    docx_folder.mkdir()
    md_folder.mkdir()
    source = docx_folder / "policy.docx"
    links = FolderLinks(tmp_path)
    manager = RevisionManager(tmp_path)

    _write_docx(source, "first")
    first = manager.process(source, links.destination_for(source))
    assert first == md_folder / "policy_r001.md"

    _write_docx(source, "second")
    second = manager.process(source, links.destination_for(source))
    assert second == md_folder / "policy_r002.md"
    assert (tmp_path / "98_archive/03_Business_Context_MD/policy_r001.md").exists()
    assert (
        tmp_path
        / "98_archive/03_Business_Context_MD/policy_r001.md.manifest.json"
    ).exists()


def test_ambiguous_folders_do_not_route(tmp_path: Path) -> None:
    (tmp_path / "01_Policies_DOCX").mkdir()
    (tmp_path / "02_Policies_DOCX").mkdir()
    (tmp_path / "03_Policies_MD").mkdir()
    source = tmp_path / "01_Policies_DOCX/policy.docx"
    _write_docx(source, "text")

    assert FolderLinks(tmp_path).destination_for(source) is None
    assert parse_linked_folder("General") is None
