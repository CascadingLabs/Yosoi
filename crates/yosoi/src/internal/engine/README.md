# Internal Yosoi engine

This private module connects Yosoi's core features so applications can fetch
pages, find information in documents, search the web, and discover website
pages. It applies the chosen limits and keeps evidence of the results.

Applications use the public `yosoi` facade. The engine module is an
implementation detail shared with the SDK and optional CLI binary.
