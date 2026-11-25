"""The checks a harness source must pass, from wire ends to the netlist."""
import re
from collections import defaultdict

from harness.routing import HarnessTree, Route
from harness.source import (Findings, HarnessSource, conventions, format_length, is_generic, is_number, is_splice,
                            pin_label, pins_of, wire_end)

Cavity = tuple[str, str]  # (designator, pin)


# Run every check in the order the report lists them: wires, cavities, connectors, twists,
# cables, the layout, coverings and labels, and last the netlist.
def check_harness(source: HarnessSource, tree: HarnessTree | None, routes: list[Route], findings: Findings) -> None:
    """Report everything wrong with a validated source and its routes."""
    check_wire_ids(source, findings)
    for wire in source["wires"]:
        check_wire(source, tree, wire, findings)
    check_contact_gauges(source, findings)
    cavities = wires_in_cavities(source)
    check_shared_cavities(source, cavities, findings)
    check_connector_use(source, tree, cavities, findings)
    check_twists(source, findings)
    check_cables(source, routes, findings)
    if tree:
        check_layout_use(source, tree, routes, findings)
        check_coverings_and_labels(source, tree, findings)
    expected_nets = (source.get("expect") or {}).get("nets")
    if expected_nets:
        compare_nets(build_nets(source), expected_nets, findings)


def check_wire_ids(source: HarnessSource, findings: Findings) -> None:
    ids = [wire.get("id") for wire in source["wires"]]
    for duplicate in dict.fromkeys(wire_id for wire_id in ids if ids.count(wire_id) > 1):
        findings.error(f"duplicate wire id {duplicate}")


# Each end must land on a defined connector, on a pin it has, named when it has several; the
# connector must be on the layout; the signal should match the pin label; the gauge must suit
# the contact. A wire with both ends on one connector is noted as a loopback.
def check_wire(source: HarnessSource, tree: HarnessTree | None, wire: dict, findings: Findings) -> None:
    """Report problems with one wire's two ends."""
    connectors = source["connectors"]
    for end in ("from", "to"):
        designator, pin = wire_end(wire[end])
        if designator not in connectors:
            findings.error(f"{wire['id']}: {end} connector '{designator}' is not defined")
            continue
        connector = connectors[designator]
        pins = pins_of(connector)
        if ":" not in str(wire[end]) and len(pins) > 1 and not is_splice(connector):
            findings.error(f"{wire['id']}: {end} '{wire[end]}' names no pin, and {designator} has {len(pins)}")
        if pin not in pins:
            findings.error(f"{wire['id']}: {designator} has no pin '{pin}' (pins {pins[0]}..{pins[-1]})")
        if tree and designator not in tree.nodes:
            findings.error(f"{wire['id']}: connector {designator} is not placed in layout.segments")
        label, signal = pin_label(connector, pin), wire.get("signal")
        if signal and label and label != signal and not wire.get("signal_differs_ok"):
            findings.warn(f"{wire['id']}: signal '{signal}' but {designator}:{pin} is labelled '{label}'")
    if wire_end(wire["from"])[0] == wire_end(wire["to"])[0]:
        findings.info(f"{wire['id']}: loopback on {wire_end(wire['from'])[0]}")


# A contact's AWG range is its maker's rating. A wire just outside it can still crimp well when
# its insulation fits, which the shop qualifies, so it is a warning for that decision, not an
# error, and one line per connector names every wire it covers.
def check_contact_gauges(source: HarnessSource, findings: Findings) -> None:
    """Report wires whose gauge is outside a contact's AWG range, or cannot be compared with it."""
    for designator, connector in source["connectors"].items():
        contact_range = connector.get("awg")
        if not contact_range:
            continue
        smallest, largest = min(contact_range), max(contact_range)
        outside = []
        for wire in source["wires"]:
            if designator not in (wire_end(wire.get("from", ""))[0], wire_end(wire.get("to", ""))[0]):
                continue
            gauge = str(wire.get("gauge", ""))
            awg = re.match(r"\s*(\d+)\s*AWG", gauge, re.I)
            if awg and not (smallest <= int(awg.group(1)) <= largest):
                outside.append(f"{wire['id']} ({awg.group(1)} AWG)")
            elif not awg and gauge.strip() and gauge.strip().upper() != "TBD":
                findings.warn(f"{wire['id']}: gauge '{gauge}' is not in AWG, so it was not checked against "
                              f"{designator}'s {smallest}-{largest} AWG range")
        if outside:
            verb = "is" if len(outside) == 1 else "are"
            findings.warn(f"{designator}: {', '.join(outside)} {verb} outside its contact range {smallest}-{largest} AWG; "
                          "confirm the crimp before release")


def wires_in_cavities(source: HarnessSource) -> dict[Cavity, list[str]]:
    """The ids of the wires in each cavity of a defined connector."""
    cavities = defaultdict(list)
    for wire in source["wires"]:
        for end in ("from", "to"):
            designator, pin = wire_end(wire[end])
            if designator in source["connectors"]:
                cavities[(designator, pin)].append(wire["id"])
    return cavities


def check_shared_cavities(source: HarnessSource, cavities: dict[Cavity, list[str]], findings: Findings) -> None:
    """Report cavities holding more than one wire, except splices and listed double crimps."""
    connectors = source["connectors"]
    for (designator, pin), wire_ids in cavities.items():
        connector = connectors[designator]
        double_crimps = [str(listed) for listed in connector.get("double_crimp", [])]
        if len(wire_ids) > 1 and not is_splice(connector) and pin not in double_crimps:
            findings.error(f"{designator}:{pin} has {len(wire_ids)} wires ({', '.join(wire_ids)}); "
                           "use a splice or list the pin in double_crimp")


# A splice should join three or more wires; a labelled pin is meant to be wired; a sealed
# connector needs plugs in its empty cavities; a connector off the layout and unwired is unused.
def check_connector_use(source: HarnessSource, tree: HarnessTree | None, cavities: dict[Cavity, list[str]],
                        findings: Findings) -> None:
    """Report splices, pins and connectors that are used less than they should be."""
    for designator, connector in source["connectors"].items():
        if is_generic(connector):
            findings.warn(f"{designator}: no part number; drawn as a generic connector")
        if is_splice(connector):
            joined = sum(len(wire_ids) for (splice, _), wire_ids in cavities.items() if splice == designator)
            if joined < 3:
                findings.warn(f"splice {designator} joins {joined} wires; a splice normally joins 3 or more")
            continue
        empty = [pin for pin in pins_of(connector) if (designator, pin) not in cavities]
        labelled = [pin for pin in empty if pin_label(connector, pin).upper() not in ("NC", "N/C", "")]
        if labelled:
            listed = ", ".join(f"{pin}({pin_label(connector, pin)})" for pin in labelled)
            findings.warn(f"{designator}: labelled pins not wired: {listed}")
        if empty and connector.get("sealed"):
            findings.info(f"{designator}: {len(empty)} empty cavities need sealing plugs")
        if tree and designator not in tree.nodes and not any(cavity[0] == designator for cavity in cavities):
            findings.warn(f"connector {designator} is defined but unused")


def check_twists(source: HarnessSource, findings: Findings) -> None:
    """Report twist groups of one wire, and groups whose wires end at different connectors."""
    groups = defaultdict(list)
    for wire in source["wires"]:
        if wire.get("twist"):
            groups[wire["twist"]].append(wire)
    for twist, wires in groups.items():
        if len(wires) < 2:
            findings.error(f"twist {twist} has only one wire")
        elif len({frozenset((wire_end(w["from"])[0], wire_end(w["to"])[0])) for w in wires}) > 1:
            findings.warn(f"twist {twist}: wires go to different connectors; twist only over the shared segments")


def check_cables(source: HarnessSource, routes: list[Route], findings: Findings) -> None:
    """Report cables with no conductors, and cables whose conductors share no run for a jacket."""
    for cable_id, cable in source["cables"].items():
        members = [route for wire, route in zip(source["wires"], routes) if wire.get("cable") == cable_id]
        if not members:
            if not cable.get("conductors_rejected"):
                findings.warn(f"cable {cable_id} has no conductors")
        elif all(route.segments for route in members) and not set.intersection(
                *({frozenset(segment) for segment in route.segments} for route in members)):
            findings.error(f"cable {cable_id}: its conductors share no segment, so there is no run for its jacket")


def check_layout_use(source: HarnessSource, tree: HarnessTree, routes: list[Route], findings: Findings) -> None:
    """Note TBD segments, and report segments no wire uses and leaves that are not connectors."""
    to_be_decided = ["-".join(sorted(segment)) + (f" (≥{format_length(tree.segment_minimums[segment])})"
                                                  if segment in tree.segment_minimums else "")
                     for segment, length in tree.segment_lengths.items() if length is None]
    if to_be_decided:
        findings.info(f"{len(to_be_decided)} segment length(s) TBD ({', '.join(to_be_decided)}); cut lengths through them are TBD")
    used = {frozenset(segment) for route in routes for segment in route.segments}
    for segment in tree.segment_lengths:
        if segment not in used:
            findings.warn(f"segment {'-'.join(sorted(segment))} carries no wires")
    for node in tree.order:
        if node not in source["connectors"] and tree.is_leaf(node) and node != tree.root:
            findings.warn(f"layout leaf {node} is not a connector")


# Coverings and labels point at items and layout nodes by name; check that each name exists,
# that every label sits where the standard and its own segment allow, and that an item
# counted per label is bought in the number the labels use.
def check_coverings_and_labels(source: HarnessSource, tree: HarnessTree, findings: Findings) -> None:
    """Report coverings and labels that name things the source lacks or sit where they cannot."""
    item_ids = {item.get("id") for item in source["items"]}
    layout, drawing = source["layout"], source["drawing"]
    units = drawing.get("units", "mm")
    label_limit = conventions(drawing)["label_limit"]
    for covering in layout.get("coverings") or []:
        if covering.get("item") not in item_ids:
            findings.error(f"covering {covering.get('item')}: item {covering.get('item')} is not in items")
    labels = layout.get("labels") or []
    for label in labels:
        name, node = label.get("text", label.get("at")), label.get("at")
        if label.get("item") and label["item"] not in item_ids:
            findings.error(f"label {name}: item {label['item']} is not in items")
        if node not in tree.nodes:
            findings.error(f"label {name}: at {node}, which is not a layout node")
            continue
        distance = label.get("distance", conventions(drawing)["label_distance"])
        if distance > label_limit:
            findings.warn(f"label {name}: {format_length(distance)} {units} from {node} exceeds the "
                          f"{format_length(label_limit)} {units} limit of IPC/WHMA-A-620 §12.4")
        neighbour = tree.neighbour_toward_body(node)
        segment_length = tree.segment_lengths.get(frozenset((node, neighbour))) if neighbour else None
        if segment_length is not None and distance > segment_length:
            findings.error(f"label {name}: {format_length(distance)} {units} from {node} is beyond the "
                           f"{format_length(segment_length)} {units} segment {'-'.join(sorted((node, neighbour)))}")
    for item in source["items"]:
        users = [label for label in labels if label.get("item") == item.get("id")]
        if users and is_number(item.get("qty")) and item["qty"] != len(users):
            findings.error(f"item {item['id']}: qty {format_length(item['qty'])} but {len(users)} labels use it")


# ---------- Netlist ----------


# Join every wire's two cavities, every splice's cavities with each other and every
# connector loop's two pins; what is left joined is a net. Splice cavities are internal.
def build_nets(source: HarnessSource) -> list[set[Cavity]]:
    """The wired nets: groups of two or more connector cavities that are joined."""
    representative = {}

    def find(cavity):
        representative.setdefault(cavity, cavity)
        while representative[cavity] != cavity:
            representative[cavity] = representative[representative[cavity]]
            cavity = representative[cavity]
        return cavity

    def join(first, second):
        representative[find(first)] = find(second)

    connectors = source["connectors"]
    for wire in source["wires"]:
        join(wire_end(wire["from"]), wire_end(wire["to"]))
    for designator, connector in connectors.items():
        if is_splice(connector):
            splice_cavities = [cavity for cavity in list(representative) if cavity[0] == designator]
            for cavity in splice_cavities[1:]:
                join(splice_cavities[0], cavity)
        for first_pin, second_pin in connector.get("loops", []):
            join((designator, str(first_pin)), (designator, str(second_pin)))
    nets = defaultdict(set)
    for cavity in list(representative):
        if not is_splice(connectors.get(cavity[0], {})):
            nets[find(cavity)].add(cavity)
    return [net for net in nets.values() if len(net) > 1]


def cavity_names(cavities) -> str:
    return ",".join(sorted(f"{designator}:{pin}" for designator, pin in cavities))


# Each expected net must be wired at every member, in one piece, with nothing else in it, and
# no wired net may go unclaimed or be claimed by two expected nets.
def compare_nets(built: list[set[Cavity]], expected: dict[str, list], findings: Findings) -> None:
    """Report crossings, opens, shorts and strays between the wired nets and the expected netlist."""
    crossed_nets, crossed_wiring = crossings(built, expected, findings)
    built = [net for index, net in enumerate(built) if index not in crossed_wiring]
    expected = {name: members for name, members in expected.items() if name not in crossed_nets}
    net_of = {cavity: index for index, net in enumerate(built) for cavity in net}
    claimed = {}
    for name, members in expected.items():
        member_cavities = [wire_end(member) for member in members]
        indices = {net_of.get(cavity) for cavity in member_cavities}
        if None in indices:
            missing = [f"{designator}:{pin}" for designator, pin in member_cavities if net_of.get((designator, pin)) is None]
            findings.error(f"net {name}: not wired at {', '.join(missing)}")
        indices.discard(None)
        if len(indices) > 1:
            findings.error(f"net {name}: split into {len(indices)} pieces (open between "
                           + " | ".join(cavity_names(built[index]) for index in indices) + ")")
        for index in indices:
            if index in claimed and claimed[index] != name:
                findings.error(f"SHORT: nets {claimed[index]} and {name} are connected")
            claimed[index] = name
            stray = {f"{d}:{p}" for d, p in built[index]} - {f"{d}:{p}" for d, p in member_cavities}
            if stray:
                findings.error(f"net {name}: unexpected members {', '.join(sorted(stray))}")
    for index, net in enumerate(built):
        if index not in claimed:
            findings.error(f"wired connection not in expected netlist: {', '.join(sorted(f'{d}:{p}' for d, p in net))}")


# Wires swapped between their pins: a group of expected nets wired with exactly their own pins,
# as many wired nets as expected ones, but each wired net joining pins of two or more of them.
# That is one mistake, reported once, and left out of the open, short and stray checks.
def crossings(built: list[set[Cavity]], expected: dict[str, list], findings: Findings) -> tuple[set[str], set[int]]:
    """Report each crossed group of nets; return the expected nets and wired nets it accounts for."""
    members = {name: {wire_end(member) for member in cavities} for name, cavities in expected.items()}
    touching = {index: {name for name, cavities in members.items() if cavities & net} for index, net in enumerate(built)}
    crossed_nets, crossed_wiring = set(), set()
    for index, names in touching.items():
        if len(names) < 2 or index in crossed_wiring:
            continue
        group, wiring = set(names), {index}
        while True:
            more = {other for other, touched in touching.items() if touched & group} - wiring
            if not more:
                break
            wiring |= more
            group |= set().union(*(touching[other] for other in more))
        wanted = set().union(*(members[name] for name in group))
        wired = set().union(*(built[other] for other in wiring))
        if wired == wanted and len(wiring) == len(group) and all(len(touching[other]) > 1 for other in wiring):
            names_text = " and ".join(sorted(group)) if len(group) == 2 else ", ".join(sorted(group))
            listed = [wire_end(member) for name in sorted(group) for member in expected[name]]
            place = {cavity: position for name in group for position, cavity in enumerate(map(wire_end, expected[name]))}
            ends = [sorted(built[other], key=lambda cavity: (place[cavity], listed.index(cavity))) for other in wiring]
            pairs = ", ".join("–".join(f"{d}:{p}" for d, p in net) for net in sorted(ends, key=lambda net: listed.index(net[0])))
            findings.error(f"nets {names_text} are crossed: wired {pairs}")
            crossed_nets |= group
            crossed_wiring |= wiring
    return crossed_nets, crossed_wiring
