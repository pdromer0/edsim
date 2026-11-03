"""Register and run the six pages of the local app."""

import streamlit as st

page = st.navigation(
    {
        "Ejecutar": [
            st.Page("pages/runs.py", title="Ejecuciones", url_path="ejecuciones", default=True),
            st.Page("pages/simulate.py", title="Simular", url_path="simular"),
        ],
        "Analizar": [
            st.Page("pages/results.py", title="Resultados", url_path="resultados"),
            st.Page("pages/episodes.py", title="Episodios", url_path="episodios"),
            st.Page("pages/compare.py", title="Comparar", url_path="comparar"),
            st.Page("pages/replay.py", title="Replay", url_path="replay"),
        ],
    }
)
page.run()
