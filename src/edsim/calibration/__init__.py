"""Calibration of the base center against observed Spanish data (milestone 4).

- ``targets``: ``config/objetivos.toml`` as validated ``Target`` objects;
- ``staffing``: the rule of the equivalent staff, ⌈load of the shift / u⌉,
  with one u per knob (triage nurses and doctors);
- ``evaluate``: replications with common random numbers, the comparison of
  each target with its band, the days out of it, the sensitivity of a knob
  and the choice of a staffing;
- ``report``: the tables and CSV files of ``edsim calibracion``.

See docs/specs/hito-4.md, "Calibración".
"""
