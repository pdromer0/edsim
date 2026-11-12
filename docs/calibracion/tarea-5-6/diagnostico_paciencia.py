"""Diagnóstico de la paciencia (tarea 5.6, pedido de Pedro del 12 de noviembre).

El protocolo de la rejilla: ventana anual (12 réplicas de 14 días, 2 de calentamiento y el de
vaciado), semilla 2026, cama m = 210 y la plantilla de la 4.6c; cada réplica se reduce con
replica_values (los objetivos de config/objetivos.toml) y, para el nivel real y el tiempo
hasta irse, con la tabla y el ground truth de esa misma réplica. Solo funciones públicas.

Uso, desde la raíz del repositorio:
  uv run python docs/calibracion/tarea-5-6/diagnostico_paciencia.py SALIDA.txt

Los boxes y la cama de cada caso se fijan aquí; el resto del centro es el de config/.
"""

import dataclasses
import sys

import numpy as np

from edsim.arrivals.profile import load_profile
from edsim.arrivals.rate import MINUTES_PER_DAY as DAY
from edsim.calibration.evaluate import DRAIN_DAYS, replica_values, summarize_targets
from edsim.calibration.knobs import bed_wait_center, scaled_patience
from edsim.calibration.targets import load_targets
from edsim.calibration.window import first_mondays, with_start_date
from edsim.engine.analysis import episode_table
from edsim.engine.center import load_center
from edsim.engine.engine import simulate_ed
from edsim.engine.events import MemorySink
from edsim.profiles.config import load_profiles
from edsim.runs import true_level_abandonment
from edsim.seeds import child_streams

BASE_CENTER = load_center("config/centro.toml")
# La paciencia de partida (k = 1): config/perfiles.toml ya lleva k = 4, y su bloque de
# partida es el del ejemplo del hito 5, valor a valor (test_la_paciencia_es_la_de_partida_por_k).
BASE_PROFILES = load_profiles("tests/data/perfiles_h5_ejemplo.toml")
ARRIVALS = load_profile("config/llegadas.toml")
TARGETS = load_targets("config/objetivos.toml")
NAMES = ("abandono", "tiempo_medico_niveles_2_5", "estancia_ingresados", "pretriaje_medio")


def with_shape(profiles, ratio):
    """La paciencia de partida con p90 = ratio × mediana (solo diagnóstico)."""
    outcome = profiles.outcome
    patience = tuple((m, ratio * m) for m, _ in outcome.abandonment.patience)
    abandonment = dataclasses.replace(outcome.abandonment, patience=patience)
    return dataclasses.replace(
        profiles, outcome=dataclasses.replace(outcome, abandonment=abandonment)
    )


def measure(label, boxes, k, ratio=3):
    center = dataclasses.replace(bed_wait_center(BASE_CENTER, 210), boxes=boxes)
    profiles = BASE_PROFILES if ratio == 3 else with_shape(BASE_PROFILES, ratio)
    profiles = scaled_patience(profiles, k)
    replicas, leave_times = [], []
    true_left, true_n = np.zeros(5), np.zeros(5)
    for child, monday in zip(child_streams(2026, 12), first_mondays(2026), strict=True):
        sink = MemorySink()
        result = simulate_ed(
            center, with_start_date(ARRIVALS, monday), 14 + DRAIN_DAYS, child, sink=sink,
            warmup_days=2, profiles=profiles,
        )  # fmt: skip
        table = episode_table(sink.events)
        replicas.append(replica_values(table, TARGETS, 2, 14))
        start, end = 2 * DAY, 14 * DAY
        leave_times += [e.time_to_leave for e in table if start <= e.arrival < end and e.left]
        by_id = {t.episode_id: t for t in result.ground_truth.episodes}
        tl = true_level_abandonment(table, by_id, start, end)
        true_left += [x.left for x in tl.by_level]
        true_n += [x.arrivals for x in tl.by_level]
    results = {r.target.name: r for r in summarize_targets(replicas, TARGETS)}
    cells = "; ".join(
        f"{n} {r.mean:.2f} [{r.summary.ci_low:.2f}, {r.summary.ci_high:.2f}]"
        f" {'pasa' if r.passed else 'FALLA'}"
        for n in NAMES
        for r in (results[n],)
    )
    by_true = " / ".join(
        f"{100 * a / b:.2f}" if b else "—" for a, b in zip(true_left, true_n, strict=True)
    )
    p10, p50, p90 = np.percentile(leave_times, [10, 50, 90])
    box = np.nanmean([r.box_wait for r in replicas])
    doctor = np.nanmean([r.doctor_wait for r in replicas])
    return (
        f"{label}: boxes {boxes}, k {k}, p90 = {ratio} × mediana\n"
        f"  {cells}\n"
        f"  abandono por nivel real 1 a 5: {by_true} % ({int(true_left.sum())} se van)\n"
        f"  tiempo desde la llegada hasta irse: p10 {p10:.1f}, p50 {p50:.1f}, p90 {p90:.1f} min"
        f" (media {np.mean(leave_times):.1f}; {100 * np.mean(np.array(leave_times) <= 30):.1f} %"
        f" en 30 min o menos)\n"
        f"  box / médico (2 a 5): {box:.2f} / {doctor:.2f} min\n"
    )


cases = [
    ("1a", 36, 1.0),
    ("1b", 36, 3.364),
    ("1c", 36, 4.0),
    ("2", 36, 2.0),
    ("3", 36, 1.0, 2),
    ("4a", 30, 1.0),
    ("4b", 30, 3.364),
    ("4c", 30, 4.0),
    ("3 con 30 boxes", 30, 1.0, 2),
]
with open(sys.argv[1], "w", encoding="utf-8") as out:
    for case in cases:
        text = measure(*case)
        print(text, flush=True)
        out.write(text + "\n")
