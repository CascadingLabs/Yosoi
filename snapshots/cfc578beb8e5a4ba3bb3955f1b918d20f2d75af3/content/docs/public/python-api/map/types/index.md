---
title: "Types"
description: "Types declared in yosoi.map."
order: 0
---

| Name | Summary |
| --- | --- |
| [`BoundMapRequest`](/yosoi/python-api/map/types/bound-map-request/) | A discovery request bound to a serialized policy snapshot. |
| [`DiscoverySource`](/yosoi/python-api/map/types/discovery-source/) | Provenance category for a retained hostname or page. |
| [`Exploration`](/yosoi/python-api/map/types/exploration/) | Retained page exploration state, independent of discovery provenance. |
| [`FrontierEntry`](/yosoi/python-api/map/types/frontier-entry/) | Unfinished page work, without a promise of later execution. |
| [`HostEntry`](/yosoi/python-api/map/types/host-entry/) | An admitted hostname with explicit reachability evidence. |
| [`MapOutcome`](/yosoi/python-api/map/types/map-outcome/) | Bounded discovery evidence with retained acquisition owners. |
| [`MapRequest`](/yosoi/python-api/map/types/map-request/) | Authored seed intent with validation deferred to checking or sending. |
| [`MapTermination`](/yosoi/python-api/map/types/map-termination/) | Why discovery stopped, independently of individual source success. |
| [`Observation`](/yosoi/python-api/map/types/observation/) | One retained provenance observation, without a reachability guarantee. |
| [`Omission`](/yosoi/python-api/map/types/omission/) | Counted omission events, not all undiscovered site items. |
| [`OmissionReason`](/yosoi/python-api/map/types/omission-reason/) | Classification of omitted discovery evidence or exploration work. |
| [`PageEntry`](/yosoi/python-api/map/types/page-entry/) | Normalized page URL with discovery and exploration evidence. |
| [`PublicProvider`](/yosoi/python-api/map/types/public-provider/) | Anonymous historical discovery indexes with fixed endpoint shapes. |
| [`Relationship`](/yosoi/python-api/map/types/relationship/) | Directed discovery evidence without merging the endpoint pages. |
| [`RequestTrace`](/yosoi/python-api/map/types/request-trace/) | Bounded acquisition accounting retained for a Map request. |
| [`RetainedCapture`](/yosoi/python-api/map/types/retained-capture/) | An acquired response kept alive with its owning Map outcome. |
| [`SourceFailure`](/yosoi/python-api/map/types/source-failure/) | Typed acquisition or parsing failure without raw response excerpts. |
| [`SourceOutcome`](/yosoi/python-api/map/types/source-outcome/) | Execution facts for one selected discovery source. |
| [`SourceStatus`](/yosoi/python-api/map/types/source-status/) | Per-source processing state, distinct from operation termination. |
| [`Summary`](/yosoi/python-api/map/types/summary/) | Recorded resource accounting and concurrency peaks for a discovery run. |
| [`SupportDocument`](/yosoi/python-api/map/types/support-document/) | A robots or sitemap support source and its execution state. |
| [`TreeEntry`](/yosoi/python-api/map/types/tree-entry/) | A page position in the deterministic rooted discovery forest. |
| [`WildcardEntry`](/yosoi/python-api/map/types/wildcard-entry/) | A retained wildcard pattern without expansion into guessed hosts. |
