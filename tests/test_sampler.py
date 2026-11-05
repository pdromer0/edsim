"""Muestreador de persona y motivo (flujos 5 y 6): consumo fijo y números comunes."""

import dataclasses
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from profiles_factory import START

from edsim.arrivals.thinning import ArrivalRecord
from edsim.profiles.config import REASON_KEYS, ClinicalProfiles, load_profiles
from edsim.profiles.context import arrival_context
from edsim.profiles.mixing import gumbel_max, reason_weights
from edsim.profiles.population import Person, draw_person_standard, person_from_draws
from edsim.profiles.sampler import (
    N_REASON_DRAWS,
    PersonAndReason,
    PersonReasonSampler,
    SeverityAndTriage,
    SeverityTriageSampler,
    draw_reason_standard,
    draw_severity_standard,
)
from edsim.profiles.severity import severity_from_draw, triage_from_draws, triage_quality
from edsim.seeds import child_streams

EXAMPLE = Path(__file__).parent / "data" / "perfiles_ejemplo.toml"
SEED = 2026
N = 20_000
YEAR = 365 * 1440


def streams(seed=SEED) -> list[np.random.SeedSequence]:
    """Los flujos 5 y 6 de child_streams(seed, 8), como los pasará el motor."""
    return child_streams(seed, 8)[5:7]


def year_arrivals(n: int) -> list[ArrivalRecord]:
    """n llegadas repartidas por igual en un año, fuera de los bordes de franja."""
    return [ArrivalRecord(k, (k + 0.37) * YEAR / n) for k in range(n)]


def run(profiles: ClinicalProfiles, arrivals, seed=SEED) -> list[PersonAndReason]:
    sampler = PersonReasonSampler(profiles, START, streams(seed))
    return [sampler(a) for a in arrivals]


def with_weight(profiles: ClinicalProfiles, key: str, factor: float) -> ClinicalProfiles:
    reasons = tuple(
        dataclasses.replace(r, base_weight=r.base_weight * factor) if r.key == key else r
        for r in profiles.reasons
    )
    return dataclasses.replace(profiles, reasons=reasons)


@pytest.fixture(scope="module")
def profiles() -> ClinicalProfiles:
    return load_profiles(EXAMPLE)


@pytest.fixture(scope="module")
def arrivals() -> list[ArrivalRecord]:
    return year_arrivals(N)


@pytest.fixture(scope="module")
def base(profiles, arrivals) -> list[PersonAndReason]:
    return run(profiles, arrivals)


# --- Números aleatorios comunes ------------------------------------------------


@pytest.fixture(scope="module")
def more_dyspnoea(profiles, arrivals) -> list[PersonAndReason]:
    return run(with_weight(profiles, "disnea", 1.5), arrivals)


def test_con_mas_disnea_solo_cambian_los_que_pasan_a_disnea(base, more_dyspnoea):
    changed = [(a, b) for a, b in zip(base, more_dyspnoea, strict=True) if a.reason != b.reason]

    # El caso ocurre: si nadie cambiara, el test pasaría de forma vacía.
    assert len(changed) > 0
    # Ningún paciente cambia entre dos motivos distintos de la disnea.
    assert all(b.reason == "disnea" and a.reason != "disnea" for a, b in changed)


def test_fraccion_que_cambia_con_mas_disnea(base, more_dyspnoea):
    # Con Gumbel-max cambia lo mínimo posible: la probabilidad de disnea sube del
    # 8,0 % a alrededor del 11,4 %, un 3,4 % de los pacientes (el prototipo del plan,
    # exacto sobre la mezcla de un año). Con la CDF inversa cambiaría el 15,6 %.
    fraction = np.mean([a.reason != b.reason for a, b in zip(base, more_dyspnoea, strict=True)])

    assert 0.025 < fraction < 0.045


def test_con_mas_disnea_la_persona_no_cambia(base, more_dyspnoea):
    assert [a.person for a in base] == [b.person for b in more_dyspnoea]
    assert [a.context for a in base] == [b.context for b in more_dyspnoea]


def test_con_otra_poblacion_el_flujo_del_motivo_no_cambia(profiles, arrivals):
    # Con otros porcentajes de mujeres cambia solo el sexo: banda, edad y motivo
    # salen de los mismos sorteos.
    other = dataclasses.replace(
        profiles,
        population=dataclasses.replace(profiles.population, female_pct=(10, 20, 30, 40)),
    )
    a = run(profiles, arrivals[:2000])
    b = run(other, arrivals[:2000])

    assert [x.reason for x in a] == [x.reason for x in b]
    assert [(x.person.band, x.person.age) for x in a] == [(x.person.band, x.person.age) for x in b]
    assert [x.person.female for x in a] != [x.person.female for x in b]


# --- Consumo fijo --------------------------------------------------------------


@pytest.mark.parametrize("factor", [1.0, 1.5, 0.2])
def test_paciente_k_recibe_su_bloque_de_sorteos(profiles, arrivals, factor):
    # El paciente k de un muestreador con otros pesos es exactamente la
    # transformación del bloque k de 7 + 17 sorteos de un generador independiente:
    # el consumo no depende de lo que salga.
    changed = with_weight(profiles, "traumatismo", factor)
    population_seq, reason_seq = streams()
    population_rng = np.random.default_rng(population_seq)
    reason_rng = np.random.default_rng(reason_seq)
    sampler = PersonReasonSampler(changed, START, streams())

    for arrival in arrivals[:3000]:
        ctx = arrival_context(arrival.time, START, changed.shift_band_starts)
        person = person_from_draws(changed.population, ctx, draw_person_standard(population_rng))
        g = draw_reason_standard(reason_rng)
        reason = REASON_KEYS[gumbel_max(reason_weights(changed, ctx, person.band), g)]

        assert sampler(arrival) == PersonAndReason(context=ctx, person=person, reason=reason)


def test_diecisiete_gumbel_por_paciente():
    a, b = np.random.default_rng(5), np.random.default_rng(5)

    g = draw_reason_standard(a)

    assert N_REASON_DRAWS == 17 == len(REASON_KEYS)
    np.testing.assert_array_equal(g, b.gumbel(size=17))


def test_los_flujos_no_se_modifican(profiles, arrivals):
    seqs = streams()
    before = [(s.entropy, s.spawn_key, s.n_children_spawned) for s in seqs]

    first = run_with(profiles, seqs, arrivals[:500])
    second = run_with(profiles, seqs, arrivals[:500])

    assert [(s.entropy, s.spawn_key, s.n_children_spawned) for s in seqs] == before
    assert first == second


def run_with(profiles, seqs, arrivals):
    sampler = PersonReasonSampler(profiles, START, seqs)
    return [sampler(a) for a in arrivals]


def test_otra_semilla_da_otros_pacientes(profiles, arrivals):
    assert run(profiles, arrivals[:200]) != run(profiles, arrivals[:200], seed=SEED + 1)


@pytest.mark.parametrize("n", [1, 3])
def test_numero_de_flujos_incorrecto(profiles, n):
    with pytest.raises(ValueError, match="2"):
        PersonReasonSampler(profiles, START, child_streams(SEED, n))


def test_flujos_que_no_son_seed_sequence(profiles):
    with pytest.raises(ValueError, match="SeedSequence"):
        PersonReasonSampler(profiles, START, [5, 6])


# --- Interfaz ------------------------------------------------------------------


def test_tipos_de_python(base):
    x = base[0]

    assert type(x.reason) is str and x.reason in REASON_KEYS
    assert isinstance(x.person, Person)
    assert type(x.person.age) is int and type(x.person.female) is bool


def test_edades_y_motivos_en_rango(base):
    ages = np.array([x.person.age for x in base])

    assert ages.min() >= 15 and ages.max() <= 99
    assert {x.reason for x in base} == set(REASON_KEYS)  # los 17 salen en 20 000


def test_inmutable(base):
    with pytest.raises(dataclasses.FrozenInstanceError):
        base[0].reason = "otros"


def test_el_contexto_es_el_de_la_llegada(profiles, base, arrivals):
    for x, a in zip(base[::997], arrivals[::997], strict=True):
        assert x.context == arrival_context(a.time, START, profiles.shift_band_starts)


def test_profiles_no_carga_simpy_ni_el_motor():
    script = (
        "import sys, importlib, pkgutil, edsim.profiles\n"
        "for m in pkgutil.walk_packages(edsim.profiles.__path__, 'edsim.profiles.'):\n"
        "    importlib.import_module(m.name)\n"
        "assert 'edsim.profiles.sampler' in sys.modules\n"
        "bad = sorted(n for n in sys.modules if n.split('.')[0] == 'simpy'"
        " or n.startswith('edsim.engine'))\n"
        "assert not bad, bad\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=False, timeout=60
    )

    assert result.returncode == 0, result.stdout + result.stderr


# --- Gravedad y triaje (flujos 7 y 1) ------------------------------------------


def severity_streams(seed=SEED) -> list[np.random.SeedSequence]:
    """Los flujos 7 y 1 de child_streams(seed, 8), en ese orden."""
    children = child_streams(seed, 8)
    return [children[7], children[1]]


def run_triage(profiles: ClinicalProfiles, people, seed=SEED) -> list[SeverityAndTriage]:
    sampler = SeverityTriageSampler(profiles, severity_streams(seed))
    return [sampler(p) for p in people]


def with_triage(profiles: ClinicalProfiles, **changes) -> ClinicalProfiles:
    return dataclasses.replace(profiles, triage=dataclasses.replace(profiles.triage, **changes))


@pytest.fixture(scope="module")
def triaged(profiles, base) -> list[SeverityAndTriage]:
    return run_triage(profiles, base)


def test_paciente_k_recibe_su_normal_de_cada_flujo(profiles, base):
    # El paciente k usa exactamente la normal k del flujo 7 y la normal k del
    # flujo 1, de generadores independientes: el consumo no depende de lo que salga.
    severity_seq, noise_seq = severity_streams()
    severity_rng = np.random.default_rng(severity_seq)
    noise_rng = np.random.default_rng(noise_seq)
    sampler = SeverityTriageSampler(profiles, severity_streams())
    t = profiles.triage

    for pr in base[:3000]:
        z, z_noise = severity_rng.standard_normal(), noise_rng.standard_normal()
        g = severity_from_draw(profiles.reason(pr.reason).severity, pr.person.band, z)
        level, true_level = triage_from_draws(g, z_noise, t.thresholds, t.noise, t.bias)
        quality, jump = triage_quality(level, true_level)

        assert sampler(pr) == SeverityAndTriage(
            z=z, severity=g, level=level, true_level=true_level, quality=quality, jump=jump
        )


def test_una_normal_por_flujo_y_paciente():
    a, b = np.random.default_rng(5), np.random.default_rng(5)

    assert draw_severity_standard(a) == b.standard_normal()
    assert draw_severity_standard(a) == b.standard_normal()


def test_los_flujos_de_gravedad_no_se_modifican(profiles, base):
    seqs = severity_streams()
    before = [(s.entropy, s.spawn_key, s.n_children_spawned) for s in seqs]

    first = list(map(SeverityTriageSampler(profiles, seqs), base[:500]))
    second = list(map(SeverityTriageSampler(profiles, seqs), base[:500]))

    assert [(s.entropy, s.spawn_key, s.n_children_spawned) for s in seqs] == before
    assert first == second


def test_con_otro_ruido_solo_cambia_el_nivel_asignado(profiles, base, triaged):
    other = run_triage(with_triage(profiles, noise=0.5), base)

    assert [x.severity for x in other] == [x.severity for x in triaged]
    assert [x.true_level for x in other] == [x.true_level for x in triaged]
    changed = sum(a.level != b.level for a, b in zip(triaged, other, strict=True))
    # El caso ocurre: si nadie cambiara de nivel asignado, el test sería vacío.
    assert changed > 0


def test_con_otra_media_solo_cambia_la_gravedad_de_ese_motivo(profiles, base, triaged):
    disnea = profiles.reason("disnea")
    other_profiles = dataclasses.replace(
        profiles,
        reasons=tuple(
            dataclasses.replace(r, severity=dataclasses.replace(r.severity, mean=1.5))
            if r.key == "disnea"
            else r
            for r in profiles.reasons
        ),
    )
    other = run_triage(other_profiles, base)

    shift = 1.5 - disnea.severity.mean
    for pr, a, b in zip(base, triaged, other, strict=True):
        if pr.reason == "disnea":
            assert b.severity == pytest.approx(a.severity + shift, abs=1e-12)
            assert b.z == a.z  # el paciente conserva su percentil
        else:
            assert b == a
    assert any(pr.reason == "disnea" for pr in base)


def test_el_muestreador_usa_los_umbrales_escritos(profiles, base, triaged):
    # Los umbrales del perfil, tal cual: con otros, otros niveles.
    other = run_triage(with_triage(profiles, thresholds=(9.0, 8.0, 7.0, 6.0)), base[:500])

    assert all(x.level == 5 and x.true_level == 5 for x in other)
    assert {x.level for x in triaged} == {1, 2, 3, 4, 5}


def test_tipos_de_la_gravedad(triaged):
    x = triaged[0]

    assert type(x.z) is float and type(x.severity) is float
    assert type(x.level) is int and type(x.true_level) is int and type(x.jump) is int
    assert x.quality in ("correcto", "infratriaje", "sobretriaje")


def test_calidad_coherente_con_los_niveles(triaged):
    for x in triaged:
        assert (x.quality, x.jump) == triage_quality(x.level, x.true_level)


@pytest.mark.parametrize("n", [1, 3])
def test_numero_de_flujos_de_gravedad_incorrecto(profiles, n):
    with pytest.raises(ValueError, match="2"):
        SeverityTriageSampler(profiles, child_streams(SEED, n))


def test_flujos_de_gravedad_que_no_son_seed_sequence(profiles):
    with pytest.raises(ValueError, match="SeedSequence"):
        SeverityTriageSampler(profiles, [7, 1])
