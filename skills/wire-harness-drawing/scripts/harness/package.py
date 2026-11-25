"""The whole package from one harness source: checks, then CSVs, sheets and the combined PDF."""
import argparse
import csv
import json
from dataclasses import dataclass
from pathlib import Path

from harness.bom import BomLine, build_bom
from harness.cables import CableCut, cable_cuts, conductor_leads
from harness.checks import check_harness
from harness.explorer_model import harness_model
from harness.formboard import formboard_sheet, sheet_misfits
from harness.routing import HarnessTree, Route, build_tree, route_wires
from harness.source import format_length, Findings, HarnessSource, load_source, wire_end
from harness.tables import table_sheet_bodies, table_sheets
from harness.validation import validate_source
from harness.wiring import render_wiring_diagram, wireviz_available, wireviz_source, wiring_sheet


# A source after every check: what was found, and what the outputs are built from. The tree
# and BOM are None when the layout has no usable root.
@dataclass
class Analysis:
    source: HarnessSource
    findings: Findings
    tree: HarnessTree | None
    routes: list[Route]
    bom: list[BomLine] | None
    cable_cuts: list[CableCut]


# Validate, route and check the source; then lay sheet 1 out, because whether the drawing
# fits its sheet is a check too.
def analyse(source: HarnessSource) -> Analysis:
    """Every finding about a source, and the model the outputs are built from."""
    findings = Findings()
    validate_source(source, findings)
    tree = build_tree(source, findings)
    routes = route_wires(source, tree)
    check_harness(source, tree, routes, findings)
    cuts = cable_cuts(source, tree, routes) if tree else []
    bom = build_bom(source, tree, routes, cuts) if tree else None
    if tree:
        misfits = sheet_misfits(formboard_sheet(source, tree, routes, bom, 1, 0)[1])
        if misfits:
            findings.error("harness drawing does not fit sheet 1: " + "; ".join(misfits)
                           + ". Split the harness into sub-harnesses or shorten its text")
    return Analysis(source, findings, tree, routes, bom, cuts)


def write_bom_csv(path: Path, bom: list[BomLine]) -> None:
    with open(path, "w", newline="") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(["find", "qty", "unit", "pn", "description", "manufacturer", "refs"])
        for line in bom:
            writer.writerow([line.find, line.csv_quantity(), line.unit, line.part_number, line.description,
                             line.manufacturer, " ".join(line.ref_list())])


# A loose wire has a cut length; a cable's conductor is cut with its cable, so it has instead
# its lead beyond the jacket at each end.
def write_wire_list_csv(path: Path, source: HarnessSource, routes: list[Route], cuts: list[CableCut]) -> None:
    """One row per wire or conductor for cutting, stripping and crimping, with its route through the harness."""
    connectors = source["connectors"]
    with open(path, "w", newline="") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(["wire", "from", "from_pin", "to", "to_pin", "signal", "gauge", "color", "cut_length", "lead_a", "lead_b",
                         "twist", "cable", "strip_a", "strip_b", "path"])
        for wire, route in zip(source["wires"], routes):
            (start, start_pin), (end, end_pin) = wire_end(wire["from"]), wire_end(wire["to"])
            writer.writerow([wire["id"], start, start_pin, end, end_pin, wire.get("signal", ""), wire.get("gauge", ""),
                             wire.get("color", ""), "" if wire.get("cable") else route.cut_length_text(),
                             *conductor_leads(cuts, wire), wire.get("twist", ""),
                             wire.get("cable", ""), connectors.get(start, {}).get("strip", ""),
                             connectors.get(end, {}).get("strip", ""), " > ".join(route.node_names())])


def write_cables_csv(path: Path, source: HarnessSource, cuts: list[CableCut]) -> None:
    """One row per cable: its cut length, jacket length, and the jacket to strip back at each end."""
    with open(path, "w", newline="") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(["cable", "pn", "description", "cut_length", "jacket_length", "end_a", "strip_a", "end_b", "strip_b", "run"])
        for cut in cuts:
            cable = source["cables"][cut.cable]
            writer.writerow([cut.cable, cable.get("pn", ""), cable.get("desc", ""), format_length(cut.cut_length),
                             format_length(cut.jacket_length), cut.ends[0].node, format_length(cut.ends[0].strip_back()),
                             cut.ends[1].node, format_length(cut.ends[1].strip_back()), " > ".join(cut.run)])


# The PDF needs cairosvg, which needs the Cairo library, and pypdf. Either may be missing,
# so they are imported only here; without them the package is complete except for the PDF.
def write_pdf(svg_paths: list[Path], pdf_path: Path) -> str | None:
    """Combine the sheets into one PDF; return why it was not written, or None."""
    try:
        import cairosvg
        from pypdf import PdfReader, PdfWriter
    except (ImportError, OSError) as missing:
        return f"PDF not written: {missing}"
    writer = PdfWriter()
    for svg_path in svg_paths:
        page_path = svg_path.with_suffix(".pdf")
        cairosvg.svg2pdf(url=str(svg_path), write_to=str(page_path))
        for page in PdfReader(page_path).pages:
            writer.add_page(page)
        page_path.unlink()
    with open(pdf_path, "wb") as pdf_file:
        writer.write(pdf_file)
    return None


# Sheet 1 is the formboard drawing, the table sheets follow, and the wiring diagram, when
# WireViz can render it, is last.
def write_package(analysis: Analysis, output_directory: Path, base: str, *, with_wiring_diagram: bool) -> list[Path]:
    """Write the CSVs, sheets and PDF; return the sheet paths."""
    source, routes, bom, errors = analysis.source, analysis.routes, analysis.bom, analysis.findings.error_count
    write_bom_csv(output_directory / f"{base}.bom.csv", bom)
    write_wire_list_csv(output_directory / f"{base}.wirelist.csv", source, routes, analysis.cable_cuts)
    if analysis.cable_cuts:
        write_cables_csv(output_directory / f"{base}.cables.csv", source, analysis.cable_cuts)
    # Escaping "</" keeps the JSON valid and safe to inline inside a script element.
    model = json.dumps(harness_model(analysis), indent=1, ensure_ascii=False).replace("</", "<\\/")
    (output_directory / f"{base}.harness.json").write_text(model + "\n")
    diagram_path = None
    if not with_wiring_diagram:
        print("NOTE  ", "skipped (--no-wireviz)")
    elif not wireviz_available():
        print("NOTE  ", "wireviz or graphviz (dot) not on PATH; wiring diagram sheet skipped")
    else:
        diagram_path, failure = render_wiring_diagram(wireviz_source(source, routes), output_directory, base)
        if failure:
            print("NOTE  ", failure)
    bodies = table_sheet_bodies(source, routes, bom, analysis.cable_cuts)
    sheet_count = 1 + len(bodies) + (1 if diagram_path else 0)
    sheets = [formboard_sheet(source, analysis.tree, routes, bom, sheet_count, errors)[0]]
    sheets += table_sheets(source, bodies, 2, sheet_count, errors)
    if diagram_path:
        sheets.append(wiring_sheet(source, diagram_path, sheet_count, sheet_count, errors))
    paths = []
    for number, sheet in enumerate(sheets, 1):
        path = output_directory / f"{base}.sheet{number}.svg"
        path.write_text(sheet)
        paths.append(path)
    pdf_problem = write_pdf(paths, output_directory / f"{base}.pdf")
    if pdf_problem:
        print("NOTE  ", pdf_problem)
    return paths


def parse_arguments(arguments: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a wire harness drawing package from a harness YAML source.")
    parser.add_argument("yaml", type=Path, help="the harness source")
    parser.add_argument("-o", "--outdir", type=Path, help="output directory (default: <source>-out beside the source)")
    parser.add_argument("--check-only", action="store_true", help="write only the checks report")
    parser.add_argument("--no-wireviz", action="store_true", help="leave out the wiring diagram sheet")
    return parser.parse_args(arguments)


# Exit 1 when any check fails, so a build or script can stop on it.
def main(arguments: list[str]) -> int:
    """Run the generator from the command line; return its exit code."""
    options = parse_arguments(arguments)
    base = options.yaml.stem
    output_directory = options.outdir or options.yaml.resolve().parent / f"{base}-out"
    output_directory.mkdir(parents=True, exist_ok=True)
    analysis = analyse(load_source(options.yaml))
    report = analysis.findings.report()
    print(report)
    (output_directory / f"{base}.checks.txt").write_text(report + "\n")
    failed = 1 if analysis.findings.error_count else 0
    if options.check_only:
        return failed
    if analysis.tree is None:
        print("cannot draw: layout is broken")
        return 1
    paths = write_package(analysis, output_directory, base, with_wiring_diagram=not options.no_wireviz)
    print(f"wrote {len(paths)} sheets to {output_directory}")
    return failed
