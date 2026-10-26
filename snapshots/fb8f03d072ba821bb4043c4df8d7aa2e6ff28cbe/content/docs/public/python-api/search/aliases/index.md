---
title: "Aliases"
description: "Aliases declared in yosoi.search."
order: 0
---

| Name | Summary |
| --- | --- |
| [`Provider`](/yosoi/python-api/search/aliases/provider/) | Supported provider-neutral search routes: Brave, Bing, and DuckDuckGo. Selection does not guarantee provider availability or usable results. |
| [`ProviderOutcome`](/yosoi/python-api/search/aliases/provider-outcome/) | Tagged provider result distinguishing usable results, empty response, failure, observed cancellation, and work that never started. |
| [`Rank`](/yosoi/python-api/search/aliases/rank/) | Strict one-based u16 position. Organic rank and provider placement are different coordinates and can contain gaps. |
| [`SearchFeature`](/yosoi/python-api/search/aliases/search-feature/) | Tagged rich placements separate from organic rank: sponsored content, answers, image galleries, and local packs. Reported destinations are not fetched by these values. |
