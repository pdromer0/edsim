"""Clinical profiles: who arrives and why, as functions of the arrival's context.

The subpackage turns each arrival into a patient with a profile, without SimPy
and without the engine, so that it can be tested and validated on its own:

- ``config``: ``config/perfiles.toml`` as an immutable, validated object;
- ``context``: shift band, day type and season of an arrival;
- ``mixing``: the log-linear categorical, Gumbel-max and ``base_weights_for``;
- ``population``: age band, age, sex and arrival mode;
- ``severity``: latent severity, thresholds, triage with error and its exact
  matrix of true against assigned level;
- ``sampler``: person and reason of each arrival, with streams 5 and 6, and
  severity and triage, with streams 7 and 1;
- ``validation``: statistical checks of the mix and of the triage.

See docs/specs/hito-4.md.
"""
