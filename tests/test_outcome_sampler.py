"""El muestreador del desenlace del hito 5 (``OutcomeSampler``, flujos 4, 8 y 9).

Consumo fijo (4 Gumbel, 1 normal y 1 normal por paciente, se usen o no), números comunes
(cambiar un parámetro solo cambia a los pacientes que debe) y la gravedad real: el destino
usa G y la paciencia el nivel real, nunca lo que ve la enfermera (el test determinista de
V10, con el paciente y los sorteos del plan de la tarea 5.2).
"""

import math
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path

import numpy as np
import pytest

from edsim.profiles.config import DestinationOdds, OutcomeProfile, load_profiles
from edsim.profiles.context import ArrivalContext
from edsim.profiles.outcome import destination_from_draws, patience_from_draw
from edsim.profiles.population import Person
from edsim.profiles.sampler import (
    N_OUTCOME_STREAMS,
    OutcomeSampler,
    PersonAndReason,
    PersonReasonSampler,
    SeverityTriageSampler,
    WorkupDurationSampler,
    abnormal_count,
    outcome_from_draws,
)
from edsim.profiles.workup import Workup
from edsim.seeds import child_streams

DATA = Path(__file__).parent / "data"
START = date(2026, 1, 1)
BED_WAIT = (240.0, 720.0)
N_PATIENTS = 2000


@pytest.fixture(scope="module")
def profiles():
    return load_profiles(DATA / "perfiles_h5_ejemplo.toml")


@dataclass(frozen=True)
class _Arrival:
    time: float


def chain(profiles, seed=7, n=N_PATIENTS, bed_wait=BED_WAIT):
    """La cadena de los muestreadores del hito 4 más el desenlace, con los flujos del motor."""
    s = child_streams(seed, 10)
    people = PersonReasonSampler(profiles, START, [s[5], s[6]])
    triage = SeverityTriageSampler(profiles, [s[7], s[1]])
    workup = WorkupDurationSampler(profiles, [s[3], s[2]])
    outcome = OutcomeSampler(profiles, bed_wait, [s[4], s[8], s[9]])
    rows = []
    for i in range(n):
        pr = people(_Arrival(7.0 * i))
        st = triage(pr)
        wd = workup(pr, st)
        rows.append((pr, st, wd.workup, outcome(pr, st, wd.workup)))
    return rows


# Consumo fijo.


def test_consumo_fijo_de_cuatro_gumbel_y_dos_normales(profiles):
    s = child_streams(3, 10)
    sampler = OutcomeSampler(profiles, BED_WAIT, [s[4], s[8], s[9]])
    reference = [np.random.default_rng(x) for x in (s[4], s[8], s[9])]
    for pr, st, w, _ in chain(profiles, n=50):
        sampler(pr, st, w)
        reference[0].gumbel(size=4)
        reference[1].standard_normal()
        reference[2].standard_normal()
    for rng, ref in zip(
        (sampler._destination_rng, sampler._patience_rng, sampler._bed_rng), reference, strict=True
    ):
        assert rng.bit_generator.state == ref.bit_generator.state


def test_los_sorteos_son_los_del_flujo(profiles):
    s = child_streams(3, 10)
    pr, st, w, _ = chain(profiles, n=1)[0]
    out = OutcomeSampler(profiles, BED_WAIT, [s[4], s[8], s[9]])(pr, st, w)
    assert out.destination_draws == tuple(np.random.default_rng(s[4]).gumbel(size=4))
    assert out.patience_z == np.random.default_rng(s[8]).standard_normal()
    assert out.bed_z == np.random.default_rng(s[9]).standard_normal()
    # La paciencia con el nivel real y la banda; la cama con factor 1.
    o = profiles.outcome.abandonment
    assert out.patience == patience_from_draw(o, st.true_level, pr.person.band, out.patience_z)
    mu, sigma = math.log(240), math.log(3) / 1.2815515655446004
    assert out.bed_base == pytest.approx(math.exp(mu + sigma * out.bed_z))


def test_los_flujos_no_se_modifican(profiles):
    s = child_streams(3, 10)
    before = [(x.entropy, x.spawn_key, x.n_children_spawned) for x in s]
    OutcomeSampler(profiles, BED_WAIT, [s[4], s[8], s[9]])
    assert [(x.entropy, x.spawn_key, x.n_children_spawned) for x in s] == before


def test_errores_del_muestreador(profiles):
    s = child_streams(3, 10)
    hito4 = load_profiles(DATA / "perfiles_ejemplo.toml")
    with pytest.raises(ValueError, match=r"needs the block \[abandono\]"):
        OutcomeSampler(hito4, BED_WAIT, [s[4], s[8], s[9]])
    with pytest.raises(ValueError, match=f"streams must have {N_OUTCOME_STREAMS} SeedSequence"):
        OutcomeSampler(profiles, BED_WAIT, [s[4], s[8]])
    with pytest.raises(ValueError, match=r"streams\[2\] must be a SeedSequence"):
        OutcomeSampler(profiles, BED_WAIT, [s[4], s[8], 9])
    with pytest.raises(ValueError, match=r"camas\.espera\[1\] \(the p90\) must be greater"):
        OutcomeSampler(profiles, (240, 120), [s[4], s[8], s[9]])


# Las pruebas alteradas cuentan solo entre las pedidas.


def test_alteradas_solo_entre_las_pedidas():
    workup = Workup(
        ordered=(True, False, True, False),
        abnormal=(True, True, False, False),
        turnarounds=(60.0, 30.0, 10.0, 100.0),
        draws=(0.0,) * 12,
    )
    # La radiografía sale alterada pero no se pide: no cuenta.
    assert abnormal_count(workup) == 1


def test_el_destino_cuenta_las_alteradas_de_la_cadena(profiles):
    for pr, st, w, out in chain(profiles, n=300):
        expected = destination_from_draws(
            profiles.outcome,
            profiles.reason(pr.reason).admission_pct,
            pr.person.band >= 2,
            st.severity,
            sum(o and a for o, a in zip(w.ordered, w.abnormal, strict=True)),
            out.destination_draws,
        )
        assert out.destination == expected


# El destino usa G, no G + ε (V10, el test determinista del plan).


def test_el_destino_usa_la_gravedad_real_y_no_la_que_ve_la_enfermera(profiles):
    # Pieza 2 para el traumatismo: base 6 / 0,5 / 0,05 %, odds ratios de G 3, 2 y 6.
    piece_2 = replace(
        profiles.outcome,
        admission=DestinationOdds("ingreso", 9.90, 3.0, older_or=2.0, abnormal_or=1.5),
        transfer=DestinationOdds("traslado", 0.75, 2.0, base=0.5),
        death=DestinationOdds("exitus", 0.11, 6.0, base=0.05),
    )
    reasons = tuple(
        replace(r, admission_pct=6.0) if r.key == "traumatismo" else r for r in profiles.reasons
    )
    variant = replace(profiles, reasons=reasons, outcome=piece_2)
    assert isinstance(variant.outcome, OutcomeProfile)

    # El paciente: traumatismo, banda 15-44, G y ε de los flujos 7 y 1 de child_streams(1, 10).
    s = child_streams(1, 10)
    z = float(np.random.default_rng(s[7]).standard_normal())
    z_e = float(np.random.default_rng(s[1]).standard_normal())
    g = -0.56 + -0.09 + 0.66 * z
    epsilon = -0.081 + 0.334 * z_e
    assert g == pytest.approx(-1.256993, abs=5e-7)
    assert epsilon == pytest.approx(0.749217, abs=5e-7)

    pr = PersonAndReason(ArrivalContext(0, 0, 0), Person(0, 30, False, False), "traumatismo")
    st = SeverityTriageSampler(variant, [s[7], s[1]])(pr)
    assert st.severity == pytest.approx(g)
    no_tests = Workup((False,) * 4, (False,) * 4, (60.0,) * 4, (0.0,) * 12)
    gumbels = (0.0, 3.7, 0.0, 0.0)

    # Con G: ingreso = −2,745717 − 1,380946 + 3,7 = −0,4267 < 0: alta.
    out = outcome_from_draws(variant, BED_WAIT, pr, st, no_tests, (gumbels, 0.0, 0.0))
    assert out.destination == "alta"
    # Con G + ε = −0,507775: ingreso = −2,745717 − 0,557848 + 3,7 = +0,3964 > 0: ingreso.
    assert destination_from_draws(piece_2, 6.0, False, g + epsilon, 0, gumbels) == "ingreso"


# Números comunes.


def test_un_odds_ratio_del_traslado_solo_mueve_el_traslado(profiles):
    transfer = replace(profiles.outcome.transfer, severity_or=2.5)
    other = replace(profiles, outcome=replace(profiles.outcome, transfer=transfer))
    a, b = chain(profiles), chain(other)
    changed = [(x[3].destination, y[3].destination) for x, y in zip(a, b, strict=True)]
    changed = [pair for pair in changed if pair[0] != pair[1]]
    assert changed  # la situación ocurre
    # Con G negativa (OR^G < 1) el paciente sale del traslado; con G positiva, entra.
    assert all("traslado" in pair for pair in changed)
    for x, y in zip(a, b, strict=True):
        assert x[3].patience == y[3].patience and x[3].bed_base == y[3].bed_base


def test_la_paciencia_y_la_cama_no_cambian_otros_sorteos(profiles):
    abandonment = replace(
        profiles.outcome.abandonment,
        patience=tuple((2 * m, 2 * p) for m, p in profiles.outcome.abandonment.patience),
    )
    other = replace(profiles, outcome=replace(profiles.outcome, abandonment=abandonment))
    a, b = chain(profiles), chain(other, bed_wait=(300.0, 600.0))
    for x, y in zip(a, b, strict=True):
        assert (x[0], x[1], x[2]) == (y[0], y[1], y[2])
        assert x[3].destination == y[3].destination
        assert x[3].destination_draws == y[3].destination_draws
        assert y[3].patience == pytest.approx(2 * x[3].patience)
        assert y[3].bed_base != x[3].bed_base


def test_cambiar_solo_epsilon_no_cambia_ningun_destino_ni_paciencia(profiles):
    other = replace(profiles, triage=replace(profiles.triage, noise=0.6))
    a, b = chain(profiles), chain(other)
    assert any(x[1].level != y[1].level for x, y in zip(a, b, strict=True))  # ε cambia
    for x, y in zip(a, b, strict=True):
        assert x[1].severity == y[1].severity and x[1].true_level == y[1].true_level
        assert x[3] == y[3]
