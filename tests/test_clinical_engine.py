"""El motor con perfiles clínicos: tubería, payloads del catálogo 2 y franja del pedido.

Tarea 4.5a (docs/specs/hito-4.md). Sin perfiles el motor es el del hito 3; sus huellas
están en test_engine.py y test_cli_characterization.py y no cambian.
"""

import dataclasses
import hashlib
import json
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path

import pytest
from clinical_factory import (
    clinical_log,
    expected_turnaround,
    hand_patient,
    ordered_of,
)

from edsim.arrivals.profile import load_profile
from edsim.arrivals.thinning import ArrivalRecord, iter_arrivals
from edsim.engine.center import load_center
from edsim.engine.clinical_sampler import ClinicalSampler
from edsim.engine.engine import N_CLINICAL_STREAMS, run_engine, simulate_ed
from edsim.engine.events import CATALOG_V2, JsonlSink, MemorySink
from edsim.engine.ground_truth import EpisodeTruth
from edsim.engine.invariants import check_invariants
from edsim.profiles.config import load_profiles
from edsim.profiles.context import context_indices
from edsim.seeds import child_streams

DATA = Path(__file__).parent / "data"
SEED = 2026
DAYS = 3


@pytest.fixture(scope="module")
def center():
    return load_center(DATA / "centro_ejemplo.toml")


@pytest.fixture(scope="module")
def arrival_profile():
    return load_profile(DATA / "llegadas_ejemplo.toml")


@pytest.fixture(scope="module")
def profiles():
    return load_profiles(DATA / "perfiles_ejemplo.toml")


def run(center, arrival_profile, profiles, days=DAYS, seed=SEED):
    sink = MemorySink()
    result = simulate_ed(center, arrival_profile, days, seed, sink=sink, profiles=profiles)
    return sink.events, result


@pytest.fixture(scope="module")
def clinical(center, arrival_profile, profiles):
    return run(center, arrival_profile, profiles)


def by_episode(events):
    out = defaultdict(dict)
    for e in events:
        if e.episode_id is not None:
            out[e.episode_id].setdefault(e.event_type, e)
    return out


# --- Llegadas y tubería -----------------------------------------------------------


def test_las_llegadas_son_las_del_provisional(center, arrival_profile, clinical):
    # Las llegadas usan el hijo 0, que es el mismo con 5 y con 8 flujos: idénticas
    # bit a bit, y los mismos días.
    events, result = clinical
    sink = MemorySink()
    provisional = simulate_ed(center, arrival_profile, DAYS, SEED, sink=sink)

    def arrivals(episodes):
        return [(e.episode_id, e.arrival_id, e.arrival_time.hex()) for e in episodes]

    assert arrivals(result.ground_truth.episodes) == arrivals(provisional.ground_truth.episodes)
    assert result.ground_truth.days == provisional.ground_truth.days

    def logged(events):
        return [e.sim_time.hex() for e in events if e.event_type == "patient_arrived"]

    assert logged(events) == logged(sink.events)


def test_el_motor_es_una_tuberia(arrival_profile, profiles, center, clinical):
    # El ground truth de simulate_ed es el ClinicalSampler aplicado a iter_arrivals
    # con los mismos flujos: el motor no añade ni cambia sorteos.
    _, result = clinical
    streams = child_streams(SEED, N_CLINICAL_STREAMS)
    sampler = ClinicalSampler(profiles, arrival_profile.start_date, center, streams[1:])
    expected = [
        EpisodeTruth.from_draws(a, sampler(a))
        for a in iter_arrivals(arrival_profile, DAYS, streams[0])
    ]

    assert list(result.ground_truth.episodes) == expected
    assert all(e.clinical is not None and e.test_turnaround is None for e in expected)


def test_misma_semilla_mismo_log_y_misma_verdad(center, arrival_profile, profiles, clinical):
    events, result = clinical
    again_events, again = run(center, arrival_profile, profiles)

    assert again_events == events
    assert again.ground_truth == result.ground_truth


def test_el_log_es_de_la_version_2(clinical):
    events, _ = clinical
    assert {e.schema_version for e in events} == {2}


def test_profiles_y_sampler_a_la_vez(center, arrival_profile, profiles):
    with pytest.raises(ValueError, match="sampler or profiles"):
        simulate_ed(
            center,
            arrival_profile,
            DAYS,
            SEED,
            sink=MemorySink(),
            profiles=profiles,
            sampler=lambda arrival: None,
        )


# --- Otra plantilla: mismos pacientes, respuesta con la franja de su pedido -----------

OTHER_DAYS = 14


@pytest.fixture(scope="module")
def two_staffings(center, arrival_profile, profiles):
    more_doctors = dataclasses.replace(center, doctors=(14, 14, 8))
    return (
        run(center, arrival_profile, profiles, days=OTHER_DAYS),
        run(more_doctors, arrival_profile, profiles, days=OTHER_DAYS),
    )


def observed_rounds(events):
    """Por episodio, el instante del pedido y la respuesta observada."""
    episodes = by_episode(events)
    return {
        ep: (got["test_ordered"].sim_time, got["test_resulted"].sim_time)
        for ep, got in episodes.items()
        if "test_resulted" in got
    }


def test_otra_plantilla_mismos_pacientes(two_staffings, arrival_profile, profiles):
    (_, base), (_, other) = two_staffings

    # Ningún sorteo del paciente depende de la plantilla.
    assert other.ground_truth.episodes == base.ground_truth.episodes


def test_otra_plantilla_cada_respuesta_con_la_franja_de_su_pedido(
    two_staffings, arrival_profile, profiles
):
    # La respuesta esperada se calcula con expected_turnaround, el mismo cálculo
    # independiente que la invariante clínica (context_indices y los factores), nunca
    # con ClinicalDraws.round_turnaround: así este test no comparte un error de
    # ClinicalDraws (versiones incorrectas V7 y V10).
    start = arrival_profile.start_date
    order_bands = []
    other_band_than_arrival = 0
    for events, result in two_staffings:
        truth = {e.episode_id: e for e in result.ground_truth.episodes}
        rounds = observed_rounds(events)
        bands = {}
        for ep, (ordered_at, resulted_at) in rounds.items():
            workup = truth[ep].clinical.workup
            expected = expected_turnaround(profiles, start, workup, ordered_at)
            assert resulted_at - ordered_at == pytest.approx(expected, abs=1e-8), ep
            with_arrival_band = expected_turnaround(profiles, start, workup, truth[ep].arrival_time)
            other_band_than_arrival += abs(expected - with_arrival_band) > 1e-6
            (band,), _, _ = context_indices([ordered_at], start, profiles.shift_band_starts)
            bands[ep] = int(band)
        order_bands.append(bands)

    # Guardas: el caso «otra franja en el pedido» ocurre. Hay pacientes cuya respuesta
    # con la franja del pedido no es la de la franja de su llegada, y pacientes cuya
    # franja del pedido cambia con la plantilla.
    assert other_band_than_arrival > 0
    common = order_bands[0].keys() & order_bands[1].keys()
    assert sum(order_bands[0][ep] != order_bands[1][ep] for ep in common) > 0


# --- Escenarios a mano ------------------------------------------------------------------


def hhmm(h: int, m: int) -> float:
    return 60.0 * h + m


def run_hand(center, patients: dict[float, object], days: int = 1):
    """El motor con pacientes clínicos a mano, uno por instante de llegada."""
    log, sink = clinical_log()
    arrivals = [ArrivalRecord(k, t) for k, t in enumerate(patients)]
    draws = dict(enumerate(patients.values()))
    result = run_engine(center, arrivals, lambda a: draws[a.arrival_id], log, days)
    return sink.events, result


def test_el_factor_es_el_de_la_franja_del_pedido(center, profiles):
    # Llega a las 14:00 (mañana), acaba el triaje a las 14:20 y la valoración a las
    # 15:10: la analítica se pide de tarde y tarda 75 × 1,1 = 82,5, no 75.
    patient = hand_patient(profiles, triage=20.0, assessment=50.0, ordered=ordered_of("analitica"))
    events, _ = run_hand(center, {hhmm(14, 0): patient})
    got = by_episode(events)["EP-000000"]

    assert got["test_ordered"].sim_time == hhmm(15, 10)
    assert got["test_resulted"].sim_time - got["test_ordered"].sim_time == pytest.approx(
        82.5, abs=1e-9
    )


@pytest.fixture(scope="module")
def payload_scenario(center, profiles):
    # Todo de mañana, de 9:00 a 9:20, y cada ronda acaba antes de las 15:00.
    patients = {
        # De puerta, con analítica (alterada) y ECG.
        hhmm(9, 0): hand_patient(
            profiles,
            level=1,
            reason="parada",
            age=82,
            female=False,
            ambulance=True,
            ordered=ordered_of("analitica", "ecg"),
            abnormal=(True, False, False, False),
        ),
        # Enfermería, nivel 3, con analítica y ECG (el ECG alterado).
        hhmm(9, 5): hand_patient(
            profiles,
            level=3,
            reason="dolor_toracico",
            age=58,
            ordered=ordered_of("analitica", "ecg"),
            abnormal=(False, False, True, False),
        ),
        # Enfermería, nivel 4, sin ronda.
        hhmm(9, 10): hand_patient(profiles, level=4, reason="traumatismo", age=23, female=False),
        # Crítico infratriado: real 1, asignado 2; va a enfermería, con imagen.
        hhmm(9, 15): hand_patient(
            profiles,
            level=2,
            true_level=1,
            reason="disnea",
            age=71,
            ambulance=True,
            ordered=ordered_of("imagen"),
        ),
        # Sobretriado: real 2, asignado 1; va a la puerta, sin ronda.
        hhmm(9, 20): hand_patient(profiles, level=1, true_level=2, reason="sincope", age=67),
    }
    events, result = run_hand(center, patients)
    return by_episode(events), result


EXPECTED_PAYLOADS = {
    "EP-000000": {
        "patient_arrived": {"medio": "ambulancia"},
        "patient_registered": {"edad": 82, "sexo": "hombre"},
        "triage_started": {"circuito": "puerta"},
        "triage_completed": {"nivel": 1, "motivo": "parada"},
        "test_ordered": {"pruebas": ("analitica", "ecg")},
        "test_resulted": {"resultados": {"analitica": "alterado", "ecg": "normal"}},
    },
    "EP-000001": {
        "patient_arrived": {"medio": "propios_medios"},
        "patient_registered": {"edad": 58, "sexo": "mujer"},
        "triage_started": {"circuito": "enfermeria"},
        "triage_completed": {"nivel": 3, "motivo": "dolor_toracico"},
        "test_ordered": {"pruebas": ("analitica", "ecg")},
        "test_resulted": {"resultados": {"analitica": "normal", "ecg": "alterado"}},
    },
    "EP-000002": {
        "patient_arrived": {"medio": "propios_medios"},
        "patient_registered": {"edad": 23, "sexo": "hombre"},
        "triage_started": {"circuito": "enfermeria"},
        "triage_completed": {"nivel": 4, "motivo": "traumatismo"},
    },
    "EP-000003": {
        "patient_arrived": {"medio": "ambulancia"},
        "patient_registered": {"edad": 71, "sexo": "mujer"},
        "triage_started": {"circuito": "enfermeria"},
        "triage_completed": {"nivel": 2, "motivo": "disnea"},
        "test_ordered": {"pruebas": ("imagen",)},
        "test_resulted": {"resultados": {"imagen": "normal"}},
    },
    "EP-000004": {
        "patient_arrived": {"medio": "propios_medios"},
        "patient_registered": {"edad": 67, "sexo": "mujer"},
        "triage_started": {"circuito": "puerta"},
        "triage_completed": {"nivel": 1, "motivo": "sincope"},
    },
}


@pytest.mark.parametrize("episode", sorted(EXPECTED_PAYLOADS))
def test_payloads_del_catalogo_2_a_mano(payload_scenario, episode):
    got, _ = payload_scenario
    events = got[episode]
    expected = EXPECTED_PAYLOADS[episode]

    for event_type, payload in expected.items():
        assert events[event_type].payload == payload, event_type
    # Sin ronda no hay pedido ni resultado; los demás eventos llevan su payload del hito 3.
    assert ("test_ordered" in events) == ("test_ordered" in expected)
    assert "patient_departed" in events
    assert events["disposition_decided"].payload == {"destino": "alta"}


def test_el_escenario_de_payloads_es_de_manana(payload_scenario, profiles):
    # Guarda del escenario: pedidos y resultados antes de las 15:00, así que la franja
    # del pedido y la de la llegada coinciden.
    got, _ = payload_scenario
    times = [
        e.sim_time
        for events in got.values()
        for name, e in events.items()
        if name in ("test_ordered", "test_resulted")
    ]
    assert len(times) == 6
    assert max(times) < hhmm(15, 0)


def test_la_puerta_es_del_nivel_asignado(payload_scenario):
    got, _ = payload_scenario
    # El infratriado (real 1, asignado 2) espera a la enfermera; el sobretriado
    # (real 2, asignado 1) se clasifica en la puerta.
    assert got["EP-000003"]["triage_started"].payload["circuito"] == "enfermeria"
    assert got["EP-000004"]["triage_started"].payload["circuito"] == "puerta"
    assert (
        got["EP-000004"]["triage_completed"].sim_time
        == got["EP-000004"]["patient_arrived"].sim_time
    )


# --- Nada oculto en el log ------------------------------------------------------------


def test_ningun_payload_lleva_un_valor_oculto(clinical):
    # Lo oculto (G, z, respuestas) son floats: el log clínico no lleva ninguno, y solo
    # usa claves del catálogo 2.
    events, _ = clinical
    for e in events:
        assert set(e.payload) == set(CATALOG_V2[e.event_type].payload)
        for value in e.payload.values():
            assert type(value) is not float, (e.event_type, value)


# El CSV del ground truth clínico (tarea 4.5b) se prueba en test_clinical_csv.py.


# --- Invariantes -----------------------------------------------------------------------

CONFIG = Path(__file__).resolve().parents[1] / "config"


@pytest.mark.parametrize(
    ("folder", "center_file", "arrivals_file", "profiles_file"),
    [
        (CONFIG, "centro.toml", "llegadas.toml", "perfiles.toml"),
        (DATA, "centro_ejemplo.toml", "llegadas_ejemplo.toml", "perfiles_ejemplo.toml"),
    ],
    ids=["config", "tests-data"],
)
def test_invariantes_sin_violaciones_con_el_clinico(
    folder, center_file, arrivals_file, profiles_file
):
    # 14 días con 2 de calentamiento: ninguna invariante violada, con el ground truth,
    # los procesos vivos y los perfiles (la respuesta de cada ronda con su franja).
    center = load_center(folder / center_file)
    profiles = load_profiles(folder / profiles_file)
    sink = MemorySink()
    result = simulate_ed(
        center,
        load_profile(folder / arrivals_file),
        14,
        SEED,
        sink=sink,
        warmup_days=2,
        profiles=profiles,
    )

    assert (
        check_invariants(
            sink.events,
            center,
            ground_truth=result.ground_truth,
            inside=result.inside,
            profiles=profiles,
        )
        == []
    )
    # Guardas: hay triajes de puerta, rondas y resultados que comprobar.
    types = [e.event_type for e in sink.events]
    assert types.count("test_resulted") > 1000
    assert (
        sum(
            e.event_type == "triage_started" and e.payload["circuito"] == "puerta"
            for e in sink.events
        )
        >= 10
    )


# --- Huellas del modelo clínico --------------------------------------------------------

# Huellas SHA-256 del modelo clínico con el centro, las llegadas y los perfiles de
# ejemplo, semilla 2026 y 3 días: el log (eventos.jsonl) y el ground truth, una línea
# JSON por episodio (abajo). Se regeneran solo a propósito, con un cambio de los
# muestreadores o de ClinicalTruth explicado en el commit; nunca para que un test pase.
# La representación del ground truth es la de este test: el formato estable será el CSV
# clínico de la tarea 4.5b. Generadas en la tarea 4.5a (1ee7e1ba… y c4f2c069…) y
# regeneradas en la fase A de la 4.6a: la parada al 0,3 % con gravedad 4,21 y 0,25 y la
# cascada rederivada (pesos base, ruido y umbrales) cambian el motivo, el nivel y las
# pruebas de algunos pacientes.
CLINICAL_LOG_FINGERPRINT = "c1e44ab71806bb6783338e7c359d0bfc4d076cd690017eb273afd27fc403c10f"
CLINICAL_TRUTH_FINGERPRINT = "106179101b404bbb2c19aaef41c2a2c08946b60a055e69e7eeadb5ffdcfcf6a2"


def truth_lines(episodes) -> str:
    """El EpisodeTruth entero de cada episodio, en el orden de sus campos, una línea JSON."""
    return "".join(
        json.dumps(asdict(e), ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n"
        for e in episodes
    )


def test_huella_del_log_clinico(center, arrival_profile, profiles, tmp_path):
    path = tmp_path / "eventos.jsonl"
    with JsonlSink(path) as sink:
        simulate_ed(center, arrival_profile, DAYS, SEED, sink=sink, profiles=profiles)

    assert hashlib.sha256(path.read_bytes()).hexdigest() == CLINICAL_LOG_FINGERPRINT


def test_huella_del_ground_truth_clinico(clinical):
    _, result = clinical
    text = truth_lines(result.ground_truth.episodes)

    assert text.count("\n") == len(result.ground_truth.episodes) == 1101
    assert hashlib.sha256(text.encode("utf-8")).hexdigest() == CLINICAL_TRUTH_FINGERPRINT
