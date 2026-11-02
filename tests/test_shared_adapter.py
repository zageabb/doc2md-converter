from pathlib import Path
import sys
import types
import pytest
from doc2md_watcher import converters
from doc2md_watcher.shared_adapter import try_shared_conversion


def test_legacy_is_default(tmp_path, monkeypatch):
    monkeypatch.delenv("DOC2MD_USE_SHARED_CONVERSION", raising=False)
    source = tmp_path / "input.md"
    source.write_text("# Heading\n", encoding="utf-8")
    dest = tmp_path / "out.docx"
    converters.convert(source, dest)
    assert dest.exists()


def test_unsupported_pair_stays_legacy(tmp_path, monkeypatch):
    monkeypatch.setenv("DOC2MD_USE_SHARED_CONVERSION", "1")
    source = tmp_path / "data.json"
    source.write_text('{"name":"Example"}', encoding="utf-8")
    dest = tmp_path / "out.md"
    converters.convert(source, dest)
    assert "Example" in dest.read_text()


def test_enabled_adapter_invokes_shared_once(tmp_path, monkeypatch):
    monkeypatch.setenv("DOC2MD_USE_SHARED_CONVERSION", "true")
    calls = []
    fake = types.ModuleType("shared_document_conversion")
    def convert(source, destination, *, overwrite=False):
        calls.append((source, destination, overwrite))
        destination.write_text("shared output")
    fake.convert = convert
    monkeypatch.setitem(sys.modules, "shared_document_conversion", fake)
    src = tmp_path / "a.md"
    src.write_text("test")
    out = tmp_path / "a.docx"
    if sys.version_info < (3, 11):
        with pytest.raises(RuntimeError, match="Python 3.11"):
            try_shared_conversion(src, out)
    else:
        converters.convert(src, out)
        assert len(calls) == 1
        assert calls[0][0] == src
        assert calls[0][2] is False
        assert calls[0][1] != out
        assert calls[0][1].suffix == out.suffix
        assert out.read_text() == "shared output"


def test_shared_failure_does_not_fall_back(tmp_path, monkeypatch):
    monkeypatch.setenv("DOC2MD_USE_SHARED_CONVERSION", "yes")
    fake = types.ModuleType("shared_document_conversion")
    def convert(*args, **kwargs):
        raise ValueError("shared conversion failed")
    fake.convert = convert
    monkeypatch.setitem(sys.modules, "shared_document_conversion", fake)
    source = tmp_path / "input.md"
    source.write_text("content")
    dest = tmp_path / "out.docx"
    if sys.version_info >= (3, 11):
        with pytest.raises(ValueError, match="shared conversion failed"):
            converters.convert(source, dest)
        assert not dest.exists()


def test_real_watcher_staging_with_shared_adapter(tmp_path, monkeypatch):
    from doc2md_watcher.revisions import RevisionManager
    monkeypatch.setenv("DOC2MD_USE_SHARED_CONVERSION", "1")
    fake = types.ModuleType("shared_document_conversion")

    def convert(source, destination, *, overwrite=False):
        assert not destination.exists()
        assert overwrite is False
        destination.write_text("from shared library", encoding="utf-8")

    fake.convert = convert
    monkeypatch.setitem(sys.modules, "shared_document_conversion", fake)
    input_path = tmp_path / "sample.docx"
    from docx import Document
    doc = Document()
    doc.add_paragraph("hello")
    doc.save(input_path)
    if sys.version_info >= (3, 11):
        output = RevisionManager(tmp_path).process(input_path)
        assert output.read_text(encoding="utf-8") == "from shared library"
        assert not list(tmp_path.glob(".doc2md-shared-*"))
