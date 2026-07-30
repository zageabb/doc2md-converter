import csv
import json
from email.message import EmailMessage
from pathlib import Path

from odf import text
from odf.opendocument import OpenDocumentText
from pptx import Presentation

from doc2md_watcher.converters import convert
from doc2md_watcher.revisions import RevisionManager


def test_json_and_yaml_become_readable_markdown(tmp_path: Path) -> None:
    json_source = tmp_path / "inventory.json"
    json_source.write_text(
        json.dumps({"system": "screening", "risk": {"level": "high"}}),
        encoding="utf-8",
    )
    yaml_source = tmp_path / "controls.yaml"
    yaml_source.write_text("owner: governance\ncontrols:\n  - human review\n", encoding="utf-8")

    json_output = tmp_path / "inventory.md"
    yaml_output = tmp_path / "controls.md"
    convert(json_source, json_output)
    convert(yaml_source, yaml_output)

    assert "**system:** screening" in json_output.read_text(encoding="utf-8")
    assert "human review" in yaml_output.read_text(encoding="utf-8")


def test_html_and_email_evidence_become_markdown(tmp_path: Path) -> None:
    html_source = tmp_path / "policy.html"
    html_source.write_text(
        "<html><head><title>AI Policy</title></head>"
        "<body><h1>Approval</h1><p>Human review required.</p></body></html>",
        encoding="utf-8",
    )
    message = EmailMessage()
    message["From"] = "owner@example.com"
    message["To"] = "board@example.com"
    message["Subject"] = "Model approval"
    message.set_content("Approved with monitoring.")
    email_source = tmp_path / "approval.eml"
    email_source.write_bytes(message.as_bytes())

    html_output = tmp_path / "policy.md"
    email_output = tmp_path / "approval.md"
    convert(html_source, html_output)
    convert(email_source, email_output)

    assert "# AI Policy" in html_output.read_text(encoding="utf-8")
    assert "Approved with monitoring." in email_output.read_text(encoding="utf-8")


def test_jsonl_is_flattened_to_csv(tmp_path: Path) -> None:
    source = tmp_path / "evaluations.jsonl"
    source.write_text(
        '{"model":"a","metrics":{"bias":0.1}}\n'
        '{"model":"b","metrics":{"bias":0.2}}\n',
        encoding="utf-8",
    )
    output = tmp_path / "evaluations.csv"
    convert(source, output)

    with output.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0] == {"model": "a", "metrics.bias": "0.1"}


def test_presentation_and_open_document_become_markdown(tmp_path: Path) -> None:
    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[1])
    slide.shapes.title.text = "Risk committee"
    slide.placeholders[1].text = "Approve monitoring plan"
    pptx_source = tmp_path / "committee.pptx"
    presentation.save(pptx_source)

    odt = OpenDocumentText()
    odt.text.addElement(text.H(outlinelevel=1, text="Model card"))
    odt.text.addElement(text.P(text="Known limitation"))
    odt_source = tmp_path / "model-card.odt"
    odt.save(str(odt_source))

    pptx_output = tmp_path / "committee.md"
    odt_output = tmp_path / "model-card.md"
    convert(pptx_source, pptx_output)
    convert(odt_source, odt_output)

    assert "Risk committee" in pptx_output.read_text(encoding="utf-8")
    assert "# Model card" in odt_output.read_text(encoding="utf-8")


def test_manifest_is_created_and_archived_with_revision(tmp_path: Path) -> None:
    source = tmp_path / "inventory.json"
    source.write_text('{"system": "first"}', encoding="utf-8")
    manager = RevisionManager(tmp_path)
    first = manager.process(source)
    first_manifest = first.with_name(first.name + ".manifest.json")

    manifest = json.loads(first_manifest.read_text(encoding="utf-8"))
    assert manifest["revision"] == 1
    assert len(manifest["source"]["sha256"]) == 64
    assert len(manifest["output"]["sha256"]) == 64

    source.write_text('{"system": "second"}', encoding="utf-8")
    second = manager.process(source)
    assert second.name == "inventory_r002.md"
    assert (tmp_path / "98_archive/inventory_r001.md").exists()
    assert (tmp_path / "98_archive/inventory_r001.md.manifest.json").exists()
