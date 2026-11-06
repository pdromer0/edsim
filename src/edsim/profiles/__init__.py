"""Clinical profiles: who arrives and why, as functions of the arrival's context.

The subpackage turns each arrival into a patient with a profile, without SimPy
and without the engine, so that it can be tested and validated on its own:

- ``config``: ``config/perfiles.toml`` as an immutable, validated object;
- ``context``: shift band, day type and season of an arrival;
- ``mixing``: the log-linear categorical, Gumbel-max and ``base_weights_for``;
- ``population``: age band, age, sex and arrival mode;
- ``severity``: latent severity, thresholds, triage with error and its exact
  matrix of true against assigned level;
- ``workup``: tests of four types, their results and turnarounds, and their
  exact shares over a year;
- ``durations``: triage, assessment and reassessment by true level and
  reason, and the exact load of the doctor;
- ``sampler``: person and reason of each arrival, with streams 5 and 6;
  severity and triage, with streams 7 and 1; tests and durations, with
  streams 3 and 2;
- ``validation``: statistical checks of the mix, the triage, the tests and
  the durations;
- ``derivation``: the cascade of derived values (base weights, noise and
  bias, thresholds) rounded as written, and the criterion that chooses the
  mean severity of a reason by its shares of level 1.

See docs/specs/hito-4.md.
"""
