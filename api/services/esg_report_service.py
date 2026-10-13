"""ESG/compliance PDF sustainability report -- ties the Sustainability tab's
own metrics (PUE, WUE, carbon, water stress, the industry benchmark) into a
document a facility operator can actually hand to a compliance/budget
reviewer, instead of a live dashboard only.

Uses reportlab (pure Python, no system-level PDF toolchain needed) --
added to requirements.txt in this pass. Not runnable/verified in the
assistant's sandbox (no network to install it); the API is stable enough
that this should work as written, but run it locally before trusting it in
production.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.carbon_provider import FALLBACK_FLAT_INTENSITY_GCO2_PER_KWH
from src.facility_benchmarking import benchmark_pue

SIMULATED_NOTICE = (
    "SIMULATED DATA: every figure in this report comes from the TwinGrid simulator. "
    "None of it is a measurement from a real facility."
)


def carbon_report_section(state: dict[str, Any]) -> dict[str, Any]:
    """The carbon wording of the report, as plain data (no reportlab needed, so it is unit-testable).

    ``carbon_data_is_real`` False (or missing) means the flat assumed intensity: the table says ASSUMPTION, never
    "Real", and ``warning`` is a paragraph the report must print. When it is True the report still does not claim
    a live grid feed: the series' source and average/marginal basis live in the backend carbon label.
    """
    if state.get("carbon_data_is_real") is True:
        return {
            "value": "Loaded series",
            "note": "Hour-of-day mean of a loaded series, not a live grid feed. Source and "
            "average/marginal basis: see the backend carbon label.",
            "warning": None,
        }
    shown = state.get("carbon_intensity_gco2_per_kwh")
    intensity = float(shown) if isinstance(shown, (int, float)) else FALLBACK_FLAT_INTENSITY_GCO2_PER_KWH
    return {
        "value": "ASSUMPTION",
        "note": f"Flat {intensity:.0f} gCO2/kWh world-average assumption (IEA/Ember). "
        "Not measured grid data; not specific to any site.",
        "warning": (
            "CARBON FIGURES ARE ASSUMED, NOT MEASURED. This report's carbon numbers use a flat "
            f"{intensity:.0f} gCO2/kWh world-average assumption, the same value at every hour and for every place. "
            "No grid carbon-intensity dataset is loaded. Treat every carbon number here as illustrative; "
            "it supports no emissions-reduction claim."
        ),
    }


def generate_report(state: dict[str, Any], output_path: str | Path) -> Path:
    """Render a one-page ESG summary PDF from a state dict shaped like
    api.services.twin_service.compute_state()'s return value (or
    DataCentreState.to_dict()) -- must have pue, wue, cooling_power_kw,
    it_power_kw, water_consumed_L, water_flow_lpm, and carbon_data_is_real.

    Returns the path written.
    """
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(str(output_path), pagesize=letter)
    story: list[Any] = []

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    story.append(Paragraph("TwinGrid Sustainability Report", styles["Title"]))
    story.append(Paragraph(f"Generated {generated_at}", styles["Normal"]))
    story.append(Spacer(1, 0.1 * inch))
    story.append(Paragraph(SIMULATED_NOTICE, styles["Italic"]))
    story.append(Spacer(1, 0.3 * inch))

    pue = float(state.get("pue", 0.0))
    bm = benchmark_pue(pue)
    carbon = carbon_report_section(state)

    rows = [
        ["Metric", "Value", "Note"],
        ["PUE", f"{pue:.3f}", f"{bm['band'].replace('_', ' ').title()} -- {bm['note']}"],
        ["WUE (L/kWh)", f"{state.get('wue', 0.0):.3f}", ""],
        ["IT power (kW)", f"{state.get('it_power_kw', 0.0):.1f}", ""],
        ["Cooling power (kW)", f"{state.get('cooling_power_kw', 0.0):.1f}", ""],
        ["Water consumed (L, cumulative)", f"{state.get('water_consumed_L', 0.0):.1f}", ""],
        ["Carbon intensity data", carbon["value"], Paragraph(carbon["note"], styles["BodyText"])],
    ]
    table = Table(rows, colWidths=[2.0 * inch, 1.2 * inch, 3.3 * inch])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2937")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f3f4f6")]),
            ]
        )
    )
    story.append(table)
    story.append(Spacer(1, 0.3 * inch))

    story.append(
        Paragraph(
            f"Benchmark source: {bm['source']} -- industry average PUE "
            f"{bm['industry_average_2024']:.2f}, capacity-weighted average "
            f"{bm['industry_capacity_weighted_2024']:.2f}.",
            styles["Italic"],
        )
    )
    if carbon["warning"]:
        story.append(Spacer(1, 0.1 * inch))
        story.append(Paragraph(f"<b>{carbon['warning']}</b>", styles["Normal"]))

    doc.build(story)
    return output_path
