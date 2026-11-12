"""Las diferencias de los perfiles clínicos de dos ejecuciones, clave a clave (tarea 5.5).

Comparar enseñaba solo que las huellas de los perfiles eran distintas (pendiente del hito 4):
`profiles_diff` dice qué valores cambian.
"""

import tomllib
from pathlib import Path

import pytest
import tomlkit

from edsim.runs import (
    RunReadError,
    RunStore,
    profiles_diff,
    read_run_profiles_values,
    simulate_run,
)

DATA = Path(__file__).parent / "data"


def test_las_diferencias_a_mano():
    a = {"a": {"x": 1, "y": [1, 2]}, "b": {"z": "s"}}
    b = {"a": {"x": 1, "y": [1, 3]}, "c": {"w": 2}}
    found = [(d.key, d.a, d.b) for d in profiles_diff(a, b)]
    # En el orden de a y después lo que solo está en b; a.x no cambia y no sale.
    assert found == [("a.y", (1, 2), (1, 3)), ("b.z", "s", None), ("c.w", None, 2)]


def test_unos_perfiles_frente_a_si_mismos_no_cambian():
    values = tomllib.loads((DATA / "perfiles_ejemplo.toml").read_text(encoding="utf-8"))
    assert profiles_diff(values, values) == ()


def test_un_peso_cambiado_es_una_sola_diferencia():
    text = (DATA / "perfiles_ejemplo.toml").read_text(encoding="utf-8")
    document = tomlkit.parse(text)
    weight = document["motivos"]["disnea"]["peso_base"]
    document["motivos"]["disnea"]["peso_base"] = weight * 1.5
    found = profiles_diff(tomllib.loads(text), tomllib.loads(tomlkit.dumps(document)))
    assert [(d.key, d.a, d.b) for d in found] == [
        ("motivos.disnea.peso_base", weight, weight * 1.5)
    ]


def test_lee_la_copia_de_la_ejecucion(tmp_path):
    for run_id, profiles in (("clinica", DATA / "perfiles_ejemplo.toml"), ("provisional", None)):
        simulate_run(
            DATA / "centro_ejemplo.toml",
            DATA / "llegadas_ejemplo.toml",
            1,
            7,
            output_dir=tmp_path / run_id,
            run_id=run_id,
            warmup_days=0,
            origin="cli",
            profiles=profiles,
        )
    store = RunStore(tmp_path)
    expected = tomllib.loads((DATA / "perfiles_ejemplo.toml").read_text(encoding="utf-8"))
    assert read_run_profiles_values(store, "clinica") == expected
    with pytest.raises(RunReadError, match="perfiles.toml"):
        read_run_profiles_values(store, "provisional")
