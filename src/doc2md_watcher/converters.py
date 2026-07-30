from __future__ import annotations

import csv
import json
from email import policy
from email.parser import BytesParser
from pathlib import Path
from typing import Any

import yaml
from bs4 import BeautifulSoup
from defusedxml import ElementTree as ET
from docx import Document
from odf import table, text
from odf.opendocument import load as load_odf
from openpyxl import Workbook, load_workbook
from pptx import Presentation
from striprtf.striprtf import rtf_to_text


class ConversionError(RuntimeError):
    """Raised when a supported document cannot be converted."""


def docx_to_md(source: Path, destination: Path) -> None:
    document = Document(source)
    lines: list[str] = []
    for paragraph in document.paragraphs:
        text = paragraph.text
        style = (paragraph.style.name if paragraph.style else "").lower()
        if style.startswith("heading"):
            try:
                level = max(1, min(6, int(style.split()[-1])))
            except (ValueError, IndexError):
                level = 1
            lines.append(f"{'#' * level} {text}")
        elif text:
            lines.append(text)
        else:
            lines.append("")

    for table in document.tables:
        rows = [[cell.text.replace("\n", "<br>") for cell in row.cells] for row in table.rows]
        if not rows:
            continue
        width = max(len(row) for row in rows)
        rows = [row + [""] * (width - len(row)) for row in rows]
        lines.append("")
        lines.append("| " + " | ".join(_escape_md(value) for value in rows[0]) + " |")
        lines.append("| " + " | ".join("---" for _ in range(width)) + " |")
        for row in rows[1:]:
            lines.append("| " + " | ".join(_escape_md(value) for value in row) + " |")

    destination.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def md_to_docx(source: Path, destination: Path) -> None:
    document = Document()
    for raw_line in source.read_text(encoding="utf-8-sig").splitlines():
        stripped = raw_line.lstrip()
        hashes = len(stripped) - len(stripped.lstrip("#"))
        if hashes and hashes <= 6 and stripped[hashes : hashes + 1] == " ":
            document.add_heading(stripped[hashes + 1 :], level=hashes)
        elif stripped.startswith(("- ", "* ")):
            document.add_paragraph(stripped[2:], style="List Bullet")
        elif stripped[:3].rstrip(".").isdigit() and ". " in stripped[:4]:
            document.add_paragraph(stripped.split(". ", 1)[1], style="List Number")
        else:
            document.add_paragraph(raw_line)
    document.save(destination)


def xlsx_to_csv(source: Path, destination: Path) -> None:
    workbook = load_workbook(source, read_only=True, data_only=True)
    try:
        sheet = workbook.active
        with destination.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            for row in sheet.iter_rows(values_only=True):
                writer.writerow(["" if value is None else value for value in row])
    finally:
        workbook.close()


def csv_to_xlsx(source: Path, destination: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = source.stem[:31] or "Sheet1"
    with source.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.reader(handle):
            sheet.append(row)
    workbook.save(destination)


def pdf_to_md(source: Path, destination: Path) -> None:
    try:
        import fitz

        pdf = fitz.open(source)
        try:
            pages = []
            for number, page in enumerate(pdf, start=1):
                text = page.get_text("text").strip()
                pages.append(f"## Page {number}\n\n{text}")
        finally:
            pdf.close()
        destination.write_text("\n\n".join(pages).rstrip() + "\n", encoding="utf-8")
    except Exception as exc:
        raise ConversionError(f"could not extract PDF text: {exc}") from exc


def json_to_md(source: Path, destination: Path) -> None:
    data = json.loads(source.read_text(encoding="utf-8-sig"))
    destination.write_text(_structured_to_md(data), encoding="utf-8")


def yaml_to_md(source: Path, destination: Path) -> None:
    data = yaml.safe_load(source.read_text(encoding="utf-8-sig"))
    destination.write_text(_structured_to_md(data), encoding="utf-8")


def xml_to_md(source: Path, destination: Path) -> None:
    root = ET.parse(source).getroot()
    data = {_xml_name(root.tag): _xml_to_value(root)}
    destination.write_text(_structured_to_md(data), encoding="utf-8")


def html_to_md(source: Path, destination: Path) -> None:
    soup = BeautifulSoup(source.read_text(encoding="utf-8-sig"), "html.parser")
    for unwanted in soup(["script", "style", "noscript"]):
        unwanted.decompose()
    lines: list[str] = []
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    if title:
        lines.append(f"# {title}")
    body = soup.body or soup
    for element in body.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "pre"]):
        value = element.get_text(" ", strip=True)
        if not value:
            continue
        if element.name.startswith("h"):
            lines.append(f"{'#' * int(element.name[1])} {value}")
        elif element.name == "li":
            lines.append(f"- {value}")
        elif element.name == "pre":
            lines.append(f"```\n{element.get_text().strip()}\n```")
        else:
            lines.append(value)
    destination.write_text("\n\n".join(lines).rstrip() + "\n", encoding="utf-8")


def plain_text_to_md(source: Path, destination: Path) -> None:
    destination.write_text(source.read_text(encoding="utf-8-sig"), encoding="utf-8")


def rtf_to_md(source: Path, destination: Path) -> None:
    value = rtf_to_text(source.read_text(encoding="utf-8", errors="replace"))
    destination.write_text(value.rstrip() + "\n", encoding="utf-8")


def pptx_to_md(source: Path, destination: Path) -> None:
    presentation = Presentation(source)
    lines: list[str] = []
    for number, slide in enumerate(presentation.slides, start=1):
        title = ""
        if slide.shapes.title:
            title = slide.shapes.title.text.strip()
        lines.append(f"# Slide {number}" + (f": {title}" if title else ""))
        for shape in slide.shapes:
            if shape == slide.shapes.title:
                continue
            if getattr(shape, "has_text_frame", False):
                for paragraph in shape.text_frame.paragraphs:
                    value = paragraph.text.strip()
                    if value:
                        prefix = "  " * paragraph.level + "- "
                        lines.append(prefix + value)
            if getattr(shape, "has_table", False):
                rows = [[cell.text for cell in row.cells] for row in shape.table.rows]
                lines.extend(_markdown_table(rows))
        notes = slide.notes_slide.notes_text_frame.text.strip()
        if notes:
            lines.extend(["", "## Speaker notes", "", notes])
        lines.append("")
    destination.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def odt_to_md(source: Path, destination: Path) -> None:
    document = load_odf(str(source))
    lines: list[str] = []
    for node in _odf_blocks(document.text):
        value = _odf_text(node).strip()
        if not value:
            continue
        if getattr(node, "tagName", "") == "text:h":
            level = int(node.getAttribute("outlinelevel") or 1)
            lines.append(f"{'#' * min(6, max(1, level))} {value}")
        else:
            lines.append(value)
    destination.write_text("\n\n".join(lines).rstrip() + "\n", encoding="utf-8")


def ods_to_csv(source: Path, destination: Path) -> None:
    document = load_odf(str(source))
    sheets = document.spreadsheet.getElementsByType(table.Table)
    if not sheets:
        raise ConversionError("ODS workbook contains no sheets")
    with destination.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        for row in sheets[0].getElementsByType(table.TableRow):
            values: list[str] = []
            for cell in row.getElementsByType(table.TableCell):
                repeated = int(cell.getAttribute("numbercolumnsrepeated") or 1)
                value = _odf_text(cell)
                values.extend([value] * min(repeated, 10_000))
            writer.writerow(values)


def delimited_to_csv(source: Path, destination: Path) -> None:
    with source.open("r", encoding="utf-8-sig", newline="") as input_handle:
        with destination.open("w", encoding="utf-8", newline="") as output_handle:
            writer = csv.writer(output_handle)
            writer.writerows(csv.reader(input_handle, delimiter="\t"))


def jsonl_to_csv(source: Path, destination: Path) -> None:
    records: list[dict[str, Any]] = []
    fields: list[str] = []
    for number, line in enumerate(source.read_text(encoding="utf-8-sig").splitlines(), start=1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            value = {"value": value}
        flat = _flatten(value)
        records.append(flat)
        for key in flat:
            if key not in fields:
                fields.append(key)
    with destination.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(records)


def eml_to_md(source: Path, destination: Path) -> None:
    message = BytesParser(policy=policy.default).parsebytes(source.read_bytes())
    headers = [
        ("From", message.get("From", "")),
        ("To", message.get("To", "")),
        ("Cc", message.get("Cc", "")),
        ("Date", message.get("Date", "")),
        ("Subject", message.get("Subject", "")),
        ("Message-ID", message.get("Message-ID", "")),
    ]
    body = message.get_body(preferencelist=("plain", "html"))
    content = body.get_content() if body else ""
    if body and body.get_content_type() == "text/html":
        content = BeautifulSoup(content, "html.parser").get_text("\n", strip=True)
    attachments = [
        part.get_filename()
        for part in message.iter_attachments()
        if part.get_filename()
    ]
    lines = ["# Email", "", *[f"- **{name}:** {value}" for name, value in headers], "", "## Body", "", content]
    if attachments:
        lines.extend(["", "## Attachments", "", *[f"- {name}" for name in attachments]])
    destination.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def msg_to_md(source: Path, destination: Path) -> None:
    import extract_msg

    message = extract_msg.Message(str(source))
    try:
        headers = [
            ("From", message.sender or ""),
            ("To", message.to or ""),
            ("Cc", message.cc or ""),
            ("Date", str(message.date or "")),
            ("Subject", message.subject or ""),
        ]
        attachments = [
            attachment.longFilename or attachment.shortFilename
            for attachment in message.attachments
            if attachment.longFilename or attachment.shortFilename
        ]
        lines = [
            "# Outlook message",
            "",
            *[f"- **{name}:** {value}" for name, value in headers],
            "",
            "## Body",
            "",
            message.body or "",
        ]
        if attachments:
            lines.extend(["", "## Attachments", "", *[f"- {name}" for name in attachments]])
        destination.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    finally:
        message.close()


def notebook_to_md(source: Path, destination: Path) -> None:
    notebook = json.loads(source.read_text(encoding="utf-8"))
    lines: list[str] = [f"# {source.stem}", ""]
    for cell in notebook.get("cells", []):
        content = "".join(cell.get("source", []))
        if cell.get("cell_type") == "markdown":
            lines.extend([content.rstrip(), ""])
        elif cell.get("cell_type") == "code":
            lines.extend(["```python", content.rstrip(), "```", ""])
            outputs = cell.get("outputs", [])
            rendered = []
            for output in outputs:
                value = output.get("text") or output.get("data", {}).get("text/plain")
                if value:
                    rendered.append("".join(value) if isinstance(value, list) else str(value))
            if rendered:
                lines.extend(["```text", "\n".join(rendered).rstrip(), "```", ""])
    destination.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def convert(source: Path, destination: Path) -> None:
    pair = (source.suffix.lower(), destination.suffix.lower())
    converters = {
        (".docx", ".md"): docx_to_md,
        (".xlsx", ".csv"): xlsx_to_csv,
        (".md", ".docx"): md_to_docx,
        (".csv", ".xlsx"): csv_to_xlsx,
        (".pdf", ".md"): pdf_to_md,
        (".json", ".md"): json_to_md,
        (".yaml", ".md"): yaml_to_md,
        (".yml", ".md"): yaml_to_md,
        (".xml", ".md"): xml_to_md,
        (".html", ".md"): html_to_md,
        (".htm", ".md"): html_to_md,
        (".txt", ".md"): plain_text_to_md,
        (".log", ".md"): plain_text_to_md,
        (".rtf", ".md"): rtf_to_md,
        (".pptx", ".md"): pptx_to_md,
        (".odt", ".md"): odt_to_md,
        (".ods", ".csv"): ods_to_csv,
        (".tsv", ".csv"): delimited_to_csv,
        (".jsonl", ".csv"): jsonl_to_csv,
        (".ndjson", ".csv"): jsonl_to_csv,
        (".eml", ".md"): eml_to_md,
        (".msg", ".md"): msg_to_md,
        (".ipynb", ".md"): notebook_to_md,
    }
    try:
        converter = converters[pair]
    except KeyError as exc:
        raise ConversionError(f"unsupported conversion: {pair[0]} -> {pair[1]}") from exc
    converter(source, destination)


def _escape_md(value: str) -> str:
    return value.replace("|", r"\|")


def _structured_to_md(data: Any) -> str:
    lines = ["# Structured document", ""]

    def render(value: Any, depth: int, label: str | None = None) -> None:
        if isinstance(value, dict):
            if label is not None:
                lines.append(f"{'#' * min(depth + 1, 6)} {label}")
                lines.append("")
            for key, child in value.items():
                render(child, depth + 1, str(key))
        elif isinstance(value, list):
            if label is not None:
                lines.append(f"{'#' * min(depth + 1, 6)} {label}")
                lines.append("")
            for item in value:
                if isinstance(item, (dict, list)):
                    render(item, depth + 1)
                else:
                    lines.append(f"- {_scalar(item)}")
            lines.append("")
        else:
            lines.append(f"- **{label}:** {_scalar(value)}" if label else _scalar(value))
            lines.append("")

    render(data, 1)
    return "\n".join(lines).rstrip() + "\n"


def _scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return str(value).lower()
    return str(value)


def _xml_to_value(element: ET.Element) -> Any:
    children = list(element)
    attributes = {f"@{_xml_name(key)}": value for key, value in element.attrib.items()}
    if not children:
        value = (element.text or "").strip()
        if attributes:
            return {**attributes, "#text": value} if value else attributes
        return value
    result: dict[str, Any] = dict(attributes)
    for child in children:
        name = _xml_name(child.tag)
        value = _xml_to_value(child)
        if name in result:
            if not isinstance(result[name], list):
                result[name] = [result[name]]
            result[name].append(value)
        else:
            result[name] = value
    return result


def _xml_name(value: str) -> str:
    return value.rsplit("}", 1)[-1]


def _markdown_table(rows: list[list[str]]) -> list[str]:
    if not rows:
        return []
    width = max(len(row) for row in rows)
    normalized = [row + [""] * (width - len(row)) for row in rows]
    lines = ["", "| " + " | ".join(_escape_md(value) for value in normalized[0]) + " |"]
    lines.append("| " + " | ".join("---" for _ in range(width)) + " |")
    lines.extend("| " + " | ".join(_escape_md(value) for value in row) + " |" for row in normalized[1:])
    return lines


def _odf_text(node: Any) -> str:
    parts: list[str] = []
    for child in node.childNodes:
        if getattr(child, "data", None) is not None:
            parts.append(child.data)
        else:
            parts.append(_odf_text(child))
    return "".join(parts)


def _odf_blocks(node: Any):
    for child in getattr(node, "childNodes", []):
        if getattr(child, "tagName", "") in {"text:h", "text:p"}:
            yield child
        else:
            yield from _odf_blocks(child)


def _flatten(value: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, child in value.items():
        name = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(child, dict):
            result.update(_flatten(child, name))
        elif isinstance(child, list):
            result[name] = json.dumps(child, ensure_ascii=False)
        else:
            result[name] = child
    return result
