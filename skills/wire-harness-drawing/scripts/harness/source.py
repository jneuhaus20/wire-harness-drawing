"""The harness source: reading it, the findings about it, and the conventions it is read by."""
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml

HarnessSource = dict[str, Any]
Severity = Literal["ERROR", "WARN", "INFO"]


# ---------- Findings ----------


# Every check reports here. An ERROR or WARN said twice is kept once; INFO lines are kept as
# given, since each names its own wire.
@dataclass
class Findings:
    """The ordered ERROR, WARN and INFO lines about one harness source."""

    items: list[tuple[Severity, str]] = field(default_factory=list)

    def error(self, message: str) -> None:
        self._add_once("ERROR", message)

    def warn(self, message: str) -> None:
        self._add_once("WARN", message)

    def info(self, message: str) -> None:
        self.items.append(("INFO", message))

    @property
    def error_count(self) -> int:
        return sum(1 for severity, _ in self.items if severity == "ERROR")

    def report(self) -> str:
        """The findings as the lines of the checks report."""
        return "\n".join(f"{severity:5}  {message}" for severity, message in self.items) or "OK     no findings"

    def _add_once(self, severity: Severity, message: str) -> None:
        if (severity, message) not in self.items:
            self.items.append((severity, message))


# ---------- Reading ----------


# YAML 1.1 reads yes/no/on/off as booleans, which turns a relay contact "NO" or a
# signal "OFF" into false. Harness sources follow YAML 1.2 here: only true/false are booleans.
class HarnessLoader(yaml.SafeLoader):
    """A safe YAML loader whose only boolean words are true and false."""


HarnessLoader.yaml_implicit_resolvers = {
    first_character: [(tag, pattern) for tag, pattern in resolvers if tag != "tag:yaml.org,2002:bool"]
    for first_character, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
HarnessLoader.add_implicit_resolver(
    "tag:yaml.org,2002:bool", re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$"), list("tTfF")
)

section_defaults: dict[str, type] = {
    "drawing": dict, "connectors": dict, "wires": list, "layout": dict, "items": list, "cables": dict,
}


def load_source(path: Path) -> HarnessSource:
    """Read a harness YAML file; a section left empty ("items:") reads as absent."""
    with open(path) as source_file:
        source = yaml.load(source_file, Loader=HarnessLoader)
    for section, empty in section_defaults.items():
        if source.get(section) is None:
            source[section] = empty()
    return source


# ---------- Units ----------


# Every default that is a length depends on the drawing's unit, and so does how wire and
# covering is bought. Keep them together so an inch drawing never inherits a millimetre default.
unit_conventions: dict[str, dict[str, Any]] = {
    "mm": dict(tolerance=[{"upto": 300, "tol": 5}, {"upto": 1000, "tol": 10}, {"upto": None, "tol": "1%"}],
               round_to=5, loopback_length=100, label_distance=50, label_limit=300, stand_in_length=300,
               purchase_unit="m", lengths_per_purchase_unit=1000),
    "in": dict(tolerance=[{"upto": 12, "tol": 0.25}, {"upto": 40, "tol": 0.5}, {"upto": None, "tol": "1%"}],
               round_to=0.25, loopback_length=4, label_distance=2, label_limit=12, stand_in_length=12,
               purchase_unit="ft", lengths_per_purchase_unit=12),
}

default_twist_takeup = "3%"


def conventions(drawing: dict) -> dict[str, Any]:
    """The unit conventions for a drawing; an unknown unit reads as mm and is reported by validation."""
    return unit_conventions.get(drawing.get("units", "mm"), unit_conventions["mm"])


def twist_takeup(drawing: dict) -> float:
    """The fraction twisted wires are lengthened by over their twisted run."""
    return float(drawing.get("twist_takeup", default_twist_takeup).rstrip("%")) / 100


# Tolerance rows apply in order; a percentage tolerance rounds to whole units from 5 up.
def tolerance_for(drawing: dict, length: float | None) -> float | str | None:
    """The tolerance a length gets from the drawing's tolerance table."""
    if length is None:
        return None
    for row in drawing.get("tolerance", conventions(drawing)["tolerance"]):
        if row.get("upto") is None or length <= row["upto"]:
            tolerance = row["tol"]
            if isinstance(tolerance, str) and tolerance.endswith("%"):
                value = length * float(tolerance[:-1]) / 100.0
                return round(value) if value >= 5 else round(value, 1)
            return tolerance
    return 0


def format_length(value: Any) -> str:
    """A length or count as printed: TBD for None, no trailing zeros for numbers."""
    if value is None:
        return "TBD"
    return f"{value:g}" if isinstance(value, (int, float)) else str(value)


def is_number(value: Any) -> bool:
    """True for an int or float read from YAML; a bool is not a number here."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


# ---------- Connectors and wire ends ----------


def wire_end(text: Any) -> tuple[str, str]:
    """'P1:3' -> ('P1', '3'); 'SP1' -> ('SP1', '1')."""
    text = str(text)
    if ":" in text:
        designator, pin = text.split(":", 1)
        return designator.strip(), pin.strip()
    return text.strip(), "1"


def wire_connectors(wire: dict) -> tuple[str, str]:
    """The designators at a wire's from and to ends."""
    return wire_end(wire["from"])[0], wire_end(wire["to"])[0]


def is_splice(connector: dict) -> bool:
    return connector.get("type", "").lower() == "splice"


connector_shapes = ("rectangular", "circular")
connector_genders = ("male", "female")
face_views = ("mating face", "rear")
face_layouts = ("grid", "ring", "cavities")


def is_generic(connector: dict) -> bool:
    """A connector whose part is not chosen yet: no part number. Splices are drawn as splices regardless."""
    return not connector.get("pn") and not is_splice(connector)


# A stated cavity layout, as seen from its stated view: a rows × columns grid numbered along
# rows (or columns), a ring numbered clockwise from the top, or explicit positions. Positions
# are in cavity pitches with y down; they are empty when the source states no layout.
def cavity_positions(connector: dict) -> dict[str, tuple[float, float]]:
    """Where each pin's cavity sits on the connector face."""
    face = connector.get("face") or {}
    pins = pins_of(connector)
    if "grid" in face:
        rows, columns = face["grid"]
        by_columns = face.get("numbering") == "columns"
        return {pin: ((index // rows, index % rows) if by_columns else (index % columns, index // columns))
                for index, pin in enumerate(pins)}
    if "ring" in face:
        count = len(pins)
        return {pin: (math.sin(2 * math.pi * index / count), -math.cos(2 * math.pi * index / count))
                for index, pin in enumerate(pins)}
    if "cavities" in face:
        cavities = {str(pin): tuple(position) for pin, position in face["cavities"].items()}
        return {pin: cavities[pin] for pin in pins}
    return {}


def pins_of(connector: dict) -> list[str]:
    """A connector's pin names: its pins list, or 1..pincount."""
    if "pins" in connector:
        return [str(pin) for pin in connector["pins"]]
    count = connector.get("pincount") or len(connector.get("pinlabels", [])) or 1
    return [str(number) for number in range(1, count + 1)]


def pin_label(connector: dict, pin: str) -> str:
    """The label of one pin, from a pinlabels list or mapping; empty when it has none."""
    labels = connector.get("pinlabels") or []
    if isinstance(labels, dict):
        return str(labels.get(pin, labels.get(int(pin) if pin.isdigit() else pin, "")) or "")
    pins = pins_of(connector)
    if pin not in pins:
        return ""
    index = pins.index(pin)
    return str(labels[index]) if index < len(labels) and labels[index] is not None else ""


# ---------- Colours ----------


# IEC 60757 two-letter codes and the colour each is drawn in: insulation colours, softened from
# pure hues so a sheet full of wires stays readable.
display_colors = {
    "BK": "#2f2f2f", "BN": "#8a5a3b", "RD": "#c4453f", "OG": "#dd8a3c", "YE": "#e2c54b",
    "GN": "#4e9a5f", "BU": "#4c7cc4", "VT": "#8667b8", "GY": "#9a9a96", "WH": "#eeeeea",
    "PK": "#e2a0b6", "TQ": "#4fb0ab", "SR": "#c3c3c0", "GD": "#c9a54a",
}
unknown_color = "#888888"


# The other ways people write each colour: three-letter abbreviations, English names, and the
# older two-letter forms. Each reads as its IEC code.
color_aliases = {
    "BK": ["BLK", "BLACK"], "BN": ["BRN", "BROWN", "BR"], "RD": ["RED"], "OG": ["ORN", "ORG", "ORANGE", "OR"],
    "YE": ["YEL", "YLW", "YELLOW"], "GN": ["GRN", "GREEN"], "BU": ["BLU", "BLUE", "BL"],
    "VT": ["VIO", "VLT", "VIOLET", "PUR", "PRP", "PURPLE", "VI"], "GY": ["GRY", "GRA", "GREY", "GRAY", "GR"],
    "WH": ["WHT", "WHI", "WHITE"], "PK": ["PNK", "PINK"], "TQ": ["TRQ", "TUR", "TURQUOISE"],
    "SR": ["SLV", "SILVER"], "GD": ["GLD", "GOLD"],
}
iec_codes = {"BK", "BN", "RD", "OG", "YE", "GN", "BU", "VT", "GY", "WH", "PK", "TQ", "SR", "GD"}
code_for_word = {alias: code for code, aliases in color_aliases.items() for alias in aliases} | {code: code for code in iec_codes}
# Words that join a base colour to its stripe: "white with blue stripe".
color_joining_words = {"WITH", "AND", "STRIPE", "STRIPED", "TRACER"}


# Base colour first, then any stripes: each word is a code, an alias, or IEC codes run together (GNYE).
def iec_color_code(written: str) -> str | None:
    """A colour as written, as its IEC 60757 code ('WHT/BLU' -> 'WHBU'); None if a part is not a colour."""
    words = [word for word in re.split(r"[^A-Z]+", str(written).upper()) if word and word not in color_joining_words]
    codes = []
    for word in words:
        if word in code_for_word:
            codes.append(code_for_word[word])
        elif len(word) % 2 == 0 and all(word[i:i + 2] in iec_codes for i in range(0, len(word), 2)):
            codes.extend(word[i:i + 2] for i in range(0, len(word), 2))
        else:
            return None
    return "".join(codes) or None


# A colour still to be decided is written TBD (or TBC): printed as written, drawn as no colour.
undecided_colors = {"TBD", "TBC"}


def chosen_color(owner: dict) -> str | None:
    """A wire's or cable's colour code, or None when it is not chosen yet."""
    color = owner.get("color")
    return None if not color or str(color).upper() in undecided_colors else color


def color_parts(code: str | None) -> list[str]:
    """A colour code's two-letter parts, base colour first: 'GNYE' -> ['GN', 'YE']."""
    code = (code or "").replace("/", "").upper()
    return [code[i:i + 2] for i in range(0, len(code), 2)] or ["GY"]


def display_color(part: str) -> str:
    return display_colors.get(part, unknown_color)
