# Internal Contract validation

This private module checks extracted fields against record rules and converts
valid values into Rust types. It reports problems such as missing fields or
invalid values through the public `yosoi::contracts` namespace.
