"""Real Word footnotes for python-docx documents.

python-docx can read footnote references but does not expose a public authoring
API. References are inserted into the document tree while footnotes.xml and its
package relationships are added deterministically after save.
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass, field
from typing import List
from xml.etree import ElementTree as ET

from docx.oxml import OxmlElement
from docx.oxml.ns import qn


W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
FOOTNOTE_REL = f"{R_NS}/footnotes"
FOOTNOTE_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.footnotes+xml"
)


@dataclass
class FootnoteRegistry:
    texts: List[str] = field(default_factory=list)

    def add(self, paragraph, text: str) -> int:
        footnote_id = len(self.texts) + 1
        self.texts.append((text or "").strip())
        run = OxmlElement("w:r")
        rpr = OxmlElement("w:rPr")
        style = OxmlElement("w:rStyle")
        style.set(qn("w:val"), "FootnoteReference")
        rpr.append(style)
        run.append(rpr)
        ref = OxmlElement("w:footnoteReference")
        ref.set(qn("w:id"), str(footnote_id))
        run.append(ref)
        paragraph._p.append(run)
        return footnote_id


def _footnotes_xml(texts: List[str]) -> bytes:
    ET.register_namespace("w", W_NS)
    root = ET.Element(f"{{{W_NS}}}footnotes")

    for special_id, tag in ((-1, "separator"), (0, "continuationSeparator")):
        fn = ET.SubElement(root, f"{{{W_NS}}}footnote", {f"{{{W_NS}}}id": str(special_id)})
        p = ET.SubElement(fn, f"{{{W_NS}}}p")
        r = ET.SubElement(p, f"{{{W_NS}}}r")
        ET.SubElement(r, f"{{{W_NS}}}{tag}")

    for index, value in enumerate(texts, 1):
        fn = ET.SubElement(root, f"{{{W_NS}}}footnote", {f"{{{W_NS}}}id": str(index)})
        p = ET.SubElement(fn, f"{{{W_NS}}}p")
        ppr = ET.SubElement(p, f"{{{W_NS}}}pPr")
        ET.SubElement(ppr, f"{{{W_NS}}}pStyle", {f"{{{W_NS}}}val": "FootnoteText"})
        rr = ET.SubElement(p, f"{{{W_NS}}}r")
        rrpr = ET.SubElement(rr, f"{{{W_NS}}}rPr")
        ET.SubElement(rrpr, f"{{{W_NS}}}rStyle", {f"{{{W_NS}}}val": "FootnoteReference"})
        ET.SubElement(rr, f"{{{W_NS}}}footnoteRef")
        text_run = ET.SubElement(p, f"{{{W_NS}}}r")
        node = ET.SubElement(text_run, f"{{{W_NS}}}t", {
            "{http://www.w3.org/XML/1998/namespace}space": "preserve"
        })
        node.text = " " + value
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _patch_relationships(raw: bytes) -> bytes:
    ET.register_namespace("", PKG_REL_NS)
    root = ET.fromstring(raw)
    for rel in root:
        if rel.attrib.get("Type") == FOOTNOTE_REL:
            return raw
    used = []
    for rel in root:
        rid = rel.attrib.get("Id", "")
        if rid.startswith("rId") and rid[3:].isdigit():
            used.append(int(rid[3:]))
    ET.SubElement(root, f"{{{PKG_REL_NS}}}Relationship", {
        "Id": f"rId{max(used, default=0) + 1}",
        "Type": FOOTNOTE_REL,
        "Target": "footnotes.xml",
    })
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _patch_content_types(raw: bytes) -> bytes:
    ET.register_namespace("", CT_NS)
    root = ET.fromstring(raw)
    if not any(node.attrib.get("PartName") == "/word/footnotes.xml" for node in root):
        ET.SubElement(root, f"{{{CT_NS}}}Override", {
            "PartName": "/word/footnotes.xml",
            "ContentType": FOOTNOTE_CONTENT_TYPE,
        })
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _patch_styles(raw: bytes) -> bytes:
    """Add the built-in footnote styles omitted by python-docx's template."""
    ET.register_namespace("w", W_NS)
    root = ET.fromstring(raw)
    existing = {node.attrib.get(f"{{{W_NS}}}styleId")
                for node in root.findall(f"{{{W_NS}}}style")}
    if "FootnoteText" not in existing:
        style = ET.SubElement(root, f"{{{W_NS}}}style", {
            f"{{{W_NS}}}type": "paragraph", f"{{{W_NS}}}styleId": "FootnoteText",
        })
        ET.SubElement(style, f"{{{W_NS}}}name", {f"{{{W_NS}}}val": "footnote text"})
        ET.SubElement(style, f"{{{W_NS}}}basedOn", {f"{{{W_NS}}}val": "Normal"})
        ET.SubElement(style, f"{{{W_NS}}}uiPriority", {f"{{{W_NS}}}val": "99"})
        ppr = ET.SubElement(style, f"{{{W_NS}}}pPr")
        ET.SubElement(ppr, f"{{{W_NS}}}spacing", {
            f"{{{W_NS}}}after": "0", f"{{{W_NS}}}line": "240",
            f"{{{W_NS}}}lineRule": "auto",
        })
        rpr = ET.SubElement(style, f"{{{W_NS}}}rPr")
        ET.SubElement(rpr, f"{{{W_NS}}}sz", {f"{{{W_NS}}}val": "20"})
        ET.SubElement(rpr, f"{{{W_NS}}}szCs", {f"{{{W_NS}}}val": "20"})
    if "FootnoteReference" not in existing:
        style = ET.SubElement(root, f"{{{W_NS}}}style", {
            f"{{{W_NS}}}type": "character", f"{{{W_NS}}}styleId": "FootnoteReference",
        })
        ET.SubElement(style, f"{{{W_NS}}}name", {f"{{{W_NS}}}val": "footnote reference"})
        ET.SubElement(style, f"{{{W_NS}}}semiHidden")
        ET.SubElement(style, f"{{{W_NS}}}unhideWhenUsed")
        rpr = ET.SubElement(style, f"{{{W_NS}}}rPr")
        ET.SubElement(rpr, f"{{{W_NS}}}vertAlign", {f"{{{W_NS}}}val": "superscript"})
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def attach_footnote_part(docx_bytes: bytes, texts: List[str]) -> bytes:
    if not texts:
        return docx_bytes
    source = io.BytesIO(docx_bytes)
    output = io.BytesIO()
    with zipfile.ZipFile(source, "r") as zin, zipfile.ZipFile(
        output, "w", compression=zipfile.ZIP_DEFLATED
    ) as zout:
        for item in zin.infolist():
            if item.filename == "word/footnotes.xml":
                continue
            data = zin.read(item.filename)
            if item.filename == "word/_rels/document.xml.rels":
                data = _patch_relationships(data)
            elif item.filename == "[Content_Types].xml":
                data = _patch_content_types(data)
            elif item.filename == "word/styles.xml":
                data = _patch_styles(data)
            zout.writestr(item, data)
        zout.writestr("word/footnotes.xml", _footnotes_xml(texts))
    return output.getvalue()


__all__ = ["FootnoteRegistry", "attach_footnote_part"]
