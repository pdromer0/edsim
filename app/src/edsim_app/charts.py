"""Declarative charts from public core results and presentation tables."""

import altair as alt
import pandas as pd

from edsim.runs import DurationSummary


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
