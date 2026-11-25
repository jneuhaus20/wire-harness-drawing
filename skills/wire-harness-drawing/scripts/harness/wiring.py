"""The wiring diagram: a WireViz source built from the harness, WireViz's render of it, and the sheet that frames it."""
import base64
import re
import shutil
import subprocess
from collections import OrderedDict
from pathlib import Path

import yaml

from harness.frame import close_sheet, frame
from harness.routing import Route
from harness.source import chosen_color, HarnessSource, color_parts, conventions, is_splice, pin_label, pins_of, wire_end
from harness.svg import sheet_height, sheet_width


def twist_name(wire_count: int) -> str:
    return {2: "Twisted pair", 3: "Twisted triple", 4: "Twisted quad"}.get(wire_count, f"Twisted group of {wire_count}")


# Colours, gauge and length shared by the wires of one WireViz cable or bundle. The length is
# the longest wire's, in the unit wire is bought in; WireViz assumes metres unless told.
def wireviz_conductors(drawing: dict, wires: list[dict], routes: list[Route]) -> dict:
    """The conductor attributes WireViz draws for a group of wires."""
    attributes = {"wirelabels": [wire["id"] for wire in wires]}
    if all(chosen_color(wire) for wire in wires):
        attributes["colors"] = ["".join(color_parts(chosen_color(wire))) for wire in wires]
    else:  # colours not chosen yet: count only, no stand-in colour
        attributes["wirecount"] = len(wires)
    gauges = {str(wire.get("gauge", "")) for wire in wires}
    gauge = gauges.pop() if len(gauges) == 1 else ""
    if gauge and re.match(r"\s*\d+(\.\d+)?(\s+\S+)?\s*$", gauge):  # a number, or number and unit; TBD stays out
        attributes["gauge"] = gauge
    lengths = [route.cut_length for route in routes if route.cut_length]
    if lengths:
        units = conventions(drawing)
        attributes["length"] = round(max(lengths) / units["lengths_per_purchase_unit"], 3)
        if units["purchase_unit"] != "m":
            attributes["length_unit"] = units["purchase_unit"]
    return attributes


def wireviz_bundle(drawing: dict, wires: list[dict], routes: list[Route]) -> dict:
    """A loose bundle of wires in WireViz."""
    return {"category": "bundle", "show_name": False, **wireviz_conductors(drawing, wires, routes)}


# A harness cable keeps its own identity in the diagram: its part number, its description and
# its shield, with every conductor it has, assigned or not.
def wireviz_cable(drawing: dict, cable: dict, wires: list[dict], routes: list[Route]) -> dict:
    """A multi-conductor cable in WireViz."""
    attributes = wireviz_conductors(drawing, wires, routes)
    attributes["wirecount"] = len(wires)
    attributes.update({key: cable[key] for key in ("pn", "manufacturer", "mpn") if key in cable})
    if cable.get("desc"):
        attributes["type"] = cable["desc"]
    if cable.get("shield"):
        attributes["shield"] = cable["shield"]
    return attributes


def wireviz_pin(pin: str) -> int | str:
    """A pin as WireViz expects it: a number when it is one."""
    return int(pin) if str(pin).isdigit() else pin


def wireviz_connector(connector: dict) -> dict:
    """A connector in WireViz: a pin table, or a simple box for a splice."""
    if is_splice(connector):
        return {"style": "simple", "type": "Splice", "show_name": True}
    attributes = {key: connector[key] for key in ("type", "subtype", "pn", "manufacturer", "mpn", "notes") if key in connector}
    attributes["pins"] = [wireviz_pin(pin) for pin in pins_of(connector)]
    attributes["pinlabels"] = [pin_label(connector, pin) for pin in pins_of(connector)]
    attributes["hide_disconnected_pins"] = bool(connector.get("hide_unused", False))
    attributes["show_pincount"] = False  # the pin table already shows every pin
    return attributes


# One WireViz cable per twist group (named for it), per harness cable (drawn as that cable),
# and per loose bundle of wires that share both ends and a gauge (named for those ends). Each cable connects its
# conductors to their pins, one connection set per pair of connectors; a splice, being a
# simple box in WireViz, takes one conductor per set.
def wireviz_source(source: HarnessSource, routes: list[Route]) -> dict:
    """The WireViz YAML document for the harness."""
    connectors, drawing = source["connectors"], source["drawing"]
    document = {"metadata": {"title": source["drawing"].get("title", "")}, "options": {"fontname": "arial"},
                "connectors": {designator: wireviz_connector(connector) for designator, connector in connectors.items()},
                "cables": {}, "connections": []}
    groups = OrderedDict()
    for wire, route in zip(source["wires"], routes):
        (start, start_pin), (end, end_pin) = wire_end(wire["from"]), wire_end(wire["to"])
        if wire.get("cable"):
            key = ("cable", wire["cable"])
        elif wire.get("twist"):
            key = ("twist", wire["twist"])
        else:
            key = ("bundle", start, end, str(wire.get("gauge", "")))
        groups.setdefault(key, []).append((wire, route, start, wireviz_pin(start_pin), end, wireviz_pin(end_pin)))
    for key, members in groups.items():
        wires, member_routes = [member[0] for member in members], [member[1] for member in members]
        if key[0] == "cable":
            name, cable = key[1], wireviz_cable(drawing, source["cables"].get(key[1], {}), wires, member_routes)
        elif key[0] == "twist":
            name, cable = key[1], wireviz_bundle(drawing, wires, member_routes)
            cable.update(type=twist_name(len(wires)), show_name=True)
        else:
            # A loose bundle is named for the connectors it joins, never a B-number, which the
            # drawing uses for breakouts; a second bundle between the same two adds its gauge.
            _, start, end, gauge = key
            name = f"{start}-{end}" if f"{start}-{end}" not in document["cables"] else f"{start}-{end} {gauge}".strip()
            cable = wireviz_bundle(drawing, wires, member_routes)
        document["cables"][name] = cable
        document["connections"] += cable_connections(connectors, name, members)
    return document


def cable_connections(connectors: dict, cable_name: str, members: list[tuple]) -> list[list]:
    """The WireViz connection sets that join one cable's conductors to their pins."""
    by_connectors = OrderedDict()
    for position, (_, _, start, start_pin, end, end_pin) in enumerate(members, 1):
        by_connectors.setdefault((start, end), []).append((position, start_pin, end_pin))
    connections = []
    for (start, end), conductors in by_connectors.items():
        start_splice = is_splice(connectors.get(start, {}))
        end_splice = is_splice(connectors.get(end, {}))
        if start_splice or end_splice:
            for position, start_pin, end_pin in conductors:
                connections.append([start if start_splice else {start: [start_pin]}, {cable_name: [position]},
                                    end if end_splice else {end: [end_pin]}])
        else:
            connections.append([{start: [start_pin for _, start_pin, _ in conductors]},
                                {cable_name: [position for position, _, _ in conductors]},
                                {end: [end_pin for _, _, end_pin in conductors]}])
    return connections


def wireviz_available() -> bool:
    return bool(shutil.which("wireviz") and shutil.which("dot"))


# Write the WireViz source next to the other outputs and render it. A WireViz failure is
# reported with the end of its output, and the package goes on without the diagram sheet.
def render_wiring_diagram(document: dict, output_directory: Path, base: str) -> tuple[Path | None, str | None]:
    """The rendered diagram's SVG path, or None and the reason there is none."""
    source_path = output_directory / f"{base}.wireviz.yaml"
    with open(source_path, "w") as source_file:
        yaml.safe_dump(document, source_file, sort_keys=False)
    result = subprocess.run(["wireviz", "-f", "sp", "-o", str(output_directory), "-O", f"{base}.wiring", str(source_path)],
                            capture_output=True, text=True)
    svg_path = output_directory / f"{base}.wiring.svg"
    if result.returncode or not svg_path.exists():
        return None, "wireviz failed: " + (result.stderr or result.stdout)[-800:]
    return svg_path, None


# The WireViz render is embedded whole, scaled to fit the sheet's drawing area and centred.
def wiring_sheet(source: HarnessSource, diagram_path: Path, sheet: int, sheet_count: int, check_errors: int) -> str:
    """The wiring-diagram sheet's SVG."""
    elements, _ = frame(source, sheet, sheet_count, "WIRING DIAGRAM", check_errors)
    diagram = diagram_path.read_bytes()
    view_box = re.search(rb'viewBox="([\d. -]+)"', diagram)
    diagram_width, diagram_height = (float(v) for v in view_box.group(1).split()[2:]) if view_box else (1000, 700)
    area_x, area_y, area_width, area_height = 40, 150, sheet_width - 80, sheet_height - 150 - 160
    scale = min(area_width / diagram_width, area_height / diagram_height)
    width, height = diagram_width * scale, diagram_height * scale
    encoded = base64.b64encode(diagram).decode()
    elements.append(f'<image x="{area_x + (area_width - width) / 2:.1f}" y="{area_y + (area_height - height) / 2:.1f}" '
                    f'width="{width:.1f}" height="{height:.1f}" href="data:image/svg+xml;base64,{encoded}"/>')
    return close_sheet(elements)
