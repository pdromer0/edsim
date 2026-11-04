"""Register and run the six pages of the local app."""

import streamlit as st

from edsim_app.replay import pause_replays_except
from edsim_app.state import catalog_store, initialize_state, render_sidebar

initialize_state(catalog_store())

page = st.navigation(
    {
        "Ejecutar": [
            st.Page("views/runs.py", title="Ejecuciones", url_path="ejecuciones", default=True),
            st.Page("views/simulate.py", title="Simular", url_path="simular"),
        ],
        "Analizar": [
            st.Page("views/results.py", title="Resultados", url_path="resultados"),
            st.Page("views/episodes.py", title="Episodios", url_path="episodios"),
            st.Page("views/compare.py", title="Comparar", url_path="comparar"),
            st.Page("views/replay.py", title="Replay", url_path="replay"),
        ],
    }
)
pause_replays_except(st.session_state.selected_run_id if page.url_path == "replay" else None)
render_sidebar()
page.run()
