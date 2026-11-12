"""Objetivos de calibración: config/objetivos.toml y load_targets (tarea 4.6b)."""

import copy
import tomllib
from pathlib import Path

import pytest

from edsim.calibration.targets import (
    ARRIVALS_PERCENTAGE,
    CHECK,
    FIT,
    MANCHESTER,
    PERCENTAGE,
    Target,
    load_targets,
    targets_from_data,
)

CONFIG = Path(__file__).resolve().parents[1] / "config" / "objetivos.toml"


@pytest.fixture
def data() -> dict:
    with CONFIG.open("rb") as file:
        return tomllib.load(file)


def test_carga_los_cinco_objetivos_reales_con_su_fuente():
    targets = {t.name: t for t in load_targets(CONFIG)}

    assert list(targets) == [
        "pretriaje_medio",
        "tiempo_medico_niveles_2_5",
        "tiempo_medico_nivel_3",
        "porcentaje_sobre_manchester",
        "porcentaje_pretriaje_mas_5",
    ]
    pretriage = targets["pretriaje_medio"]
    assert (pretriage.measure, pretriage.levels, pretriage.reference, pretriage.band) == (
        "triage_wait",
        (2, 3, 4, 5),
        12.4,
        (6.0, 15.0),
    )
    assert targets["tiempo_medico_niveles_2_5"].reference is None
    assert targets["tiempo_medico_nivel_3"].levels == (3,)
    assert targets["tiempo_medico_nivel_3"].reference == 59.0
    assert targets["porcentaje_sobre_manchester"].threshold == MANCHESTER
    assert targets["porcentaje_pretriaje_mas_5"].threshold == 5.0
    # El nivel 3 es de comprobación desde la tarea 4.6b, después de medir la sensibilidad.
    assert [t.use for t in targets.values()] == [FIT, FIT, CHECK, CHECK, CHECK]
    assert targets["tiempo_medico_nivel_3"].note.startswith("Discrepancia estructural")
    assert all(
        t.source.startswith("SAS") and t.link.startswith("https://") for t in targets.values()
    )


def test_lo_que_busca_el_ajuste_es_la_referencia_o_el_centro_de_la_horquilla():
    targets = {t.name: t for t in load_targets(CONFIG)}
    assert targets["pretriaje_medio"].aim == 12.4
    assert targets["tiempo_medico_niveles_2_5"].aim == 52.5  # sin referencia: (35 + 70) / 2


def test_umbral_de_manchester_por_nivel():
    target = next(t for t in load_targets(CONFIG) if t.name == "porcentaje_sobre_manchester")
    assert [target.threshold_for(level) for level in (2, 3, 4, 5)] == [10.0, 60.0, 120.0, 240.0]


def _error(data: dict, edit) -> str:
    changed = copy.deepcopy(data)
    edit(changed["objetivos"]["pretriaje_medio"])
    with pytest.raises(ValueError) as caught:
        targets_from_data(changed)
    return str(caught.value)


@pytest.mark.parametrize(
    ("edit", "message"),
    [
        (lambda t: t.update(horquila=[6, 15]), "unknown keys: objetivos.pretriaje_medio.horquila"),
        (lambda t: t.pop("uso"), "missing keys: objetivos.pretriaje_medio.uso"),
        (
            lambda t: t.update(horquilla=[15, 6]),
            "objetivos.pretriaje_medio.horquilla must have min < max",
        ),
        (
            lambda t: t.update(horquilla=[6, 6]),
            "objetivos.pretriaje_medio.horquilla must have min < max",
        ),
        (lambda t: t.update(uso="ajustes"), "objetivos.pretriaje_medio.uso must be one of"),
        (
            lambda t: t.update(referencia=16.0),
            "objetivos.pretriaje_medio.referencia must be inside the band",
        ),
        (
            lambda t: t.update(umbral=5),
            "objetivos.pretriaje_medio.umbral is only for 'porcentaje_sobre_umbral'",
        ),
        (
            lambda t: t.update(niveles=[3, 2]),
            "objetivos.pretriaje_medio.niveles must be increasing",
        ),
        (lambda t: t.update(niveles=[]), "objetivos.pretriaje_medio.niveles must be a non-empty"),
        (
            lambda t: t.update(niveles=[2, 6]),
            "objetivos.pretriaje_medio.niveles[1] must be a level",
        ),
        (lambda t: t.update(medida="espera"), "objetivos.pretriaje_medio.medida must be one of"),
        (
            lambda t: t.update(estadistico="mediana"),
            "objetivos.pretriaje_medio.estadistico must be one of",
        ),
        (lambda t: t.update(fuente=""), "objetivos.pretriaje_medio.fuente must be a non-empty"),
    ],
)
def test_errores_con_la_clave_completa(data, edit, message):
    assert message in _error(data, edit)


@pytest.mark.parametrize(
    ("umbral", "message"),
    [
        (None, "objetivos.pretriaje_medio.umbral is required"),
        (0, "objetivos.pretriaje_medio.umbral must be minutes > 0 or 'manchester'"),
        ("triaje", "objetivos.pretriaje_medio.umbral must be minutes > 0 or 'manchester'"),
    ],
)
def test_umbral_de_un_porcentaje(data, umbral, message):
    def edit(t):
        t.update(estadistico=PERCENTAGE, horquilla=[30, 60], referencia=46.3)
        if umbral is None:
            t.pop("umbral", None)
        else:
            t["umbral"] = umbral

    assert message in _error(data, edit)


def test_horquilla_de_un_porcentaje_entre_0_y_100(data):
    def edit(t):
        t.update(estadistico=PERCENTAGE, umbral=5, horquilla=[30, 120], referencia=46.3)

    assert "horquilla of a percentage must be within [0, 100]" in _error(data, edit)


def test_referencia_opcional_y_en_el_borde_de_la_horquilla():
    common = dict(
        measure="triage_wait",
        levels=[2],
        statistic="media",
        threshold=None,
        band=[6, 15],
        use=FIT,
        source="SAS",
        link="https://example.org",
    )
    assert Target(name="a", **common).reference is None
    assert Target(name="b", reference=6, **common).reference == 6.0
    assert Target(name="c", reference=15, **common).reference == 15.0


def test_claves_de_primer_nivel(data):
    with pytest.raises(ValueError, match="unknown keys: centro"):
        targets_from_data({**data, "centro": {}})
    with pytest.raises(ValueError, match="missing keys: objetivos"):
        targets_from_data({})
    with pytest.raises(ValueError, match="objetivos.x must be a table"):
        targets_from_data({"objetivos": {"x": 3}})


# --- Los objetivos del hito 5: porcentaje de llegadas y destino (tarea 5.6) -----------------

SAS = {"fuente": "SAS", "enlace": "https://example.org", "uso": "ajuste"}
ABANDONO = {
    "medida": "left",
    "estadistico": "porcentaje_de_llegadas",
    "referencia": 1.82,
    "horquilla": [1, 4],
    **SAS,
}
ESTANCIA_INGRESADOS = {
    "medida": "stay",
    "destino": "ingreso",
    "niveles": [1, 2, 3, 4, 5],
    "estadistico": "media",
    "referencia": 472.5,
    "horquilla": [360, 600],
    **SAS,
}


def _one(table: dict) -> Target:
    (target,) = targets_from_data({"objetivos": {"x": table}})
    return target


def test_el_porcentaje_de_llegadas_no_lleva_niveles():
    target = _one(ABANDONO)
    assert (target.measure, target.levels, target.statistic) == (
        "left",
        (),
        ARRIVALS_PERCENTAGE,
    )
    assert target.is_percentage and target.needs_outcome
    assert target.aim == 1.82


def test_la_estancia_con_destino():
    target = _one(ESTANCIA_INGRESADOS)
    assert (target.measure, target.destination, target.levels) == (
        "stay",
        "ingreso",
        (1, 2, 3, 4, 5),
    )
    assert not target.is_percentage and target.needs_outcome


@pytest.mark.parametrize(
    ("table", "needs"),
    [
        (ABANDONO, True),
        ({**ABANDONO, "medida": "departure"}, False),
        ({**ABANDONO, "medida": "departure", "destino": "ingreso"}, True),
        (ESTANCIA_INGRESADOS, True),
        ({k: v for k, v in ESTANCIA_INGRESADOS.items() if k != "destino"}, False),
    ],
    ids=["abandono", "salidas", "ingreso_observado", "estancia_ingresados", "estancia"],
)
def test_que_objetivos_necesitan_el_modelo_del_hito_5(table, needs):
    # Solo el abandono y los destinos del hito 5; la estancia de todos existe en el hito 4.
    assert _one(table).needs_outcome is needs


@pytest.mark.parametrize(
    ("table", "message"),
    [
        (
            {**ABANDONO, "niveles": [4, 5]},
            "objetivos.x.niveles is not allowed with 'porcentaje_de_llegadas'",
        ),
        (
            {**ABANDONO, "umbral": 5},
            "objetivos.x.umbral is only for 'porcentaje_sobre_umbral', not for"
            " 'porcentaje_de_llegadas'",
        ),
        (
            {**ABANDONO, "medida": "stay"},
            "objetivos.x.medida must be one of ('left', 'departure') with 'porcentaje_de_llegadas'",
        ),
        ({**ABANDONO, "horquilla": [1, 140]}, "horquilla of a percentage must be within [0, 100]"),
        (
            {**ESTANCIA_INGRESADOS, "medida": "triage_wait"},
            "objetivos.x.destino is only for the measures 'stay' and 'departure'",
        ),
        ({**ESTANCIA_INGRESADOS, "destino": "uci"}, "objetivos.x.destino must be one of"),
        ({**ESTANCIA_INGRESADOS, "medida": "left"}, "objetivos.x.medida must be one of"),
        (
            {k: v for k, v in ESTANCIA_INGRESADOS.items() if k != "niveles"},
            "missing keys: objetivos.x.niveles",
        ),
        ({**ESTANCIA_INGRESADOS, "destinos": "ingreso"}, "unknown keys: objetivos.x.destinos"),
    ],
    ids=[
        "niveles",
        "umbral",
        "medida_de_suceso",
        "horquilla",
        "destino_sin_estancia",
        "destino_desconocido",
        "suceso_en_una_media",
        "faltan_niveles",
        "clave_desconocida",
    ],
)
def test_errores_de_los_objetivos_del_hito_5_con_la_clave_completa(table, message):
    with pytest.raises(ValueError) as caught:
        _one(table)
    assert message in str(caught.value)
