from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from zipfile import ZipFile
import xml.etree.ElementTree as ET


NS = {
    "a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}
REL_NS = {"pr": "http://schemas.openxmlformats.org/package/2006/relationships"}


@dataclass(frozen=True)
class SheetRows:
    name: str
    rows: list[list[str]]


def _col_index(cell_ref: str) -> int:
    letters = "".join(ch for ch in cell_ref if ch.isalpha())
    number = 0
    for ch in letters:
        number = number * 26 + ord(ch.upper()) - 64
    return max(number, 1)


def read_xlsx(path: str | Path) -> list[SheetRows]:
    workbook_path = Path(path)
    if not workbook_path.exists():
        raise FileNotFoundError(f"xlsx file not found: {workbook_path}")

    with ZipFile(workbook_path) as archive:
        shared_strings = _read_shared_strings(archive)
        sheets = _read_sheet_targets(archive)
        result: list[SheetRows] = []
        for sheet_name, target in sheets:
            result.append(SheetRows(sheet_name, _read_sheet_rows(archive, target, shared_strings)))
        return result


def _read_shared_strings(archive: ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    values: list[str] = []
    for item in root.findall("a:si", NS):
        texts = [node.text or "" for node in item.findall(".//a:t", NS)]
        values.append("".join(texts))
    return values


def _read_sheet_targets(archive: ZipFile) -> list[tuple[str, str]]:
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    rid_to_target = {
        rel.attrib["Id"]: rel.attrib["Target"]
        for rel in rels.findall("pr:Relationship", REL_NS)
    }
    sheets: list[tuple[str, str]] = []
    sheets_node = workbook.find("a:sheets", NS)
    if sheets_node is None:
        return sheets
    for sheet in sheets_node.findall("a:sheet", NS):
        rid = sheet.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
        if not rid or rid not in rid_to_target:
            continue
        target = rid_to_target[rid].lstrip("/")
        if not target.startswith("xl/"):
            target = f"xl/{target}"
        sheets.append((sheet.attrib["name"], target))
    return sheets


def _read_sheet_rows(archive: ZipFile, target: str, shared_strings: list[str]) -> list[list[str]]:
    root = ET.fromstring(archive.read(target))
    sheet_data = root.find("a:sheetData", NS)
    if sheet_data is None:
        return []

    rows: list[list[str]] = []
    for row in sheet_data.findall("a:row", NS):
        values: list[str] = []
        for cell in row.findall("a:c", NS):
            cell_ref = cell.attrib.get("r", "")
            index = _col_index(cell_ref)
            while len(values) < index - 1:
                values.append("")
            values.append(_read_cell_value(cell, shared_strings))
        rows.append(values)
    return rows


def _read_cell_value(cell: ET.Element, shared_strings: list[str]) -> str:
    cell_type = cell.attrib.get("t")
    value_node = cell.find("a:v", NS)
    if cell_type == "s" and value_node is not None and value_node.text is not None:
        index = int(value_node.text)
        return shared_strings[index] if index < len(shared_strings) else value_node.text
    if cell_type == "inlineStr":
        return "".join(node.text or "" for node in cell.findall(".//a:t", NS))
    if value_node is not None and value_node.text is not None:
        return value_node.text
    return ""
