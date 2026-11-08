"""Live mode: publish the engine's events in real time (milestone 6).

The Kafka client is an optional extra. Only ``edsim.live.kafka`` uses it, and it imports the
client inside the functions that need it, so every module of the package imports without it.
"""
