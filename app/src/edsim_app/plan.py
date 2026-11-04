"""Render a service plan as escaped SVG, independent of Streamlit."""

from datetime import date, datetime, time, timedelta
from html import escape
from math import ceil

from edsim.runs import TIMEZONE, ReplayCounts, ReplayPatient, ReplayState
from edsim_app.palette import LEVEL_COLORS, UNKNOWN_LEVEL_COLOR

STATE_LABELS = {
    "waiting_triage": "Espera triaje",
    "triage": "Triaje",
    "waiting_box": "Espera box",
    "waiting_doctor": "Espera médico",
    "assessment": "Valoración",
    "waiting_tests": "Espera pruebas",
    "reassessment": "Reevaluación",
}


def render_plan(
    state: ReplayState,
    counts: ReplayCounts,
    *,
    start_date: date,
    highlighted_episode: str | None = None,
) -> str:
    """Draw bounded queues and one cell per physical box; totals are supplied curves."""
    waiting_triage = sorted(
        (p for p in state.patients if p.state == "waiting_triage"),
        key=lambda p: (p.arrival, p.episode_id),
    )
    waiting_box = sorted(
        (p for p in state.patients if p.state == "waiting_box"),
        key=lambda p: (p.level, p.arrival, p.episode_id),
    )
    height = max(
        450,
        130 + 38 * min(30, max(len(waiting_triage), len(waiting_box))),
        130 + 76 * ceil(counts.boxes / 4),
        130
        + 48
        * max(counts.nurses_staff, counts.nurses_busy, counts.doctors_staff, counts.doctors_busy),
    )
    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1440 {height}" '
        'role="img" aria-label="Plano del servicio de urgencias">',
        "<style>text{font-family:system-ui,sans-serif;font-size:12px;fill:#17212b}"
        ".heading{font-size:16px;font-weight:bold}</style>",
        f'<rect width="1440" height="{height}" fill="#ffffff" rx="8"/>',
    ]

    def text(x, y, value, css="", attributes=""):
        svg.append(f'<text x="{x}" y="{y}" class="{css}" {attributes}>{escape(str(value))}</text>')

    def title_for(displacements):
        titles = []
        for d in displacements:
            stamp = datetime.combine(start_date, time(), TIMEZONE) + timedelta(minutes=d.time)
            titles.append(
                f"Desalojo {stamp:%d/%m/%Y %H:%M:%S} · box {d.box} · "
                f"{d.episode_id} · desalojado_por: {d.displaced_by}"
            )
        return "<title>" + escape("; ".join(titles)) + "</title>"

    recent = tuple(d for d in state.displacements if state.time - 60 < d.time <= state.time)

    def patient(p: ReplayPatient, x, y, width=180, height=32, *, label=None):
        svg.append(f'<g data-role="patient" data-episode="{escape(p.episode_id, quote=True)}">')
        displaced = tuple(d for d in recent if d.episode_id == p.episode_id)
        stroke = "#c62828" if displaced else "#596773"
        mark = ' data-mark="displaced-patient"' if displaced else ""
        svg.append(
            f'<rect x="{x}" y="{y}" width="{width}" height="{height}" rx="5" '
            f'fill="{LEVEL_COLORS.get(p.level, UNKNOWN_LEVEL_COLOR)}" stroke="{stroke}" '
            f'stroke-width="{3 if displaced else 1}"{mark}/>'
        )
        if displaced:
            svg.append(title_for(displaced))
        else:
            svg.append(f"<title>{escape(p.episode_id)} · {escape(STATE_LABELS[p.state])}</title>")
        text(x + 5, y + 15, label or p.episode_id)
        if height >= 45:
            text(x + 5, y + 32, STATE_LABELS[p.state])
        if p.episode_id == highlighted_episode:
            svg.append(
                f'<rect data-mark="highlight" x="{x - 3}" y="{y - 3}" '
                f'width="{width + 6}" height="{height + 6}" rx="6" '
                'fill="none" stroke="#6a1b9a" stroke-width="3"/>'
            )
        svg.append("</g>")

    def queue(patients, x, title, total, role):
        text(x, 26, title, "heading")
        text(x, 48, f"Total: {total}", attributes=f'data-count="{role}"')
        svg.append(f'<g data-role="{role}-queue">')
        for i, p in enumerate(patients[:30]):
            patient(p, x, 66 + i * 38)
        if total > 30:
            text(x, 80 + 30 * 38, f"+{total - 30} más")
        svg.append("</g>")

    def staff(x, title, busy, capacity, patients, role):
        text(x, 26, title, "heading")
        text(x, 48, f"{busy} / {capacity}", attributes=f'data-count="{role}"')
        for i in range(capacity):
            y = 66 + i * 48
            svg.append(f'<g data-role="{role}-post" data-occupied="{str(i < busy).lower()}">')
            svg.append(
                f'<rect x="{x}" y="{y}" width="125" height="38" rx="4" '
                'fill="#f4f6f8" stroke="#8795a1"/>'
            )
            if i < min(busy, capacity) and i < len(patients):
                patient(patients[i], x + 3, y + 3, 119, 32)
            else:
                text(x + 4, y + 22, "Ocupado" if i < busy else "Libre")
            svg.append("</g>")
        for i in range(max(0, busy - capacity)):
            y = 66 + (capacity + i) * 48
            svg.append(
                f'<g data-role="{role}-finishing">'
                "<title>Al bajar la plantilla nadie se interrumpe: termina la "
                "atención y el puesto desaparece (decisión 0026).</title>"
            )
            text(x, y + 10, "Terminando atención")
            if capacity + i < len(patients):
                patient(patients[capacity + i], x, y + 14, 125, 28)
            svg.append("</g>")

    queue(waiting_triage, 14, "Cola de triaje", counts.waiting_triage, "triage")
    staff(
        210,
        "Triaje",
        counts.nurses_busy,
        counts.nurses_staff,
        sorted((p for p in state.patients if p.state == "triage"), key=lambda p: p.arrival),
        "nurses",
    )
    queue(waiting_box, 350, "Cola de box", counts.waiting_box, "box")
    text(545, 26, "Boxes", "heading")
    text(545, 48, f"{counts.boxes_busy} / {counts.boxes}", attributes='data-count="boxes"')
    boxes = {p.box: p for p in state.patients if p.box is not None}
    for number in range(1, counts.boxes + 1):
        x, y = 545 + ((number - 1) % 4) * 105, 66 + ((number - 1) // 4) * 76
        svg.append(f'<g data-role="box" data-box="{number}">')
        displaced = tuple(d for d in recent if d.box == number)
        mark = ' data-mark="displaced-box" stroke-dasharray="6 4"' if displaced else ""
        svg.append(
            f'<rect x="{x}" y="{y}" width="98" height="68" fill="#f4f6f8" '
            f'stroke="#795548" stroke-width="2"{mark}/>'
        )
        text(x + 4, y + 14, f"Box {number}")
        if displaced:
            svg.append(title_for(displaced))
        if number in boxes:
            p = boxes[number]
            patient(p, x + 4, y + 18, 90, 46, label=p.episode_id.removeprefix("EP-"))
        else:
            text(x + 4, y + 40, "Libre")
        svg.append("</g>")
    staff(
        980,
        "Médicos",
        counts.doctors_busy,
        counts.doctors_staff,
        sorted(
            (p for p in state.patients if p.state in ("assessment", "reassessment")),
            key=lambda p: p.arrival,
        ),
        "doctors",
    )
    text(1130, 26, "Salidas · última hora", "heading")
    for i, destination in enumerate(("alta", "ingreso")):
        text(
            1130,
            66 + i * 32,
            f"{destination.capitalize()}: {state.departures_by_destination[destination]}",
        )
    text(
        14,
        height - 37,
        "Borde discontinuo: desalojo aquí · Contorno rojo: paciente desalojado (últimos 60 min)",
    )
    text(
        14,
        height - 15,
        "Violeta: paciente seleccionado · Ocupados / plantilla puede superar 1; "
        "nadie se interrumpe.",
    )
    svg.append("</svg>")
    return "".join(svg)
