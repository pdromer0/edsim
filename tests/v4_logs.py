"""Logs a mano de la versión 4 para los tests de la tarea 5.4.

`HandLog` apunta los eventos paciente a paciente, cada uno con su instante, y los emite en
orden de tiempo con un `EventLog` de la versión 4. Los del mismo instante salen en el orden
en que se apuntaron, así que, como en el motor, el evento que libera un box se apunta
antes que el que lo recibe. El episodio del paciente `who` es `EP-{who:06d}`: los números
van en orden de llegada, como en el motor.

Los payloads clínicos son fijos (mujer de 50 años, motivo «otros»): las métricas de la 5.4
no los leen.
"""

from edsim.engine.events import (
    DOOR,
    NURSE,
    OUTCOME_SCHEMA_VERSION,
    WARD,
    Event,
    EventLog,
    MemorySink,
)
from edsim.engine.scenarios import SCENARIO_START


def episode(who: int) -> str:
    """El episode_id del paciente `who`."""
    return f"EP-{who:06d}"


class HandLog:
    """Eventos apuntados por paciente y emitidos en orden de tiempo (estable en los empates)."""

    def __init__(self) -> None:
        self._items: list[tuple[float, int, str, int | None, dict]] = []

    def add(self, t: float, kind: str, who: int | None = None, **payload: object) -> "HandLog":
        self._items.append((float(t), len(self._items), kind, who, payload))
        return self

    def arrive(self, who: int, t: float) -> "HandLog":
        self.add(t, "patient_arrived", who, medio="propios_medios")
        return self.add(t, "patient_registered", who, edad=50, sexo="mujer")

    def triage(self, who: int, start: float, end: float, level: int, door: bool = False):
        self.add(start, "triage_started", who, circuito=DOOR if door else NURSE)
        return self.add(end, "triage_completed", who, nivel=level, motivo="otros")

    def box(self, who: int, t: float, number: int) -> "HandLog":
        return self.add(t, "box_assigned", who, box=number)

    def assess(self, who: int, start: float, end: float, number: int, tipo: str = "inicial"):
        self.add(start, "assessment_started", who, tipo=tipo, pool="medicos", box=number)
        return self.add(end, "assessment_ended", who, tipo=tipo, interrumpida=False)

    def depart(self, who: int, t: float, destino: str = "alta") -> "HandLog":
        """Decisión y salida en el mismo instante: alta, traslado o exitus."""
        self.add(t, "disposition_decided", who, destino=destino)
        return self.add(t, "patient_departed", who, destino=destino)

    def admit(self, who: int, decision: float, bed: float) -> "HandLog":
        """Ingreso: decisión y pedido de cama en `decision`; cama y salida en `bed`."""
        self.add(decision, "disposition_decided", who, destino="ingreso")
        self.add(decision, "bed_requested", who, servicio=WARD)
        self.add(bed, "bed_assigned", who, servicio=WARD)
        return self.add(bed, "patient_departed", who, destino="ingreso")

    def leave(self, who: int, t: float, espera: str) -> "HandLog":
        return self.add(t, "patient_left_wbs", who, espera=espera)

    def displace(self, who: int, t: float, number: int, by: int) -> "HandLog":
        return self.add(t, "patient_displaced", who, box=number, desalojado_por=episode(by))

    def staff(self, t: float, resource: str, before: int, after: int) -> "HandLog":
        return self.add(t, "staffing_changed", recurso=resource, anterior=before, nueva=after)

    def events(self, run_id: str = "rmano") -> list[Event]:
        """Los eventos, emitidos en orden de tiempo con un EventLog de la versión 4."""
        sink = MemorySink()
        log = EventLog(run_id, SCENARIO_START, sink, schema_version=OUTCOME_SCHEMA_VERSION)
        for t, _, kind, who, payload in sorted(self._items, key=lambda item: item[:2]):
            log.emit(kind, t, arrival_id=who, **payload)
        return sink.events
