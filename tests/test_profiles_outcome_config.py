"""El bloque del hito 5 en ``perfiles.toml``: ``[abandono]``, ``[destinos]`` e ``ingreso``.

Todo o nada (decisión 68, H5-2): sin el bloque, los perfiles del hito 4 tal cual; con él,
las tres partes; a medias, un error que nombra lo que falta con la clave completa. Los
porcentajes van en (0, 100), los odds ratios son positivos y, en cada motivo, ``ingreso``
más las bases del traslado y del exitus queda por debajo de 100.
"""

import re
from dataclasses import replace
from pathlib import Path

import pytest

from edsim.profiles.config import (
    REASON_KEYS,
    Abandonment,
    DestinationOdds,
    load_profiles,
)

DATA = Path(__file__).parent / "data"

ABANDONMENT = """
[abandono]
paciencia = [[1440, 4320], [480, 1440], [240, 720], [150, 450], [120, 360]]
paciencia_edad = [0.8, 1.0, 1.0, 1.0]
"""
DESTINATIONS = """
[destinos]
ingreso = { objetivo = 9.90, or_gravedad = 1.5, or_mayor = 1.5, or_alterada = 1.5 }
traslado = { objetivo = 0.75, base = 0.7639, or_gravedad = 1.5 }
exitus = { objetivo = 0.11, base = 0.001937, or_gravedad = 15.0 }
"""


def example_text() -> str:
    return (DATA / "perfiles_ejemplo.toml").read_text(encoding="utf-8")


def with_admission(text: str, pct: dict[str, float]) -> str:
    """Añade ``ingreso`` justo debajo de la cabecera de cada motivo de ``pct``."""
    for key, value in pct.items():
        header = f"[motivos.{key}]\n"
        assert text.count(header) == 1
        text = text.replace(header, f"{header}ingreso = {value}\n")
    return text


ALL = dict.fromkeys(REASON_KEYS, 2.0) | {"parada": 30.66}


def block_text(abandonment: str = ABANDONMENT, destinations: str = DESTINATIONS, pct=None) -> str:
    return with_admission(example_text(), ALL if pct is None else pct) + abandonment + destinations


def write(tmp_path, text: str) -> Path:
    path = tmp_path / "perfiles.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_sin_bloque_los_perfiles_del_hito_4():
    profiles = load_profiles(DATA / "perfiles_ejemplo.toml")
    assert profiles.outcome is None
    assert all(r.admission_pct is None for r in profiles.reasons)


def test_el_bloque_entero_se_lee(tmp_path):
    profiles = load_profiles(write(tmp_path, block_text()))
    outcome = profiles.outcome
    assert outcome.abandonment.patience[4] == (120.0, 360.0)
    assert outcome.abandonment.age_factors == (0.8, 1.0, 1.0, 1.0)
    assert outcome.admission == DestinationOdds("ingreso", 9.90, 1.5, 1.5, 1.5)
    assert outcome.transfer == DestinationOdds("traslado", 0.75, 1.5, base=0.7639)
    assert outcome.death == DestinationOdds("exitus", 0.11, 15.0, base=0.001937)
    assert [d.key for d in outcome.destinations] == ["ingreso", "traslado", "exitus"]
    assert profiles.reason("parada").admission_pct == 30.66
    assert profiles.reason("orl").admission_pct == 2.0


def test_los_odds_ratios_opcionales_valen_uno_y_la_edad_tambien(tmp_path):
    destinations = DESTINATIONS.replace(", or_mayor = 1.5, or_alterada = 1.5", "")
    abandonment = ABANDONMENT.replace("paciencia_edad = [0.8, 1.0, 1.0, 1.0]\n", "")
    outcome = load_profiles(write(tmp_path, block_text(abandonment, destinations))).outcome
    assert (outcome.admission.older_or, outcome.admission.abnormal_or) == (1.0, 1.0)
    assert outcome.abandonment.age_factors == (1.0, 1.0, 1.0, 1.0)


@pytest.mark.parametrize(
    ("abandonment", "destinations", "pct", "missing"),
    [
        (ABANDONMENT, "", None, "destinos"),
        ("", DESTINATIONS, None, "abandono"),
        ("", "", None, "abandono, destinos"),
        (ABANDONMENT, DESTINATIONS, {}, ", ".join(f"motivos.{k}.ingreso" for k in REASON_KEYS)),
        (
            ABANDONMENT,
            DESTINATIONS,
            {k: 2.0 for k in REASON_KEYS if k != "parada"},
            "motivos.parada.ingreso",
        ),
        (
            "",
            "",
            {"orl": 1.0},
            "abandono, destinos, "
            + ", ".join(f"motivos.{k}.ingreso" for k in REASON_KEYS if k != "orl"),
        ),
    ],
    ids=["sin-destinos", "sin-abandono", "solo-ingreso", "sin-ingreso", "falta-uno", "uno-solo"],
)
def test_un_bloque_a_medias_es_un_error(tmp_path, abandonment, destinations, pct, missing):
    path = write(tmp_path, block_text(abandonment, destinations, pct))
    message = f"the milestone 5 block comes whole or not at all: missing keys: {missing}"
    with pytest.raises(ValueError, match=re.escape(message) + "$"):
        load_profiles(path)


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        (
            "traslado = { objetivo = 0.75, base = 0.7639,",
            "traslado = { objetivo = 0.75,",
            r"missing keys: destinos\.traslado\.base",
        ),
        (
            "ingreso = { objetivo = 9.90,",
            "ingreso = { objetivo = 9.90, base = 6.0,",
            r"unknown keys: destinos\.ingreso\.base",
        ),
        (
            "exitus = { objetivo = 0.11, base = 0.001937, or_gravedad = 15.0 }",
            "exitus = { objetivo = 0.11, base = 0.001937 }",
            r"missing keys: destinos\.exitus\.or_gravedad",
        ),
        (
            "traslado = { objetivo = 0.75,",
            "traslado = { objetivo = 0.75, or_edad = 2,",
            r"unknown keys: destinos\.traslado\.or_edad",
        ),
        (
            "exitus = {",
            "exito = {",
            r"missing keys: destinos\.exitus; unknown keys: destinos\.exito",
        ),
    ],
)
def test_claves_de_destinos(tmp_path, old, new, message):
    path = write(tmp_path, block_text(destinations=DESTINATIONS.replace(old, new)))
    with pytest.raises(ValueError, match=message):
        load_profiles(path)


def test_una_clave_desconocida_en_abandono(tmp_path):
    path = write(tmp_path, block_text(abandonment=ABANDONMENT + "paciencias = 3\n"))
    with pytest.raises(ValueError, match=r"unknown keys: abandono\.paciencias"):
        load_profiles(path)


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("[120, 360]]", "[120, 360], [100, 300]]", r"abandono\.paciencia must have 5 values"),
        ("[120, 360]]", "[120, 360, 400]]", r"abandono\.paciencia\[4\] must have 2 values"),
        (
            "[120, 360]]",
            "[360, 120]]",
            r"abandono\.paciencia\[4\]\[1\] \(the p90\) must be greater",
        ),
        ("[120, 360]]", "[nan, 360]]", r"abandono\.paciencia\[4\]\[0\] must be a finite number"),
        ("[120, 360]]", f"[120, {10**400}]]", r"abandono\.paciencia\[4\]\[1\] must be a finite"),
        ("[1440, 4320],", "[0, 4320],", r"abandono\.paciencia\[0\]\[0\] \(the median\) must be"),
        ("[0.8, 1.0, 1.0, 1.0]", "[0.8, 1.0, 1.0]", r"abandono\.paciencia_edad must have 4"),
        ("[0.8, 1.0, 1.0, 1.0]", "[0.8, 0, 1.0, 1.0]", r"abandono\.paciencia_edad\[1\] must be"),
        ("paciencia = [[1440", "paciencia = [] #", r"abandono\.paciencia must have 5 values"),
    ],
)
def test_valores_de_abandono(tmp_path, old, new, message):
    path = write(tmp_path, block_text(abandonment=ABANDONMENT.replace(old, new)))
    with pytest.raises(ValueError, match=message):
        load_profiles(path)


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("objetivo = 9.90", "objetivo = 100", r"destinos\.ingreso\.objetivo must be between 0"),
        ("objetivo = 0.11", "objetivo = 0", r"destinos\.exitus\.objetivo must be between 0"),
        ("base = 0.7639", "base = inf", r"destinos\.traslado\.base must be a finite number"),
        ("or_gravedad = 15.0", "or_gravedad = inf", r"exitus\.or_gravedad must be a finite"),
        (
            "or_gravedad = 15.0",
            "or_gravedad = 0",
            r"destinos\.exitus\.or_gravedad must be positive",
        ),
        ("or_alterada = 1.5", "or_alterada = -1", r"destinos\.ingreso\.or_alterada must be pos"),
        ("or_mayor = 1.5", f"or_mayor = {10**400}", r"destinos\.ingreso\.or_mayor must be a fin"),
    ],
)
def test_valores_de_destinos(tmp_path, old, new, message):
    path = write(tmp_path, block_text(destinations=DESTINATIONS.replace(old, new)))
    with pytest.raises(ValueError, match=message):
        load_profiles(path)


@pytest.mark.parametrize("value", [0, 100, "nan"])
def test_el_ingreso_de_un_motivo_va_en_el_intervalo_abierto(tmp_path, value):
    path = write(tmp_path, block_text(pct=ALL | {"orl": value}))
    with pytest.raises(ValueError, match=r"motivos\.orl\.ingreso must be"):
        load_profiles(path)


def test_ingreso_mas_las_bases_por_debajo_de_100(tmp_path):
    # El límite es 100 − 0,7639 − 0,001937 = 99,234163.
    # 99,2342 + 0,7639 + 0,001937 = 100,000037: llega a 100.
    path = write(tmp_path, block_text(pct=ALL | {"parada": 99.2342}))
    with pytest.raises(ValueError, match=r"motivos\.parada\.ingreso \+ destinos\.traslado\.base"):
        load_profiles(path)
    # 99,2341 + 0,7639 + 0,001937 = 99,999937: vale.
    load_profiles(write(tmp_path, block_text(pct=ALL | {"parada": 99.2341})))


def test_el_error_lleva_la_ruta(tmp_path):
    path = write(tmp_path, block_text(pct=ALL | {"orl": 0}))
    with pytest.raises(ValueError, match=rf"^{re.escape(str(path))}: motivos\.orl\.ingreso"):
        load_profiles(path)


def test_replace_respeta_el_todo_o_nada(tmp_path):
    profiles = load_profiles(write(tmp_path, block_text()))
    with pytest.raises(ValueError, match=r"missing keys: abandono, destinos$"):
        replace(profiles, outcome=None)
    reasons = tuple(
        replace(r, admission_pct=None) if r.key == "orl" else r for r in profiles.reasons
    )
    with pytest.raises(ValueError, match=r"missing keys: motivos\.orl\.ingreso$"):
        replace(profiles, reasons=reasons)
    hito4 = load_profiles(DATA / "perfiles_ejemplo.toml")
    with pytest.raises(ValueError, match=r"missing keys: motivos\.traumatismo\.ingreso"):
        replace(hito4, outcome=profiles.outcome)


def test_los_dataclass_validan_al_construirse():
    with pytest.raises(ValueError, match=r"destinos\.traslado\.base"):
        DestinationOdds("traslado", 0.75, 1.5)
    with pytest.raises(ValueError, match=r"must be one of \('ingreso', 'traslado', 'exitus'\)"):
        DestinationOdds("alta", 89.0, 1.0)
    with pytest.raises(ValueError, match=r"abandono\.paciencia must have 5 values"):
        Abandonment(((120, 360),))
