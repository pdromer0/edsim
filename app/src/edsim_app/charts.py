"""Declarative charts from public core results and presentation tables."""

import altair as alt
import pandas as pd

from edsim.runs import DurationSummary
from edsim_app.palette import LEVEL_COLORS


def duration_chart(duration: DurationSummary) -> alt.Chart:
    """Render the supplied lognormal density without calculating it again."""
    frame = pd.DataFrame({"Minutos": duration.curve_minutes, "Densidad": duration.curve_density})
    return (
        alt.Chart(frame)
        .mark_line()
        .encode(x=alt.X("Minutos:Q"), y=alt.Y("Densidad:Q"))
        .properties(height=110)
    )


def offered_chart(frame: pd.DataFrame) -> alt.Chart:
    """Compare mean offered load with scheduled capacity on the same scale."""
    tidy = frame.melt("Fecha y hora", var_name="Serie", value_name="Recursos")
    return (
        alt.Chart(tidy)
        .mark_line(interpolate="step-after")
        .encode(
            x=alt.X("Fecha y hora:T", title="Fecha y hora (UTC+1)"),
            y=alt.Y("Recursos:Q", title="Recursos ocupados / disponibles"),
            color=alt.Color(
                "Serie:N",
                scale=alt.Scale(
                    domain=["Carga ofrecida", "Capacidad"], range=["#2a78d6", "#eb6834"]
                ),
            ),
            tooltip=[alt.Tooltip("Fecha y hora:T", format="%d/%m %H:%M"), "Serie:N", "Recursos:Q"],
        )
        .properties(height=260)
        .interactive()
    )


def waits_chart(frame: pd.DataFrame) -> alt.Chart:
    """Compare door-to-doctor means and p90 with each level's Manchester maximum."""
    clock = (
        "Desde la clasificación (C)"
        if "Desde la clasificación (C) media (min)" in frame
        else "Puerta-médico"
    )
    tidy = (
        frame[
            [
                "Nivel",
                f"{clock} media (min)",
                f"{clock} p90 (min)",
                "Máximo Manchester (min)",
            ]
        ]
        .rename(
            columns={
                f"{clock} media (min)": "Media",
                f"{clock} p90 (min)": "p90",
                "Máximo Manchester (min)": "Máximo Manchester",
            }
        )
        .melt("Nivel", var_name="Serie", value_name="Minutos")
    )
    return (
        alt.Chart(tidy)
        .mark_point(size=85)
        .encode(
            x=alt.X("Nivel:O"),
            y=alt.Y("Minutos:Q"),
            color=alt.Color(
                "Nivel:O",
                scale=alt.Scale(domain=list(LEVEL_COLORS), range=list(LEVEL_COLORS.values())),
            ),
            shape="Serie:N",
            tooltip=["Nivel:O", "Serie:N", alt.Tooltip("Minutos:Q", format=".1f")],
        )
        .properties(height=260)
    )


def occupancy_chart(frame: pd.DataFrame) -> alt.LayerChart:
    """Render nine occupancy ratios without clipping the color scale at one."""
    base = alt.Chart(frame).encode(
        x=alt.X("Turno:N", sort=["Mañana", "Tarde", "Noche"]),
        y=alt.Y("Recurso:N", sort=["Enfermería de triaje", "Médicos", "Boxes"]),
        tooltip=["Recurso:N", "Turno:N", "Etiqueta:N"],
    )
    upper = max(1.0, float(frame["Ocupación"].max()))
    cells = base.mark_rect().encode(
        color=alt.Color("Ocupación:Q", scale=alt.Scale(domain=[0, upper], scheme="blues"))
    )
    text = base.mark_text().encode(
        text="Etiqueta:N",
        color=alt.condition(
            alt.datum["Ocupación"] > 0.6 * upper, alt.value("white"), alt.value("black")
        ),
    )
    return (cells + text).properties(height=180)


def curve_chart(frame: pd.DataFrame, warmup_end: pd.Timestamp) -> alt.LayerChart:
    """Draw block means/maxima and exact resource steps with clipped warmup shading."""
    names = frame["Serie"].drop_duplicates().tolist()
    palette = {
        "Media": "#2a78d6",
        "Máximo": "#eb6834",
        "Plantilla vigente": "#1baf7a",
        "Boxes": "#1baf7a",
    }
    lines = (
        alt.Chart(frame)
        .mark_line(interpolate="step-after")
        .encode(
            x=alt.X("Fecha y hora:T", title="Fecha y hora (UTC+1)"),
            y=alt.Y("Valor:Q", title="Pacientes / recursos"),
            color=alt.Color(
                "Serie:N", scale=alt.Scale(domain=names, range=[palette[name] for name in names])
            ),
            tooltip=[
                alt.Tooltip("Fecha y hora:T", format="%d/%m %H:%M"),
                "Serie:N",
                alt.Tooltip("Valor:Q", format=".2f"),
            ],
        )
    )
    start, end = frame["Fecha y hora"].min(), frame["Fecha y hora"].max()
    layers = []
    if warmup_end > start:
        shade = pd.DataFrame({"Inicio": [start], "Fin": [min(warmup_end, end)]})
        layers.append(
            alt.Chart(shade)
            .mark_rect(color="#888888", opacity=0.15)
            .encode(x="Inicio:T", x2="Fin:T")
        )
    return alt.layer(*layers, lines).properties(height=280).interactive()


def hourly_census_chart(frame: pd.DataFrame) -> alt.Chart:
    """Plot the core's mean census by clock hour within the observation window."""
    return (
        alt.Chart(frame)
        .mark_line(point=True)
        .encode(
            x=alt.X(
                "Hora del día:Q", scale=alt.Scale(domain=[0, 23]), axis=alt.Axis(tickMinStep=1)
            ),
            y=alt.Y("Censo medio:Q"),
            tooltip=["Hora del día:Q", "Censo medio:Q"],
        )
        .properties(height=230)
    )


def episode_chart(
    segments: pd.DataFrame, tests: pd.DataFrame, displacements: pd.DataFrame
) -> alt.LayerChart:
    """Draw physical states, independent lab work and displacement diamonds."""
    # Building a fresh frame keeps shared core results and caller frames untouched.
    intervals = pd.concat([segments, tests], ignore_index=True)
    bars = (
        alt.Chart(intervals)
        .mark_bar(size=26)
        .encode(
            x=alt.X("Inicio:T", title="Fecha y hora (UTC+1)"),
            x2="Fin:T",
            y=alt.Y("Carril:N", sort=["Recorrido", "Pruebas"], title=None),
            color=alt.Color(
                "Estado:N",
                scale=alt.Scale(
                    domain=[
                        "Espera de triaje",
                        "Triaje",
                        "Espera de box",
                        "En box esperando médico",
                        "Valoración",
                        "En box esperando pruebas",
                        "Reevaluación",
                        "Pruebas en curso",
                    ],
                    range=[
                        "#b6cde4",
                        "#2a78d6",
                        "#efc394",
                        "#e7a15b",
                        "#1baf7a",
                        "#c7b8db",
                        "#7966a3",
                        "#898781",
                    ],
                ),
            ),
            tooltip=[
                "Estado:N",
                "Box:O",
                alt.Tooltip("Inicio:T", format="%d/%m/%Y %H:%M:%S"),
                alt.Tooltip("Fin:T", format="%d/%m/%Y %H:%M:%S"),
                alt.Tooltip("Duración (min):Q", format=".2f"),
            ],
        )
    )
    points = (
        alt.Chart(displacements)
        .mark_point(shape="diamond", size=130, filled=True, color="#b00020")
        .encode(
            x="Fecha y hora:T",
            y=alt.Y("Carril:N", sort=["Recorrido", "Pruebas"]),
            tooltip=[
                alt.Tooltip("Fecha y hora:T", format="%d/%m/%Y %H:%M:%S"),
                "Box:O",
                "Desalojado por:N",
            ],
        )
    )
    return (bars + points).properties(height=160).interactive()


def difference_histogram_chart(frame: pd.DataFrame) -> alt.Chart:
    """Draw core-supplied intervals and counts of patients with a nonzero change."""
    return (
        alt.Chart(frame)
        .mark_bar(binSpacing=1)
        .encode(
            x=alt.X("Desde (min):Q", title="B − A (minutos)", bin="binned"),
            x2="Hasta (min):Q",
            y=alt.Y("Pacientes:Q", title="Pacientes que cambian"),
            color=alt.Color(
                "Efecto:N",
                scale=alt.Scale(domain=["Mejoran", "Empeoran"], range=["#1baf7a", "#b00020"]),
            ),
            tooltip=[
                alt.Tooltip("Desde (min):Q", format=".2f"),
                alt.Tooltip("Hasta (min):Q", format=".2f"),
                "Pacientes:Q",
                "Efecto:N",
            ],
        )
        .properties(height=240)
    )


def replay_census_chart(frame: pd.DataFrame, minute: pd.Timestamp) -> alt.LayerChart:
    """Show exact daily census steps and a timezone-free selected instant."""
    line = (
        alt.Chart(frame)
        .mark_line(interpolate="step-after")
        .encode(
            x=alt.X("Fecha y hora:T", title="Fecha y hora (UTC+1)"),
            y=alt.Y("Censo:Q"),
            tooltip=[alt.Tooltip("Fecha y hora:T", format="%d/%m %H:%M:%S"), "Censo:Q"],
        )
    )
    marker = (
        alt.Chart(pd.DataFrame({"Instante": [minute]}))
        .mark_rule(color="#6a1b9a", strokeWidth=2)
        .encode(x="Instante:T")
    )
    return (line + marker).properties(height=230)
