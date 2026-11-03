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
