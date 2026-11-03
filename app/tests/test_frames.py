"""Check catalog values and formatting without running Streamlit."""

from dataclasses import replace

from pandas.api.types import is_numeric_dtype

from edsim_app.frames import runs_frame, style_runs


def test_run_table_columns_values_and_fixed_timezone(run_info):
    frame = runs_frame([run_info])
    assert frame.to_dict("records") == [
        {
            "Ejecución": "example",
            "Variante del centro": "base",
            "Fecha de creación": "04/07/2026 00:30:00",
            "Días": 4,
            "Calentamiento (días)": 2,
            "Semilla": 2026,
            "Huella del centro": "12345678",
            "Llegadas por día": 307.5,
            "Invariantes": "correctas",
            "Origen": "CLI",
        }
    ]


def test_table_preserves_input_order_and_describes_violations(run_info):
    second = replace(run_info, run_id="second", invariant_violations=3, origin="app")
    frame = runs_frame([second, run_info])
    assert frame["Ejecución"].tolist() == ["second", "example"]
    assert frame["Invariantes"].tolist() == ["3 violaciones", "correctas"]
    assert frame["Origen"].tolist() == ["app", "CLI"]


def test_empty_table_keeps_all_headers():
    frame = runs_frame([])
    assert frame.empty
    assert list(frame.columns) == [
        "Ejecución",
        "Variante del centro",
        "Fecha de creación",
        "Días",
        "Calentamiento (días)",
        "Semilla",
        "Huella del centro",
        "Llegadas por día",
        "Invariantes",
        "Origen",
    ]


def test_decimal_comma_does_not_turn_numbers_into_strings(run_info):
    frame = runs_frame([run_info])
    styled = style_runs(frame)
    assert "307,5" in styled.to_html()
    assert is_numeric_dtype(styled.data["Llegadas por día"])
    assert styled.data.loc[0, "Llegadas por día"] == 307.5
