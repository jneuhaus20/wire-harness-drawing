"""How each multi-conductor cable is cut: its overall length, its jacket, and the leads at each end."""
import math
from dataclasses import dataclass

from harness.routing import HarnessTree, Route
from harness.source import HarnessSource, conventions, format_length, wire_end

# The jacket stops this short of a connector it runs right up to, so the conductors can fan
# into their cavities: 40 mm, or 1.5 in. A cable states one breakout for both ends, or one per
# end by node; an end it does not name takes the default, and a factory-terminated end takes 0.
default_breakout = {"mm": 40, "in": 1.5}


def breakout_at(source: HarnessSource, cable: dict, node: str) -> float:
    """How far short of a connector at the given jacket end the cable's jacket stops."""
    default = default_breakout.get(source["drawing"].get("units", "mm"), 40)
    breakout = cable.get("breakout", default)
    return float(breakout.get(node, default) if isinstance(breakout, dict) else breakout)


def breakout_misnamings(source: HarnessSource, cuts: list["CableCut"]) -> list[str]:
    """A finding for each cable whose breakout names a node its jacket does not end at."""
    problems = []
    for cut in cuts:
        breakout = source["cables"][cut.cable].get("breakout")
        ends = (cut.run[0], cut.run[-1])
        for node in breakout if isinstance(breakout, dict) else ():
            if node not in ends:
                problems.append(f"cable {cut.cable}: breakout names {node}, which is not an end of its jacket ({', '.join(ends)})")
    return problems


# One end of a cable's jacket: where it ends, how far short of that node it stops (zero where
# the conductors part at a breakout), each conductor's lead beyond it, and the connectors those
# leads go to.
@dataclass
class CableEnd:
    node: str
    breakout: float
    leads: dict[str, float | None]
    connectors: set[str]

    def strip_back(self) -> float | None:
        """How much jacket to remove at this end: enough for the longest lead."""
        return None if None in self.leads.values() else max(self.leads.values(), default=0)


@dataclass
class CableCut:
    cable: str
    run: list[str]  # the nodes the jacket runs through, end A first
    ends: tuple[CableEnd, CableEnd]
    jacket_length: float | None
    cut_length: float | None

    def lead(self, conductor: str, connector: str) -> float | None:
        """A conductor's lead at the end of the cable its given connector lies beyond."""
        for end in self.ends:
            if connector in end.connectors and conductor in end.leads:
                return end.leads[conductor]
        return None


def conductor_leads(cuts: list[CableCut], wire: dict) -> tuple[str, str]:
    """A cable conductor's lead at its from end and its to end, as printed; blank for a loose wire."""
    cut = next((cut for cut in cuts if cut.cable == wire.get("cable")), None)
    if cut is None:
        return "", ""
    return tuple(format_length(cut.lead(wire["id"], wire_end(wire[end])[0])) for end in ("from", "to"))


def rounded_up(source: HarnessSource, length: float | None) -> float | None:
    """A length rounded up to the drawing's round_to, as every cut length is."""
    if length is None:
        return None
    rounding = float(source["drawing"].get("round_to", conventions(source["drawing"])["round_to"]))
    return math.ceil(round(length / rounding, 9)) * rounding


def cable_cuts(source: HarnessSource, tree: HarnessTree, routes: list[Route]) -> list[CableCut]:
    """How each routed cable with conductors is cut."""
    cuts = []
    for cable_id, cable in source["cables"].items():
        members = [(wire, route) for wire, route in zip(source["wires"], routes) if wire.get("cable") == cable_id]
        if not members or not all(route.segments for _, route in members):
            continue
        shared = set.intersection(*({frozenset(segment) for segment in route.segments} for _, route in members))
        if shared:
            cuts.append(cut_cable(source, tree, cable_id, cable, members))
    return cuts


# The jacket covers the run every conductor shares. Where that run ends at a connector, the
# jacket stops the breakout length short of it and every lead is that length; where it ends at
# a breakout, each lead runs on to its own connector. Each lead adds its connector's wire
# allowance. The cable is cut to its jacket plus the longest lead at each end, plus the
# per-wire extra, rounded up like any cut length.
def cut_cable(source: HarnessSource, tree: HarnessTree, cable_id: str, cable: dict, members: list) -> CableCut:
    """How one cable is cut."""
    drawing = source["drawing"]
    shared = set.intersection(*({frozenset(segment) for segment in route.segments} for _, route in members))
    run = longest_shared_run(members[0][1].node_names(), shared)
    run_lengths = [tree.segment_lengths[frozenset(pair)] for pair in zip(run, run[1:])]
    ends = tuple(cable_end(source, tree, members, run, end_node, breakout_at(source, cable, end_node)) for end_node in (run[0], run[-1]))
    jacket = None if None in run_lengths else sum(run_lengths) - ends[0].breakout - ends[1].breakout
    strips = [end.strip_back() for end in ends]
    total = None if jacket is None or None in strips else jacket + sum(strips) + float(drawing.get("extra_per_wire", 0))
    return CableCut(cable_id, run, ends, jacket, rounded_up(source, total))


def cable_end(source: HarnessSource, tree: HarnessTree, members: list, run: list[str], end_node: str, breakout: float) -> CableEnd:
    """One end of a cable's jacket, with each conductor's lead beyond it."""
    at_connector = end_node in source["connectors"]
    leads, connectors = {}, set()
    for wire, route in members:
        connector = conductor_end_beyond(route.node_names(), end_node, run)
        connectors.add(connector)
        lengths = [tree.segment_lengths[frozenset(segment)] for segment in tree.path(end_node, connector)]
        allowance = float(source["connectors"].get(connector, {}).get("wire_allowance", 0))
        lead = None if None in lengths else (breakout if at_connector else 0) + sum(lengths) + allowance
        leads[wire["id"]] = rounded_up(source, lead)
    return CableEnd(end_node, breakout if at_connector else 0, leads, connectors)


def longest_shared_run(route_nodes: list[str], shared: set) -> list[str]:
    """The longest stretch of a route whose segments are all shared."""
    best, current = [], [route_nodes[0]]
    for start, end in zip(route_nodes, route_nodes[1:]):
        current = current + [end] if frozenset((start, end)) in shared else [end]
        if len(current) > len(best):
            best = list(current)
    return best


def conductor_end_beyond(route_nodes: list[str], run_end: str, run: list[str]) -> str:
    """The end of a conductor's route that lies beyond the given end of the jacket run."""
    inner = run[1] if run_end == run[0] else run[-2]
    toward_start = route_nodes.index(inner) > route_nodes.index(run_end)
    return route_nodes[0] if toward_start else route_nodes[-1]
