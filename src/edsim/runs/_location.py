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
]


@dataclass(frozen=True, slots=True)
class LocationState:
    """Complete immutable continuation flags, including independent lab work.

    ``in_results_room`` is set by ``box_released`` (task 4.6a: the patient left
    its box to wait for its results outside) and cleared by the next
    ``box_assigned``.
    """

    triage_started: bool = False
    triaged: bool = False
    box: int | None = None
    assessment: str | None = None
    tests_pending: bool = False
    departed: bool = False
    in_results_room: bool = False

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
                return replace(self, box=None)
            case "patient_departed":
                return replace(self, departed=True, box=None)
        return self

    def location(self) -> EpisodeState:
        """Prefer physical box waiting to independent tests after displacement.

        A patient in the results room waits for its tests without a box
        (``waiting_tests`` with ``box`` None); once its results are in, it
        waits for a box like anyone else. A distinct state for the room is
        pending for tasks 4.8a and 4.8b.
        """
        if not self.triage_started:
            return "waiting_triage"
        if not self.triaged:
            return "triage"
        if self.box is None:
            if self.in_results_room and self.tests_pending:
                return "waiting_tests"
            return "waiting_box"
        if self.assessment is not None:
            return "assessment" if self.assessment == "inicial" else "reassessment"
        if self.tests_pending:
            return "waiting_tests"
        return "waiting_doctor"
