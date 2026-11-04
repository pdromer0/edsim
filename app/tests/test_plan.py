"""Inspect SVG structure and supplied counts using hand-written states."""

from dataclasses import replace
from datetime import date
from xml.etree import ElementTree as ET

from edsim.runs import ReplayCounts, ReplayDisplacement, ReplayPatient, ReplayState
from edsim_app.palette import LEVEL_COLORS
from edsim_app.plan import render_plan

NS = {"s": "http://www.w3.org/2000/svg"}


def patient(number, level=3, state="waiting_box", box=None, arrival=None):
    return ReplayPatient(
        f"EP-{number:06d}",
        f"PT-{number:06d}",
        float(number if arrival is None else arrival),
        level,
        state,
        box,
    )


def state(patients=(), displacements=(), t=100):
    return ReplayState(
        t,
        tuple(patients),
        {"medicos": 2, "enfermeria_triaje": 2},
        (),
        tuple(displacements),
        (),
        {"alta": 4, "ingreso": 2},
    )


def counts(**changes):
    values = dict(
        census=50,
        waiting_triage=41,
        waiting_box=42,
        nurses_busy=0,
        doctors_busy=0,
        boxes_busy=5,
        nurses_staff=2,
        doctors_staff=2,
        boxes=8,
    )
    return ReplayCounts(**(values | changes))


def draw(value, counters=None, highlight=None):
    return ET.fromstring(
        render_plan(
            value, counters or counts(), start_date=date(2026, 1, 5), highlighted_episode=highlight
        )
    )


def elements(svg, role):
    return svg.findall(f'.//*[@data-role="{role}"]', NS)


def test_one_box_per_capacity_and_every_level_color():
    svg = draw(state(patient(n, n, "waiting_doctor", n) for n in range(1, 6)))
    assert [int(e.attrib["data-box"]) for e in elements(svg, "box")] == list(range(1, 9))
    for p in elements(svg, "patient"):
        level = int(p.attrib["data-episode"][-1])
        assert p.find("s:rect", NS).attrib["fill"] == LEVEL_COLORS[level]
    text = " ".join(svg.itertext())
    assert "5 / 8" in text and "Alta: 4" in text and "Ingreso: 2" in text


def test_queue_priority_arrival_cap_and_authoritative_totals():
    people = [patient(n, (n % 5) + 1, arrival=100 - n) for n in range(40)]
    people += [patient(n + 100, None, "waiting_triage", arrival=100 - n) for n in range(40)]
    svg = draw(state(people))
    for role, expected in (
        ("box-queue", sorted(people[:40], key=lambda p: (p.level, p.arrival, p.episode_id))),
        ("triage-queue", sorted(people[40:], key=lambda p: (p.arrival, p.episode_id))),
    ):
        queue = elements(svg, role)[0]
        visible = elements(queue, "patient")
        assert [p.attrib["data-episode"] for p in visible] == [p.episode_id for p in expected[:30]]
        assert "+10 más" in " ".join(queue.itertext())
    # The supplied values differ deliberately from the lists: drawing must not count.
    assert "Total: 41" in " ".join(svg.itertext())
    assert "Total: 42" in " ".join(svg.itertext())


def test_displaced_patient_and_old_box_have_distinct_marks_and_titles():
    displacement = ReplayDisplacement("EP-000001", 50, 1, "EP-000002")
    for p in (patient(1), patient(1, state="waiting_doctor", box=3)):
        svg = draw(
            state((p, patient(2, 1, "assessment", 1)), (displacement,)), highlight=p.episode_id
        )
        marked_box = svg.find('.//*[@data-mark="displaced-box"]', NS)
        assert marked_box.attrib["stroke-dasharray"] == "6 4"
        assert elements(svg, "box")[0].find('.//*[@data-mark="displaced-box"]', NS) is not None
        glyph = next(p for p in elements(svg, "patient") if p.attrib["data-episode"] == "EP-000001")
        mark = glyph.find('.//*[@data-mark="displaced-patient"]', NS)
        assert mark.attrib["stroke"] == "#c62828" and "stroke-dasharray" not in mark.attrib
        assert glyph.find('.//*[@data-mark="highlight"]', NS) is not None
        titles = " ".join(e.text or "" for e in svg.findall(".//s:title", NS))
        assert "00:50:00" in titles and "desalojado_por: EP-000002" in titles and "box 1" in titles
        old = draw(state((p,), (displacement,), t=111))
        assert old.find('.//*[@data-mark="displaced-box"]', NS) is None
        assert old.find('.//*[@data-mark="displaced-patient"]', NS) is None


def test_only_current_staff_posts_plus_explicit_finishing_attention():
    people = [patient(n, state="triage") for n in range(3)]
    people += [patient(n + 3, state="assessment", box=n + 1) for n in range(3)]
    svg = draw(state(people), counts(nurses_busy=3, doctors_busy=3))
    for pool in ("nurses", "doctors"):
        posts = elements(svg, f"{pool}-post")
        assert len(posts) == 2 and all(p.attrib["data-occupied"] == "true" for p in posts)
        finishing = elements(svg, f"{pool}-finishing")
        assert len(finishing) == 1 and "Terminando atención" in " ".join(finishing[0].itertext())
        assert "nadie se interrumpe" in " ".join(finishing[0].itertext())
    assert "3 / 2" in " ".join(svg.itertext())


def test_untrusted_text_is_escaped_and_no_patient_level_is_invented():
    p = replace(patient(1, level=None, state="waiting_triage"), episode_id='EP-<&"')
    svg = draw(state((p,)))
    assert elements(svg, "patient")[0].attrib["data-episode"] == p.episode_id
    assert not svg.findall(".//s:script", NS)


def test_wait_chart_uses_the_same_level_palette():
    import pandas as pd

    from edsim_app.charts import waits_chart

    frame = pd.DataFrame(
        {
            "Nivel": list(range(1, 6)),
            "Puerta-médico media (min)": [1] * 5,
            "Puerta-médico p90 (min)": [2] * 5,
            "Máximo Manchester (min)": [0, 10, 60, 120, 240],
        }
    )
    spec = waits_chart(frame).to_dict()
    assert spec["encoding"]["color"]["field"] == "Nivel"
    assert spec["encoding"]["color"]["scale"] == {
        "domain": list(LEVEL_COLORS),
        "range": list(LEVEL_COLORS.values()),
    }
    assert spec["encoding"]["shape"]["field"] == "Serie"
