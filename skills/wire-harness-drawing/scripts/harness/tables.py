"""Sheets 2 and up: the BOM, the wire list and one table per connector, flowed onto as many sheets as they need."""
from dataclasses import dataclass

from harness.bom import BomLine, find_numbers
from harness.frame import close_sheet, frame
from harness.routing import Route
from harness.source import HarnessSource, format_length, is_splice, pin_label, pins_of, wire_end
from harness.svg import Column, sheet_height, sheet_width, table


@dataclass
class TableContent:
    title: str
    columns: list[Column]
    rows: list[list]


def bom_table(bom: list[BomLine]) -> TableContent:
    columns = [("FIND", 40, "c"), ("QTY", 55, "c"), ("UNIT", 40, "c"), ("PART NUMBER", 150, "l"),
               ("DESCRIPTION", 260, "l"), ("MFR", 90, "l"), ("REF", 140, "l")]
    rows = [[line.find, line.sheet_quantity(), line.unit, line.part_number, line.description, line.manufacturer,
             ", ".join(line.ref_list())] for line in bom]
    return TableContent("BILL OF MATERIALS", columns, rows)


def wire_list_table(source: HarnessSource, routes: list[Route], bom: list[BomLine]) -> TableContent:
    """One row per wire: its find number, both ends with strip lengths, signal, gauge, colour and cut length."""
    connectors = source["connectors"]
    rows = []
    for wire, route in zip(source["wires"], routes):
        (start, start_pin), (end, end_pin) = wire_end(wire["from"]), wire_end(wire["to"])
        finds = find_numbers(bom, "cable", wire["cable"]) if wire.get("cable") else find_numbers(bom, "wire", wire["id"])
        rows.append([wire["id"], ", ".join(map(str, finds)), start, start_pin,
                     format_length(connectors.get(start, {}).get("strip", "")),
                     wire.get("signal") or pin_label(connectors.get(start, {}), start_pin), end, end_pin,
                     format_length(connectors.get(end, {}).get("strip", "")), wire.get("gauge", ""), wire.get("color", ""),
                     route.cut_length_text(), wire.get("twist") or wire.get("cable") or "", wire.get("note", "")])
    columns = [("WIRE", 50, "c"), ("FIND", 40, "c"), ("FROM", 46, "c"), ("PIN", 34, "c"), ("STRIP", 44, "c"),
               ("SIGNAL", 110, "l"), ("TO", 46, "c"), ("PIN", 34, "c"), ("STRIP", 44, "c"), ("GAUGE", 62, "c"),
               ("COLOR", 50, "c"), ("CUT LEN", 58, "c"), ("TWIST/CBL", 64, "c"), ("NOTE", 120, "l")]
    return TableContent("WIRE LIST (FROM–TO)", columns, rows)


def connector_tables(source: HarnessSource) -> list[TableContent]:
    """For each connector, every cavity: the wire in it and where it goes, or that it is empty."""
    tables = []
    for designator, connector in source["connectors"].items():
        if is_splice(connector):
            continue
        rows = []
        for pin in pins_of(connector):
            wires = [wire for wire in source["wires"]
                     if wire_end(wire["from"]) == (designator, pin) or wire_end(wire["to"]) == (designator, pin)]
            if not wires:
                rows.append([pin, pin_label(connector, pin) or "—", "", "", "", "empty" + (" (seal)" if connector.get("sealed") else "")])
            for wire in wires:
                other_end = wire["to"] if wire_end(wire["from"]) == (designator, pin) else wire["from"]
                rows.append([pin, pin_label(connector, pin) or wire.get("signal", ""), wire["id"], wire.get("color", ""),
                             wire.get("gauge", ""), other_end])
        title = (f"{designator} — {connector.get('label') or ''} {connector.get('type', '')} {connector.get('subtype', '')} "
                 f"{connector.get('pn', '')}").strip()
        if connector.get("view"):
            title += f"  [{connector['view']}]"
        columns = [("PIN", 34, "c"), ("SIGNAL", 110, "l"), ("WIRE", 50, "c"), ("COLOR", 50, "c"), ("GAUGE", 60, "c"),
                   ("TO", 70, "c")]
        tables.append(TableContent(title, columns, rows))
    return tables


table_area = (40, 150, sheet_width - 40, sheet_height - 170)  # left, top, right, bottom
column_gap, table_gap = 25, 22


# Tables fill a column top to bottom, then the next column to the right, then a new sheet.
# A table that does not fit where it starts continues in the next column, titled "(cont.)".
def flow_tables(tables: list[TableContent]) -> list[list[str]]:
    """The tables placed onto sheets: each sheet's list of table SVGs."""
    left, top, right, bottom = table_area
    sheets, current = [], []
    x, y, column_width = left, top, 0

    def next_sheet():
        nonlocal current, x, y, column_width
        if current:
            sheets.append(current)
        current, x, y, column_width = [], left, top, 0

    def next_column(table_width):
        nonlocal x, y, column_width
        x, y, column_width = x + column_width + column_gap, top, 0
        if x + table_width > right:
            next_sheet()

    for content in tables:
        table_width = sum(width for _, width, _ in content.columns)
        placed = 0
        first_piece = True
        while placed < len(content.rows) or (first_piece and not content.rows):
            first_piece = False
            if x + table_width > right:
                next_sheet()
            if bottom - y < 80:
                next_column(table_width)
            svg, height, rows_used = table(x, y, content.columns, content.rows[placed:],
                                           content.title + (" (cont.)" if placed else ""), max_height=bottom - y)
            current.append(svg)
            column_width = max(column_width, table_width)
            y += height + table_gap
            placed += rows_used
            if rows_used == 0 and content.rows[placed:]:
                next_column(table_width)
            if not content.rows:
                break
    if current:
        sheets.append(current)
    return sheets


def table_sheets(source: HarnessSource, bodies: list[list[str]], first_sheet: int, sheet_count: int,
                 check_errors: int) -> list[str]:
    """The SVG documents of the table sheets, framed and numbered from first_sheet."""
    return [close_sheet(frame(source, first_sheet + index, sheet_count, "BOM / WIRE LIST / CONNECTORS", check_errors)[0] + body)
            for index, body in enumerate(bodies)]


def table_sheet_bodies(source: HarnessSource, routes: list[Route], bom: list[BomLine]) -> list[list[str]]:
    """The BOM, wire list and connector tables, flowed onto sheets."""
    return flow_tables([bom_table(bom), wire_list_table(source, routes, bom), *connector_tables(source)])
