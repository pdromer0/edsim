"""Clinical profiles: who arrives and why, as functions of the arrival's context.

The subpackage turns each arrival into a patient with a profile, without SimPy
and without the engine, so that it can be tested and validated on its own:

- ``config``: ``config/perfiles.toml`` as an immutable, validated object;
- ``context``: shift band, day type and season of an arrival;
- ``mixing``: the log-linear categorical, Gumbel-max and ``base_weights_for``;
- ``population``: age band, age, sex and arrival mode;
- ``sampler``: person and reason of each arrival, with streams 5 and 6;
- ``validation``: statistical checks of the mix.

See docs/specs/hito-4.md.
"""
