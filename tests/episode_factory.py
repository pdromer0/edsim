"""Auxiliares de la tarea 5.7: episodios y verdades escritos a mano para los tests.

`episode` devuelve un `EpisodeRecord` con solo lo que las funciones de cierre del flujo
leen; `truth_of` devuelve un sustituto del `EpisodeTruth` con el nivel real, la gravedad G, la
paciencia y el destino sorteado, que es todo lo que esas funciones piden del ground truth.
"""

from types import SimpleNamespace

from edsim.engine.analysis import EpisodeRecord


def episode(
    who,
    arrival,
    *,
    left=None,
    assessment=None,
    level=4,
    departure=None,
    destination=None,
    clock_a=None,
):
    """Un EpisodeRecord mínimo; el reloj A sale de la primera valoración salvo que se dé."""
    wait = clock_a if clock_a is not None else None if assessment is None else assessment - arrival
    return EpisodeRecord(
        episode_id=f"EP-{who:06d}",
        arrival=arrival,
        triage_start=None,
        triage_end=None,
        level=level,
        first_box=None,
        first_assessment=assessment,
        decision=None,
        departure=departure,
        destination=destination,
        displacements=0,
        triage_wait=None,
        box_wait=None,
        doctor_wait=None,
        initial_doctor_wait=None,
        door_to_doctor=wait,
        triage_start_to_doctor=None,
        classified_to_doctor=None,
        initial_box_wait=None,
        results_box_wait=None,
        left=left,
    )


def truth_of(patience=0.0, true_level=4, destination="alta", severity=0.0):
    """Lo que las funciones de cierre leen del ground truth de un episodio."""
    return SimpleNamespace(
        clinical=SimpleNamespace(triage=SimpleNamespace(true_level=true_level, severity=severity)),
        outcome=SimpleNamespace(patience=patience, destination=destination),
    )
