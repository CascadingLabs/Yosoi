---
title: "yosoi.search"
description: "Public declarations in yosoi.search."
order: 0
---

`yosoi.search`

Provider-neutral Search forwards intent to Rust and keeps every provider slot.

[Source: python/yosoi/search.py:1](https://github.com/CascadingLabs/Yosoi/blob/57dcc790cd685fd3ed704b867f391099b748958a/python/yosoi/search.py#L1-L1)

## Types

| Name | Summary |
| --- | --- |
| [`Answer`](/yosoi/python-api/search/types/answer/) | A provider-displayed answer with reported citation destinations. |
| [`BoundSearchRequest`](/yosoi/python-api/search/types/bound-search-request/) | A request with a serialized snapshot of a complete policy declaration. |
| [`Cancelled`](/yosoi/python-api/search/types/cancelled/) | Started provider work observed caller cancellation without rollback. |
| [`ChargeAmount`](/yosoi/python-api/search/types/charge-amount/) | Provider-reported monetary amount without conversion or estimation. |
| [`Empty`](/yosoi/python-api/search/types/empty/) | A parsed provider response with no accepted results. |
| [`Failed`](/yosoi/python-api/search/types/failed/) | Started provider work ended without a usable normalized response. |
| [`ImageGallery`](/yosoi/python-api/search/types/image-gallery/) | A provider-displayed collection of image results, without an organic rank. |
| [`ImageResult`](/yosoi/python-api/search/types/image-result/) | An image destination paired with its reported hosting page. |
| [`LocalPack`](/yosoi/python-api/search/types/local-pack/) | A provider-displayed collection of local places and an optional map. |
| [`LocalPlace`](/yosoi/python-api/search/types/local-place/) | A provider-reported local place, without independent business verification. |
| [`NotStarted`](/yosoi/python-api/search/types/not-started/) | An authored provider slot retained even though no provider Request started. |
| [`ProviderCharge`](/yosoi/python-api/search/types/provider-charge/) | Reported monetary charge facts; unknown is not evidence of zero cost. |
| [`ProviderIdentity`](/yosoi/python-api/search/types/provider-identity/) | Provider and adapter identities recorded when an adapter actually ran. |
| [`ProviderResult`](/yosoi/python-api/search/types/provider-result/) | One selected provider slot, retained in authored policy order. |
| [`RequestAttemptSummary`](/yosoi/python-api/search/types/request-attempt-summary/) | A bounded summary of an underlying acquisition, including recovery attempts. |
| [`Results`](/yosoi/python-api/search/types/results/) | Usable normalized provider results whose coverage may still be partial. |
| [`SearchCoverage`](/yosoi/python-api/search/types/search-coverage/) | Independent extraction coverage for organic results and rich features. |
| [`SearchHit`](/yosoi/python-api/search/types/search-hit/) | An accepted organic result in provider order, with possible rank gaps. |
| [`SearchHitMetadata`](/yosoi/python-api/search/types/search-hit-metadata/) | Provider-displayed metadata; destination content is not fetched or verified. |
| [`SearchIssue`](/yosoi/python-api/search/types/search-issue/) | A bounded structural extraction issue without raw response excerpts. |
| [`SearchPage`](/yosoi/python-api/search/types/search-page/) | Normalized content extracted from one provider response. |
| [`SearchProfileFacts`](/yosoi/python-api/search/types/search-profile-facts/) | Content-free route-selection and effective-policy facts for one provider. |
| [`SearchRequest`](/yosoi/python-api/search/types/search-request/) | Authored query intent backed by Rust, independent of provider selection. |
| [`SearchResponse`](/yosoi/python-api/search/types/search-response/) | A cross-provider result retaining failed and unstarted slots. |
| [`SearchResultUrl`](/yosoi/python-api/search/types/search-result-url/) | An absolute HTTP(S) destination validated by Rust; no I/O occurs. |
| [`Sponsored`](/yosoi/python-api/search/types/sponsored/) | A provider placement identified as sponsored content, without an organic rank. |

## Functions

| Name | Summary |
| --- | --- |
| [`new`](/yosoi/python-api/search/functions/new/) | Author a search request without provider I/O. |

## Aliases

| Name | Summary |
| --- | --- |
| [`Provider`](/yosoi/python-api/search/aliases/provider/) | Supported provider-neutral search routes: Brave, Bing, and DuckDuckGo. Selection does not guarantee provider availability or usable results. |
| [`ProviderOutcome`](/yosoi/python-api/search/aliases/provider-outcome/) | Tagged provider result distinguishing usable results, empty response, failure, observed cancellation, and work that never started. |
| [`Rank`](/yosoi/python-api/search/aliases/rank/) | Strict one-based u16 position. Organic rank and provider placement are different coordinates and can contain gaps. |
| [`SearchFeature`](/yosoi/python-api/search/aliases/search-feature/) | Tagged rich placements separate from organic rank: sponsored content, answers, image galleries, and local packs. Reported destinations are not fetched by these values. |
