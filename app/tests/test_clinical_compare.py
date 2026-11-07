"""Show verified staffing and clinical pairs without treating profiles as blockers."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import edsim_app
from edsim.runs import (
    RunStore,
    compare_runs,
    pairing_category,
    read_run_episode_truth,
    read_run_results,
)
from edsim_app.comparison_frames import CLINICAL_LABELS

pytestmark = pytest.mark.slow
MAIN = Path(edsim_app.__file__).with_name("main.py")


def open_compare(a, b):
    app = AppTest.from_file(MAIN)
    app.session_state["compare_a"] = a
    app.session_state["compare_b"] = b
    app.run().switch_page("views/compare.py").run()
    assert app.title[0].value == "Comparar" and not app.exception and not app.error
    return app


@pytest.mark.parametrize(
    "b,category", [("staff", "template"), ("flu", "clinical"), ("clinical", "template")]
)
def test_pairing_category_and_clinical_changes_match_core(clinical_catalog, b, category):
    store = RunStore(clinical_catalog)
    a_result, b_result = read_run_results(store, "clinical"), read_run_results(store, b)
    assert pairing_category(a_result, b_result) == category
    expected = compare_runs(
        a_result,
        b_result,
        read_run_episode_truth(store, "clinical"),
        read_run_episode_truth(store, b),
    )
    app = open_compare("clinical", b)
    captions = " ".join(t.value for t in app.caption)
    assert (
        "Clínico · mismos sorteos estándar"
        if category == "clinical"
        else "Plantilla · mismos pacientes"
    ) in captions
    assert any(t.value == "Paciente a paciente" for t in app.subheader)
    frame = next(t.value for t in app.dataframe if "Campo clínico" in t.value)
    assert frame.to_dict("records") == [
        {
            "Campo clínico": CLINICAL_LABELS[d.field],
            "Pacientes distintos": d.changed,
            "Total": d.total,
        }
        for d in expected.pairing.clinical_differences
    ]
    if category == "clinical":
        assert (
            next(d.changed for d in expected.pairing.clinical_differences if d.field == "reason")
            > 0
        )
        metadata = next(t.value for t in app.dataframe if "Campo" in t.value).set_index("Campo")
        for field in ("Ruta de perfiles clínicos", "Huella de perfiles clínicos"):
            assert metadata.loc[field, "A"] != metadata.loc[field, "B"]
    else:
        assert frame["Pacientes distintos"].sum() == 0


def test_models_are_unpaired_and_only_summary_is_displayed(clinical_catalog):
    app = open_compare("clinical", "provisional")
    assert any("Sin emparejar" in t.value for t in app.caption)
    assert any("Modelo" in t.value for t in app.info)
    assert any("Cambio relativo" in t.value for t in app.dataframe)
    assert not any("Campo clínico" in t.value for t in app.dataframe)
    assert not any(t.value == "Paciente a paciente" for t in app.subheader)


def test_absurd_clinical_center_does_not_show_irrelevant_center_changes(clinical_catalog):
    app = open_compare("clinical", "absurd")
    assert not any("Clave del centro" in t.value for t in app.dataframe)
    frame = next(t.value for t in app.dataframe if "Campo clínico" in t.value)
    assert frame["Pacientes distintos"].sum() == 0


@pytest.mark.parametrize("run_id", ["provisional", "legacy"])
def test_provisional_and_legacy_self_comparisons_remain_available(clinical_catalog, run_id):
    app = open_compare(run_id, run_id)
    assert len(app.metric) == 6
    assert all("100,0 %" in m.value for m in app.metric if "Iguales" in m.label)
    assert any("Plantilla" in t.value for t in app.caption)
