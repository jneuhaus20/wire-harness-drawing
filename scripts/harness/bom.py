"""The bill of materials: one line per part, with its find number, quantity and references."""
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Literal

from harness.routing import HarnessTree, Route
from harness.source import HarnessSource, conventions, format_length, is_splice, pins_of, wire_end
from harness.validation import covered_segment_ends, covered_segment_name

PartKind = Literal["splice", "connector", "contact", "accessory", "cable", "wire", "item"]


# One BOM line. Quantities add up as parts with the same key are found; a length that runs
# through a TBD segment makes the whole line TBD. As-required (AR) lines are lengths.
@dataclass
class BomLine:
    kind: PartKind
    key: tuple
    description: str
    part_number: str
    manufacturer: str
    unit: str
    as_required: bool
    quantity: float = 0
    to_be_decided: bool = False
    refs: list = field(default_factory=list)
    find: int = 0

    def add(self, quantity: float | None, refs: list) -> None:
        """Add a quantity (None for a TBD length) and the references it comes from."""
        if quantity is None:
            self.to_be_decided = True
        else:
            self.quantity += quantity
        self.refs += refs

    def sheet_quantity(self) -> str:
        """The QTY cell on the BOM sheet: AR lines show the computed length in brackets."""
        if self.as_required:
            if self.to_be_decided:
                return "AR (TBD)"
            return f"AR ({self.quantity:.2f})" if self.quantity else "AR"
        return "TBD" if self.to_be_decided else format_length(round(self.quantity, 3))

    def csv_quantity(self) -> str:
        """The qty in bom.csv: a number purchasing can use, or a word when there is none yet."""
        if self.to_be_decided:
            return "TBD"
        if self.as_required and not self.quantity:
            return "AR"
        return format_length(round(self.quantity, 3))

    def ref_list(self) -> list[str]:
        """The references, each once, in the order found."""
        return list(dict.fromkeys(str(ref) for ref in self.refs))


# A connector's BOM text: its own desc, or its type and subtype with the position count added
# when neither already states it and the part has more than one.
def connector_description(connector: dict) -> str:
    """The description of a connector's housing line on the BOM."""
    if connector.get("desc"):
        return connector["desc"]
    words = " ".join(str(x) for x in (connector.get("type", "Connector"), connector.get("subtype", "")) if x)
    positions = len(pins_of(connector))
    states_count = re.search(r"\b\d+\s*-?\s*(pins?|pos|positions?|ways?|p)\b", words, re.I)
    return words if positions == 1 or states_count else f"{words}, {positions} pos"


class BomBuilder:
    """Collects BOM lines by key, keeping the order each part was first found in."""

    def __init__(self) -> None:
        self.lines: dict[tuple, BomLine] = {}

    def add(self, kind: PartKind, key: tuple, *, description: str, part_number: str, manufacturer: str,
            quantity: float | None, unit: str, refs: list, as_required: bool) -> None:
        line = self.lines.setdefault((kind, *key), BomLine(kind, (kind, *key), description, part_number, manufacturer,
                                                            unit, as_required))
        line.add(quantity, refs)

    def numbered(self) -> list[BomLine]:
        """The lines with find numbers 1, 2, ... in the order found."""
        for find, line in enumerate(self.lines.values(), 1):
            line.find = find
        return list(self.lines.values())


# Lines come in a fixed order: each connector with its contacts and accessories (splices
# alone), then cables, loose wires, and the source's other items.
def build_bom(source: HarnessSource, tree: HarnessTree, routes: list[Route]) -> list[BomLine]:
    """The BOM lines, numbered."""
    builder = BomBuilder()
    add_connector_parts(builder, source)
    add_cables_and_wires(builder, source, routes)
    add_items(builder, source, tree)
    return builder.numbered()


# One contact per pin used, so wires double-crimped in one pin share its contact.
def add_connector_parts(builder: BomBuilder, source: HarnessSource) -> None:
    """Add each connector's housing, contacts and accessories, and each splice."""
    pins_used = defaultdict(set)
    for wire in source["wires"]:
        for end in ("from", "to"):
            designator, pin = wire_end(wire[end])
            pins_used[designator].add(pin)
    for designator, connector in source["connectors"].items():
        if is_splice(connector):
            builder.add("splice", (connector.get("pn", "splice"),), description=connector.get("desc", "Splice"),
                        part_number=connector.get("pn", ""), manufacturer=connector.get("mpn_mfr", connector.get("manufacturer", "")),
                        quantity=1, unit="EA", refs=[designator], as_required=False)
            continue
        description = connector_description(connector)
        builder.add("connector", (connector.get("pn") or description,), description=description,
                    part_number=connector.get("pn", ""), manufacturer=connector.get("manufacturer", ""),
                    quantity=1, unit="EA", refs=[designator], as_required=False)
        contact = connector.get("contact")
        if contact:
            builder.add("contact", (contact.get("pn", contact.get("desc")),), description=contact.get("desc", "Contact"),
                        part_number=contact.get("pn", ""), manufacturer=contact.get("manufacturer", ""),
                        quantity=len(pins_used[designator]) + int(contact.get("spare", 0)), unit="EA",
                        refs=[designator], as_required=False)
        for accessory in connector.get("accessories", []):
            builder.add("accessory", (accessory.get("pn", accessory.get("desc")),), description=accessory.get("desc", ""),
                        part_number=accessory.get("pn", ""), manufacturer=accessory.get("manufacturer", ""),
                        quantity=accessory.get("qty", 1), unit="EA", refs=[designator], as_required=False)


def purchased_length(source: HarnessSource, length: float | None) -> float | None:
    """A drawing length in the unit it is bought in; None (TBD) stays None."""
    return None if length is None else length / conventions(source["drawing"])["lengths_per_purchase_unit"]


# A cable is bought at its longest conductor; a loose wire is bought by type, gauge, colour
# and part number together.
def add_cables_and_wires(builder: BomBuilder, source: HarnessSource, routes: list[Route]) -> None:
    """Add each cable and each loose wire as lengths."""
    purchase_unit = conventions(source["drawing"])["purchase_unit"]
    for cable_id, cable in source["cables"].items():
        cable_lengths = [route.cut_length for wire, route in zip(source["wires"], routes) if wire.get("cable") == cable_id]
        longest = None if None in cable_lengths else max(cable_lengths or [0])
        builder.add("cable", (cable.get("pn", cable_id),), description=cable.get("desc", "Cable"),
                    part_number=cable.get("pn", ""), manufacturer=cable.get("manufacturer", ""),
                    quantity=purchased_length(source, longest), unit=purchase_unit, refs=[cable_id], as_required=True)
    for wire, route in zip(source["wires"], routes):
        if wire.get("cable"):
            continue
        gauge, color = str(wire.get("gauge", "")), wire.get("color", "")
        wire_type = wire.get("type", source["drawing"].get("wire_type", "Hook-up wire"))
        part_number = wire.get("pn") or ""
        builder.add("wire", (wire_type, gauge, color, part_number),
                    description=", ".join(x for x in (wire_type, gauge, color) if x), part_number=part_number,
                    manufacturer=wire.get("manufacturer", ""), quantity=purchased_length(source, route.cut_length),
                    unit=purchase_unit, refs=[wire["id"]], as_required=True)


# An AR item that covers segments is bought at their total length; an item with no qty that
# labels use is counted by its labels; anything else is bought as stated.
def add_items(builder: BomBuilder, source: HarnessSource, tree: HarnessTree) -> None:
    """Add the source's other items: coverings, labels and the rest."""
    layout = source["layout"]
    purchase_unit = conventions(source["drawing"])["purchase_unit"]
    for item in source["items"]:
        item_id = item.get("id") or item.get("pn") or item.get("desc", "")
        quantity = item.get("qty")
        as_required = quantity in (None, "AR")
        unit = item.get("unit", "EA")
        refs = list(item.get("refs", []))
        coverings = [covering for covering in layout.get("coverings") or [] if covering.get("item") == item_id]
        labels = [label for label in layout.get("labels") or [] if label.get("item") == item_id]
        if as_required and coverings:
            covered = []
            for covering in coverings:
                for segment in covering["segments"]:
                    covered.append(tree.segment_lengths.get(frozenset(covered_segment_ends(segment))))
                refs += [covered_segment_name(segment) for segment in covering["segments"]]
            quantity, unit = purchased_length(source, None if None in covered else sum(covered)), purchase_unit
        elif quantity is None and labels:
            quantity, as_required = len(labels), False
            refs += [label["at"] for label in labels]
        counted = quantity if isinstance(quantity, (int, float)) or (as_required and coverings) else 0
        builder.add("item", (item_id,), description=item.get("desc", ""), part_number=item.get("pn", ""),
                    manufacturer=item.get("manufacturer", ""), quantity=counted, unit=unit, refs=refs,
                    as_required=as_required)


def find_numbers(bom: list[BomLine], kind: PartKind, ref: str) -> list[int]:
    """The find numbers of the lines of one kind that a designator, wire or cable is on."""
    return [line.find for line in bom if line.kind == kind and ref in line.refs]


def item_find_numbers(bom: list[BomLine], item_id: str) -> list[int]:
    """The find number of a source item's line."""
    return [line.find for line in bom if line.key == ("item", item_id)]
