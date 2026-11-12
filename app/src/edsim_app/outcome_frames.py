"""Present the outcome of milestone 5 (abandonment, destinations, beds) as Spanish tables.

Every figure comes from ``edsim.runs``; these functions only label and format.
A ``CensoredValue`` that is not exact is a lower bound and is shown as «≥ value».
"""

from collections.abc import Sequence

import pandas as pd

from edsim.runs import (
    CensoredValue,
    OutcomeTruthView,
    OverThreshold,
    TrueLevelAbandonment,
    WindowCompliance,
    WindowOutcome,
)
from edsim_app.frames import format_number

DESTINATION_LABELS = {
    "alta": "Alta",
    "ingreso": "Ingreso",
    "traslado": "Traslado",
    "exitus": "Exitus",
}
WAIT_LABELS = {
    "triaje": "Esperando el triaje",
    "box": "Esperando box",
    "medico": "Esperando médico en el box",
}
OUTCOME_CURVE_LABELS = {
    "boxes_waiting_bed": "Boxes con ingresados esperando cama",
    "hallway": "Pacientes en el pasillo",
}


def format_censored(value: CensoredValue | None, digits: int = 1) -> str:
    """«—» without patients; «≥ value» for a lower bound; the plain value if exact."""
    if value is None or value.value is None:
        return "—"
    number = format_number(value.value, digits)
    return number if value.exact else f"≥ {number}"


def format_share(value: float | None) -> str:
    return format_number(value, percentage=True)


def threshold_frame(thresholds: Sequence[OverThreshold]) -> pd.DataFrame:
    """Shares over each threshold among the known ones, and the unknown apart."""
    return pd.DataFrame(
        [
            {
                "Umbral (h)": format_number(t.minutes / 60, 0),
                "Por encima": t.over,
                "Conocidos": t.known,
                "Sin saber": t.unknown,
                "Porcentaje (por encima / conocidos)": format_share(t.share),
            }
            for t in thresholds
        ],
        columns=[
            "Umbral (h)",
            "Por encima",
            "Conocidos",
            "Sin saber",
            "Porcentaje (por encima / conocidos)",
        ],
    )


def left_frames(outcome: WindowOutcome) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Abandonment over the arrivals, by place (counts) and by assigned level."""
    left = outcome.left
    overall = pd.DataFrame(
        [
            ("Se van sin ser vistos", left.left, format_share(left.share)),
            ("Antes del triaje", left.before_triage, format_share(left.before_triage_share)),
            ("Después del triaje", left.after_triage, format_share(left.after_triage_share)),
        ],
        columns=["Abandono", "Pacientes", "Sobre las llegadas"],
    )
    by_wait = pd.DataFrame(
        [(WAIT_LABELS[wait], count) for wait, count in left.by_wait.items()],
        columns=["Desde", "Pacientes"],
    )
    by_level = pd.DataFrame(
        [
            {
                "Nivel asignado": level.level,
                "Clasificados": level.classified,
                "Se van": level.count,
                "Sobre los clasificados": format_share(level.share),
            }
            for level in left.by_level
        ],
        columns=["Nivel asignado", "Clasificados", "Se van", "Sobre los clasificados"],
    )
    return overall, by_wait, by_level


def destination_frames(outcome: WindowOutcome) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Destinations over the arrivals, and by assigned level over its classified."""
    shares = outcome.destinations
    overall = pd.DataFrame(
        [
            {
                "Destino": label,
                "Pacientes": shares.counts[key],
                "Sobre las llegadas": format_share(shares.share(key)),
            }
            for key, label in DESTINATION_LABELS.items()
        ],
        columns=["Destino", "Pacientes", "Sobre las llegadas"],
    )
    by_level = pd.DataFrame(
        [
            {"Nivel asignado": level.level, "Clasificados": level.classified}
            | {label: format_share(level.share(key)) for key, label in DESTINATION_LABELS.items()}
            for level in shares.by_level
        ],
        columns=["Nivel asignado", "Clasificados", *DESTINATION_LABELS.values()],
    )
    return overall, by_level


def stay_frame(outcome: WindowOutcome) -> pd.DataFrame:
    """Stay by destination, and the time until leaving of those who left, apart."""
    stay = outcome.stay
    rows = [(DESTINATION_LABELS[key], summary) for key, summary in stay.by_destination.items()] + [
        ("Se van sin ser vistos (hasta irse)", stay.left)
    ]
    return pd.DataFrame(
        [
            {
                "Grupo": label,
                "n": summary.n,
                "Siguen dentro": summary.censored,
                "Media (min)": format_censored(summary.mean),
                "Mediana (min)": format_censored(summary.median),
                "p90 (min)": format_censored(summary.p90),
            }
            for label, summary in rows
        ],
        columns=["Grupo", "n", "Siguen dentro", "Media (min)", "Mediana (min)", "p90 (min)"],
    )


def outcome_truth_frame(view: OutcomeTruthView) -> pd.DataFrame:
    """What the outcome sampler drew for one episode next to what its log shows."""

    def minutes(value: float | None) -> str:
        return "—" if value is None else f"{format_number(value)} min"

    rows = [
        ("Paciencia", minutes(view.patience)),
        ("z de la paciencia", format_number(view.patience_z, 3)),
        ("Plazo (minuto de la ejecución)", format_number(view.deadline)),
        ("Abandono esperado (minuto)", format_number(view.expected_leave)),
        ("Abandono observado (minuto)", format_number(view.left_at)),
        ("Desde", WAIT_LABELS.get(view.left_from, "—")),
        ("Destino sorteado", DESTINATION_LABELS[view.destination]),
        ("Destino observado", DESTINATION_LABELS.get(view.destination_observed, "—")),
        (
            "Contrafactual",
            "Sí: se fue sin ser visto; es el destino que habría tenido"
            if view.counterfactual
            else "No",
        ),
        ("Espera de cama base (factor 1)", minutes(view.bed_base)),
        ("z de la espera de cama", format_number(view.bed_z, 3)),
        ("Factor del pedido (turno × estación)", format_number(view.bed_factor, 2)),
        ("Espera de cama esperada", minutes(view.bed_expected)),
        ("Espera de cama observada", minutes(view.bed_observed)),
    ]
    return pd.DataFrame(rows, columns=["Dato", "Valor"])


def true_level_compliance_frame(compliance: WindowCompliance) -> pd.DataFrame:
    """Manchester compliance grouped by the true level of the ground truth."""
    return pd.DataFrame(
        [
            {
                "Nivel real": level.level,
                "n": level.n,
                "Máximo Manchester (min)": format_number(level.max_wait, 0),
                "Superan el máximo": level.exceeded,
                "Porcentaje que lo supera": format_share(level.exceeded_share),
                "Se van después del máximo": level.left_late,
                "Censurados (se van antes)": level.censored,
            }
            for level in compliance.by_level
        ]
    )


def true_level_abandonment_frames(value: TrueLevelAbandonment) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Abandonment by true level, and the hidden harm: severe and would-be admitted."""
    by_level = pd.DataFrame(
        [
            {
                "Nivel real": level.level,
                "Llegadas": level.arrivals,
                "Se van": level.left,
                "Porcentaje": format_share(level.share),
            }
            for level in value.by_level
        ],
        columns=["Nivel real", "Llegadas", "Se van", "Porcentaje"],
    )
    harm = pd.DataFrame(
        [
            ("Se van sin ser vistos", value.left),
            ("Graves de verdad (nivel real 1 o 2)", value.severe),
            ("Habrían ingresado (destino sorteado)", value.would_be_admitted),
        ],
        columns=["Grupo", "Pacientes"],
    )
    return by_level, harm
