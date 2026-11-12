"""Los mandos del hito 5: la espera de cama y la paciencia (tarea 5.6, H5-9).

La espera de cama mueve la mediana m con p90 = 3 · m; la paciencia, un factor común k sobre
las medianas y los p90 de los cinco niveles reales, que desplaza la lognormal sin cambiar su
forma (σ). Los dos eligen con la regla de siempre: el más cercano a la referencia entre los
que pasan, con el veto de la semilla de comprobación (decisión 41, V20).
"""

import dataclasses
import math
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType

import pytest

from edsim.arrivals.profile import load_profile
from edsim.calibration.evaluate import (
    ReplicaValues,
    SensitivityRow,
    TargetResult,
    TargetValues,
    candidate_inputs,
    check_knob_model,
    choose_staffing,
    evaluate_settings,
    knob_settings,
    simulate_replicas,
)
from edsim.calibration.knobs import (
    BED_GRID,
    BED_WAIT,
    PATIENCE,
    PATIENCE_GRID,
    KnobValue,
    bed_wait_center,
    check_knob_value,
    scaled_patience,
)
from edsim.calibration.report import format_choice, format_sensitivity_row
from edsim.calibration.staffing import NURSES, RuleStaffing
from edsim.calibration.targets import ARRIVALS_PERCENTAGE, FIT, Target
from edsim.engine.center import load_center
from edsim.profiles.config import load_profiles
from edsim.profiles.outcome import patience_params, patience_quantile
from edsim.stats import Summary

DATA = Path(__file__).resolve().parent / "data"


@pytest.fixture(scope="module")
def h5():
    return (
        load_center(DATA / "centro_h5_ejemplo.toml"),
        load_profile(DATA / "llegadas_ejemplo.toml"),
        load_profiles(DATA / "perfiles_h5_ejemplo.toml"),
    )


# --- La paciencia ---------------------------------------------------------------------------


def test_el_factor_de_paciencia_mueve_la_mediana_y_no_sigma(h5):
    # El nivel 4 de partida es [150, 450]: con k = 2, [300, 900]. La mediana (el cuantil
    # 0,5 en la banda de factor 1) se dobla y σ = ln 3 / 1,28155 = 0,85725 no cambia.
    _, _, profiles = h5
    scaled = scaled_patience(profiles, 2.0)
    before, after = profiles.outcome.abandonment, scaled.outcome.abandonment
    assert after.patience[3] == (300.0, 900.0)
    band = 1  # 45 a 64 años: factor de edad 1
    assert patience_quantile(after, 4, band, 0.5) == pytest.approx(300.0)
    for level in range(1, 6):
        _, sigma_before = patience_params(before, level, band)
        _, sigma_after = patience_params(after, level, band)
        assert sigma_after == pytest.approx(sigma_before, rel=1e-12)
        assert sigma_before == pytest.approx(math.log(3) / 1.2815515655446004, rel=1e-12)


def test_la_rejilla_de_paciencia_escribe_los_pares_de_partida_por_k(h5):
    # 2^(i/4) con 3 decimales, de 1 a 8 (calculada a mano en el plan).
    assert PATIENCE_GRID == (
        1.0, 1.189, 1.414, 1.682, 2.0, 2.378, 2.828, 3.364, 4.0, 4.757, 5.657, 6.727, 8.0
    )  # fmt: skip
    _, _, profiles = h5
    scaled = scaled_patience(profiles, 3.364).outcome.abandonment.patience
    # [1440, 4320] · 3,364 = [4844,16; 14532,48]; [150, 450] · 3,364 = [504,6; 1513,8].
    assert scaled[0] == (4844.16, 14532.48)
    assert scaled[3] == (504.6, 1513.8)
    # Escritos con 3 decimales, el cociente sigue siendo 3 en decimal exacto.
    for median, p90 in scaled:
        assert Decimal(repr(p90)) == 3 * Decimal(repr(median))


def test_la_paciencia_solo_cambia_la_paciencia(h5):
    _, _, profiles = h5
    scaled = scaled_patience(profiles, 1.682)
    outcome = scaled.outcome
    assert outcome.abandonment.age_factors == profiles.outcome.abandonment.age_factors
    restored = dataclasses.replace(
        scaled,
        outcome=dataclasses.replace(outcome, abandonment=profiles.outcome.abandonment),
    )
    assert restored == profiles


def test_con_k_1_los_perfiles_son_los_mismos(h5):
    _, _, profiles = h5
    assert scaled_patience(profiles, 1.0) == profiles


# --- La espera de cama ------------------------------------------------------------------------


def test_la_espera_de_cama_con_p90_tres_veces_la_mediana(h5):
    center, _, _ = h5
    candidate = bed_wait_center(center, 210)
    assert candidate.bed_wait == (210.0, 630.0)
    # Los factores de turno (y todo lo demás) no cambian.
    assert candidate.bed_shift_factors == center.bed_shift_factors == (0.8, 1.0, 1.5)
    assert dataclasses.replace(candidate, bed_wait=center.bed_wait) == center
    # La de partida del ejemplo, [240, 720], es la misma.
    assert bed_wait_center(center, 240) == center


def test_la_rejilla_de_la_cama():
    assert BED_GRID == tuple(float(m) for m in range(120, 361, 15))
    assert (len(BED_GRID), BED_GRID[0], BED_GRID[-1]) == (17, 120.0, 360.0)


@pytest.mark.parametrize(
    ("knob", "value", "message"),
    [
        (BED_WAIT, 0, "must be in"),
        (BED_WAIT, -15, "must be in"),
        (BED_WAIT, 7 * 1440 + 1, "must be in"),
        (BED_WAIT, math.nan, "must be a finite number"),
        (PATIENCE, math.inf, "must be a finite number"),
        (PATIENCE, True, "must be a finite number"),
        (PATIENCE, 101, "must be in"),
        ("medicos", 2, "knob must be one of"),
    ],
)
def test_valores_no_validos(knob, value, message):
    with pytest.raises(ValueError, match=message):
        check_knob_value(knob, value)


def test_los_mandos_del_hito_5_necesitan_el_modelo_del_hito_5(h5):
    h4_center = load_center(DATA / "centro_sala_ejemplo.toml")
    h4_profiles = load_profiles(DATA / "perfiles_ejemplo.toml")
    with pytest.raises(ValueError, match=r"needs a center with \[camas\]"):
        bed_wait_center(h4_center, 200)
    with pytest.raises(ValueError, match=r"needs profiles with \[abandono\]"):
        scaled_patience(h4_profiles, 2)
    for knob in (BED_WAIT, PATIENCE):
        with pytest.raises(ValueError, match=f"the knob {knob} needs the milestone 5 model"):
            check_knob_model(knob, h4_center, h4_profiles)
    center, _, profiles = h5
    check_knob_model(BED_WAIT, center, profiles)
    check_knob_model(NURSES, h4_center, h4_profiles)


# --- Candidatos ---------------------------------------------------------------------------------


def test_cada_candidato_cambia_solo_su_mando(h5):
    center, _, profiles = h5
    bed_center, bed_profiles = candidate_inputs(center, profiles, BED_WAIT, KnobValue(180))
    assert bed_profiles is profiles and bed_center.bed_wait == (180.0, 540.0)
    patience_center, patience_profiles = candidate_inputs(
        center, profiles, PATIENCE, KnobValue(2.0)
    )
    assert patience_center is center
    assert patience_profiles.outcome.abandonment.patience[4] == (240.0, 720.0)
    staff_center, staff_profiles = candidate_inputs(
        center, profiles, NURSES, RuleStaffing((2, 2, 1), 0.8, 0.8)
    )
    assert staff_profiles is profiles and staff_center.triage_nurses == (2, 2, 1)
    with pytest.raises(ValueError, match="takes one value"):
        candidate_inputs(center, profiles, PATIENCE, RuleStaffing((2, 2, 1), 0.8, 0.8))
    with pytest.raises(ValueError, match="takes a staff of the rule"):
        candidate_inputs(center, profiles, NURSES, KnobValue(2.0))


def test_los_candidatos_de_cada_mando(h5):
    center, arrivals, profiles = h5
    assert knob_settings(BED_WAIT, center, profiles, arrivals) == tuple(
        KnobValue(v) for v in BED_GRID
    )
    assert knob_settings(PATIENCE, center, profiles, arrivals, values=[1, 1.5]) == (
        KnobValue(1.0),
        KnobValue(1.5),
    )
    with pytest.raises(ValueError, match="needs at least one value"):
        knob_settings(PATIENCE, center, profiles, arrivals, values=[])
    with pytest.raises(ValueError, match="takes the grid of u, not values"):
        knob_settings(NURSES, center, profiles, arrivals, values=[2])


ABANDONO = Target(
    name="abandono",
    measure="left",
    levels=(),
    statistic=ARRIVALS_PERCENTAGE,
    threshold=None,
    band=(0, 100),
    use=FIT,
    source="a mano",
    link="https://example.org",
    reference=1.82,
)


def test_con_k_1_la_fila_es_la_evaluacion_sin_mando_bit_a_bit(h5):
    # Números aleatorios comunes: el candidato de k = 1 (y el de la cama de partida) es el
    # mismo modelo, así que su réplica es la de los ficheros, bit a bit.
    center, arrivals, profiles = h5
    options = {"replicas": 2, "days": 2, "warmup_days": 1, "seed": 2026}
    plain = simulate_replicas(center, arrivals, profiles, (ABANDONO,), **options)
    for knob, value in ((PATIENCE, 1.0), (BED_WAIT, 240.0)):
        (row,) = evaluate_settings(
            center, arrivals, profiles, (ABANDONO,), knob, [KnobValue(value)], **options
        )
        assert row.replicas == plain


def test_mas_paciencia_menos_abandono_con_los_mismos_pacientes(h5):
    center, arrivals, profiles = h5
    options = {"replicas": 2, "days": 2, "warmup_days": 1, "seed": 2026}
    rows = evaluate_settings(
        center, arrivals, profiles, (ABANDONO,), PATIENCE, [KnobValue(1), KnobValue(4)], **options
    )
    means = [row.results[0].mean for row in rows]
    assert means[1] < means[0]


# --- La elección y el veto (V20) ----------------------------------------------------------------

# Una referencia de 2,0 para que las distancias sean exactas en coma flotante.
ESTANCIA = dataclasses.replace(ABANDONO, name="estancia_ingresados", reference=2.0)


def result(t: Target, mean: float, passed: bool = True) -> TargetResult:
    summary = Summary(12, mean, 1.0, 0.3, mean - 0.7, mean + 0.7, 0.95)
    return TargetResult(t, (mean,) * 12, summary, (0.0,) * 12, passed, True)


def value_row(value: float, t: Target, mean: float, passed: bool = True) -> SensitivityRow:
    values = TargetValues(mean, (mean,), (100,), (int(mean),))
    reps = (ReplicaValues(MappingProxyType({t.name: values}), 100, 0, (0,) * 5, (12,) * 5),) * 2
    return SensitivityRow(KnobValue(value), None, (result(t, mean, passed),), reps)


def bed_rows():
    # Referencia 2,0: pasan 195 (1,5), 210 (1,875) y 225 (2,5); 210 es la más cercana.
    return [
        value_row(180, ESTANCIA, 1.0, passed=False),
        value_row(195, ESTANCIA, 1.5),
        value_row(210, ESTANCIA, 1.875),
        value_row(225, ESTANCIA, 2.5),
    ]


def test_la_cama_elige_la_mas_cercana_a_la_referencia_entre_las_que_pasan():
    assert choose_staffing(bed_rows(), BED_WAIT).setting == KnobValue(210)


def test_empate_el_valor_menor():
    rows = [value_row(240, ESTANCIA, 2.5), value_row(225, ESTANCIA, 1.5)]
    # |2,5 − 2| = |1,5 − 2| = 0,5, exactos: gana la de menos minutos.
    assert choose_staffing(rows, BED_WAIT).setting == KnobValue(225)


def test_el_veto_de_2027_descarta_la_primera_cama():
    rows = bed_rows()
    checked = {
        210: value_row(210, ESTANCIA, 4.5, passed=False),
        195: value_row(195, ESTANCIA, 1.625),
    }
    calls = []

    def check(row):
        calls.append(row.setting.value)
        return checked[row.setting.value]

    assert choose_staffing(rows, BED_WAIT, check=check).setting == KnobValue(195)
    assert calls == [210, 195]


def test_el_veto_de_2027_en_la_paciencia():
    rows = [value_row(2.828, ABANDONO, 2.1), value_row(3.364, ABANDONO, 1.7)]
    checked = {
        3.364: value_row(3.364, ABANDONO, 0.8, passed=False),
        2.828: value_row(2.828, ABANDONO, 2.6),
    }
    chosen = choose_staffing(rows, PATIENCE, check=lambda r: checked[r.setting.value])
    assert chosen.setting == KnobValue(2.828)


def test_la_comprobacion_tiene_que_ser_del_mismo_valor():
    with pytest.raises(ValueError, match="the check of 210 is of 195"):
        choose_staffing(bed_rows(), BED_WAIT, check=lambda r: value_row(195, ESTANCIA, 1.875))


def test_la_eleccion_impresa_y_el_aviso_del_borde():
    rows = bed_rows()
    text = format_choice(BED_WAIT, rows[2], rows=rows)
    assert "espera_cama 210 min de mediana (p90 630); estancia_ingresados 1.88" in text
    assert "borde" not in text
    edge = format_choice(BED_WAIT, rows[3], rows=rows)
    assert "AVISO: 225 está en el borde de los valores evaluados (180 a 225)" in edge
    none = format_choice(PATIENCE, None, rows=rows)
    assert "Elección: ningún valor de la rejilla pasa abandono; no se fuerza" in none
    assert format_sensitivity_row(rows[2], BED_WAIT).startswith("210 ")
