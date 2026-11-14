"""The bronze layer: what arrives from Kafka, kept in Postgres as it came (milestone 7).

The Postgres client is the optional ``postgres`` extra. Only ``edsim.store.postgres`` uses it,
and it imports the client inside the functions that connect, so every module of the package
imports without it. ``bronze`` turns a message into a row, ``migrations`` creates the tables
and ``consumer`` is the loop from Kafka to bronze, with its clients injected.
"""
