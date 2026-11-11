"""One physical-location reducer shared by episode cards and replay checkpoints."""

from dataclasses import dataclass, replace
from typing import Literal

from edsim.engine.events import Event

EpisodeState = Literal[
    "waiting_triage",
    "triage",
    "waiting_box",
    "waiting_doctor",
    "assessment",
    "waiting_tests",
    "reassessment",
    "waiting_bed",
]


@dataclass(frozen=True, slots=True)
class LocationState:
    """Complete immutable continuation flags, including independent lab work.

    ``in_results_room`` is set by ``box_released`` (task 4.6a: the patient left
    its box to wait for its results outside) and cleared by the next
    ``box_assigned``.

    With version 4 (task 5.4, H5-11): ``bed_requested`` is set by
    ``bed_requested`` (the state is ``waiting_bed`` from then on), ``hallway``
    by a displacement while waiting for a bed (the patient waits in the
    hallway, without a box), and ``left`` by ``patient_left_wbs``, the closing
    of an abandonment, told apart from ``departed``.
    """

    triage_started: bool = False
    triaged: bool = False
    box: int | None = None
    assessment: str | None = None
    tests_pending: bool = False
    departed: bool = False
    in_results_room: bool = False
    bed_requested: bool = False
    hallway: bool = False
    left: bool = False

    def apply(self, event: Event) -> "LocationState":
        """Return the next flags without changing this state or the event."""
        match event.event_type:
            case "triage_started":
                return replace(self, triage_started=True)
            case "triage_completed":
                return replace(self, triaged=True)
            case "box_assigned":
                return replace(self, box=event.payload["box"], in_results_room=False)
            case "box_released":
                return replace(self, box=None, in_results_room=True)
            case "assessment_started":
                return replace(self, assessment=event.payload["tipo"])
            case "assessment_ended":
                return replace(self, assessment=None)
            case "test_ordered":
                return replace(self, tests_pending=True)
            case "test_resulted":
                return replace(self, tests_pending=False)
            case "patient_displaced":
                return replace(self, box=None, hallway=self.bed_requested)
            case "patient_departed":
                return replace(self, departed=True, box=None, hallway=False)
            case "bed_requested":
                return replace(self, bed_requested=True)
            case "patient_left_wbs":
                return replace(self, left=True, box=None)
        return self

    @property
    def closed(self) -> bool:
        """Whether the episode ended: departed or, in version 4, left without being seen."""
        return self.departed or self.left

    @property
    def results_room(self) -> bool:
        """Whether the patient is out of its box between its two box stays (task 4.8a).

        True from its ``box_released`` to its next ``box_assigned``: waiting for
        its results (``waiting_tests``) and then waiting for a box again
        (``waiting_box``). The state does not change; this flag tells the
        results room apart from the box and from the first wait for a box.
        """
        return self.in_results_room

    def location(self) -> EpisodeState:
        """Prefer physical box waiting to independent tests after displacement.

        A patient in the results room waits for its tests without a box
        (``waiting_tests`` with ``box`` None); once its results are in, it
        waits for a box like anyone else. The room is told apart by
        ``results_room``, not by a state of its own (task 4.8a).

        An admitted patient waits for its bed (``waiting_bed``) in its box or,
        after a displacement, in the hallway, told apart by ``hallway`` (H5-11),
        as the results room.
        """
        if not self.triage_started:
            return "waiting_triage"
        if not self.triaged:
            return "triage"
        if self.bed_requested:
            return "waiting_bed"
        if self.box is None:
            if self.in_results_room and self.tests_pending:
                return "waiting_tests"
            return "waiting_box"
        if self.assessment is not None:
            return "assessment" if self.assessment == "inicial" else "reassessment"
        if self.tests_pending:
            return "waiting_tests"
        return "waiting_doctor"
