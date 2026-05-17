#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape


SPACE_RE = re.compile(r"\s+")

WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
CP_NS = "http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
DC_NS = "http://purl.org/dc/elements/1.1/"
DCTERMS_NS = "http://purl.org/dc/terms/"
DCTERMS_TYPE_NS = "http://purl.org/dc/dcmitype/"
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"

A4_WIDTH_TWIPS = 11906
A4_HEIGHT_TWIPS = 16838
TOP_MARGIN_TWIPS = 1440
BOTTOM_MARGIN_TWIPS = 1440
LEFT_MARGIN_TWIPS = 1587
RIGHT_MARGIN_TWIPS = 1474
LINE_SPACING_TWIPS = 580
FIRST_LINE_INDENT_TWIPS = 480


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="把纯文本章节渲染成规范化 docx")
    parser.add_argument("--input", required=True, help="输入 txt 文件")
    parser.add_argument("--output", required=True, help="输出 docx 文件")
    return parser.parse_args()


def _run_xml(text: str, font_name: str, size_half_points: int) -> str:
    safe = escape(text)
    return (
        "<w:r>"
        "<w:rPr>"
        f'<w:rFonts w:ascii="{font_name}" w:hAnsi="{font_name}" w:eastAsia="{font_name}"/>'
        f'<w:sz w:val="{size_half_points}"/>'
        f'<w:szCs w:val="{size_half_points}"/>'
        "</w:rPr>"
        f"<w:t>{safe}</w:t>"
        "</w:r>"
    )


def _title_paragraph_xml(title: str) -> str:
    return (
        "<w:p>"
        "<w:pPr>"
        '<w:jc w:val="center"/>'
        '<w:spacing w:before="0" w:after="0"/>'
        "</w:pPr>"
        f"{_run_xml(title, '黑体', 32)}"
        "</w:p>"
    )


def _body_paragraph_xml(text: str) -> str:
    return (
        "<w:p>"
        "<w:pPr>"
        f'<w:ind w:firstLine="{FIRST_LINE_INDENT_TWIPS}"/>'
        f'<w:spacing w:before="0" w:after="0" w:line="{LINE_SPACING_TWIPS}" w:lineRule="exact"/>'
        "</w:pPr>"
        f"{_run_xml(text, '宋体', 24)}"
        "</w:p>"
    )


def build_document_xml(title: str, paragraphs: list[str]) -> str:
    body_xml = [_title_paragraph_xml(title)]
    body_xml.extend(_body_paragraph_xml(text) for text in paragraphs)
    body_xml.append(
        "<w:sectPr>"
        f'<w:pgSz w:w="{A4_WIDTH_TWIPS}" w:h="{A4_HEIGHT_TWIPS}"/>'
        f'<w:pgMar w:top="{TOP_MARGIN_TWIPS}" w:right="{RIGHT_MARGIN_TWIPS}" '
        f'w:bottom="{BOTTOM_MARGIN_TWIPS}" w:left="{LEFT_MARGIN_TWIPS}" '
        'w:header="720" w:footer="720" w:gutter="0"/>'
        '<w:docGrid w:linePitch="312"/>'
        "</w:sectPr>"
    )
    joined = "".join(body_xml)
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{WORD_NS}">'
        f"<w:body>{joined}</w:body>"
        "</w:document>"
    )


def build_content_types_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '<Override PartName="/docProps/core.xml" '
        'ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
        '<Override PartName="/docProps/app.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>'
        "</Types>"
    )


def build_root_rels_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<Relationships xmlns="{PKG_REL_NS}">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="word/document.xml"/>'
        '<Relationship Id="rId2" '
        'Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" '
        'Target="docProps/core.xml"/>'
        '<Relationship Id="rId3" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" '
        'Target="docProps/app.xml"/>'
        "</Relationships>"
    )


def build_document_rels_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<Relationships xmlns="{PKG_REL_NS}"></Relationships>'
    )


def build_core_xml(title: str) -> str:
    timestamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    safe_title = escape(title)
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<cp:coreProperties xmlns:cp="{CP_NS}" xmlns:dc="{DC_NS}" '
        f'xmlns:dcterms="{DCTERMS_NS}" xmlns:dcmitype="{DCTERMS_TYPE_NS}" xmlns:xsi="{XSI_NS}">'
        f"<dc:title>{safe_title}</dc:title>"
        "<dc:creator>Codex</dc:creator>"
        "<cp:lastModifiedBy>Codex</cp:lastModifiedBy>"
        f'<dcterms:created xsi:type="dcterms:W3CDTF">{timestamp}</dcterms:created>'
        f'<dcterms:modified xsi:type="dcterms:W3CDTF">{timestamp}</dcterms:modified>'
        "</cp:coreProperties>"
    )


def build_app_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" '
        'xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">'
        "<Application>Codex</Application>"
        "</Properties>"
    )


def build_docx(title: str, paragraphs: list[str], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", build_content_types_xml())
        archive.writestr("_rels/.rels", build_root_rels_xml())
        archive.writestr("docProps/core.xml", build_core_xml(title))
        archive.writestr("docProps/app.xml", build_app_xml())
        archive.writestr("word/document.xml", build_document_xml(title, paragraphs))
        archive.writestr("word/_rels/document.xml.rels", build_document_rels_xml())


def load_text_chapter(input_path: Path) -> tuple[str, list[str]]:
    lines = [line.rstrip() for line in input_path.read_text(encoding="utf-8").splitlines()]
    non_empty = [line for line in lines if line.strip()]
    if not non_empty:
        raise ValueError(f"输入文件为空：{input_path}")

    title = non_empty[0].strip()
    body_lines = lines[lines.index(non_empty[0]) + 1 :]

    paragraphs: list[str] = []
    bucket: list[str] = []
    for line in body_lines:
        stripped = line.strip()
        if not stripped:
            if bucket:
                paragraphs.append("".join(bucket))
                bucket = []
            continue
        bucket.append(stripped)
    if bucket:
        paragraphs.append("".join(bucket))
    return title, paragraphs


def count_body_chars(paragraphs: list[str]) -> int:
    return len(SPACE_RE.sub("", "".join(paragraphs)))


def main() -> int:
    args = parse_args()
    input_path = Path(args.input).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve()

    title, paragraphs = load_text_chapter(input_path)
    build_docx(title, paragraphs, output_path)
    print(f"已生成：{output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
