# Deterministic Fixture Generators

Generators manufacture controlled artifacts such as the network-noise traces and large DOM fixtures. Every generator must accept an explicit seed, produce byte-identical output, and emit its ground-truth sidecar separately from model-visible evidence.
