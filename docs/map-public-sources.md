# Map public passive sources

Map uses a small fixed catalog of public indexes. The provider module only
constructs HTTPS GET URLs and parses bounded response bodies; Requests owns
network access, deadlines, cancellation, concurrency, response-byte limits, and
source URL provenance. Every hostname remains an unverified observation until
the Map admission and host-scope rules accept it. These indexes can be stale,
incomplete, duplicated, or wrong.

The catalog does not accept endpoint overrides, provider plugins, API keys,
cookies, or browser sessions. A provider response with an error, quota page,
challenge, HTML body, or unsupported shape is a typed source failure. It must
not be recorded as a completed empty result.

## Catalog

| Provider | Public index and query | Response parser | Provider coverage limit |
| --- | --- | --- | --- |
| `crtsh` | crt.sh Certificate Transparency search, `q=%.{domain}&output=json` | Existing crt.sh JSON `name_value` parser | No fixed per-query limit in this module. crt.sh can be slow or unavailable; source failures remain partial outcomes. |
| `hackertarget` | Anonymous Forward DNS hostsearch, `GET /hostsearch/?q={domain}` | Two-column `hostname,IP` rows; each address must parse as an IP literal | Vendor documents at most 50 results per request and a 20-query/day free hostsearch quota. A response at 50 rows is marked `sample_limited`. |
| `subdomaincenter` | Anonymous Subdomain Center dataset query, `GET /?domain={domain}` | JSON array of hostname strings | Anonymous results are a shuffled sample of up to 500 names, limited to 5 queries/minute per source IP. `sample_limited` is conservatively true for every parsed response because the pure body parser does not receive the `X-Truncated` response header. No live-crawl parameter is sent. |
| `waybackarchive` | Internet Archive CDX historical URL index with `matchType=domain`, `fl=original`, JSON output, `limit=1000`, and resume-key output | CDX JSON header and rows; URLs are parsed to their hostnames | A returned resume key or 1,000 rows marks `sample_limited`. |

The `CertificateNames.truncated` field reports only the local `max_entries`
retention cap. `ProviderNames.sample_limited` reports a provider-side sample or
query ceiling separately. For Subdomain Center, the API's exact `X-Truncated`
header is not observed by this body-only parser; the conservative flag records
the documented anonymous sample limit. For Wayback, the response body includes
the resume-key marker, which the parser reports.

HackerTarget's hostsearch endpoint is a public historical dataset lookup, not a
DNS resolver or a target-page request. Its rows are not proof that an address
currently resolves. Requests must stay within the source's published daily
quota. The vendor's hostsearch page documents 20 free queries/day and 50 rows
per request; its general API guide describes a 50-call/day free allowance across
tools, so Map uses the more restrictive hostsearch-specific figure.

## Concurrent admission

The default runner admits up to two provider jobs concurrently. Every request
hop reserves its request count, response extent, and trace inventory before
dispatch. Jobs wait on budget notifications when active reservations consume
the available byte extent. Cancellation and the absolute Map deadline stop
admission and drain jobs while preserving completed discoveries.

Anonymous quotas are enforced by a process-local admission gate: five queries
per minute for Subdomain Center and twenty per day for HackerTarget. Separate
CLI processes do not share that gate; providers enforce their per-IP quotas.
Rate-limited sources are reported without retry or delayed backoff.

## Provider evidence

The anonymous Subdomain Center endpoint was queried once for `example.org` on
2026-10-03. It returned HTTP 200, `application/json`, and 13,433 response bytes
within the 64 KiB cap. The observed body began as a JSON array of hostnames. The
official API documentation describes anonymous access, a randomized sample of
up to 500 names, a 5 requests/minute per-IP limit, and HTTP 429/503/504 errors.

The anonymous HackerTarget hostsearch endpoint was queried once for
`example.org` on 2026-10-03. It returned HTTP 200, `text/plain`, and 57 bytes
within the 64 KiB cap, with two `hostname,IP` rows. Its official endpoint page
documents the same CSV-like plaintext format, no-signup access, and the
hostsearch-specific query and result caps.

One bounded crt.sh query and one bounded Wayback CDX query did not produce
observable response output within the probe's 10-second timeout. They were not
retried. Both endpoints remain represented because their public query formats
are documented and their parser inputs are strictly shaped; runtime timeouts or
format errors must remain visible as per-source failures.

ProjectDiscovery Subfinder currently lists 53 sources, but that catalog includes
providers with required credentials and sources whose behavior is unsuitable
for this fixed anonymous boundary. This implementation uses its source list as
an audit index only; it does not copy or substantially adapt Subfinder code.

## Excluded sources

- CertSpotter and other providers whose current integrations require an API key,
  account, or registration are excluded. No credential configuration is
  present in Map.
- urlscan's Search API is not included because its current API reference marks
  the search endpoint as authenticated.
- RapidDNS's structured API requires a paid API key. Its anonymous results are
  HTML and need a separate document-locator path before they can be considered.
- THC's current Subfinder integration uses a POST JSON request with paging state;
  the approved `endpoint(domain) -> Url` contract represents fixed GET queries.
- SubMD has an anonymous endpoint but returns line-oriented text rather than one
  of this catalog's documented JSON, CSV, or CDX index shapes.
- AlienVault OTX was not included because current first-party documentation did
  not establish that its passive-DNS endpoint is available anonymously. The
  Subfinder no-auth integration test also lists intermittent 503 responses.

## Primary references

- [ProjectDiscovery Subfinder source catalog](https://github.com/projectdiscovery/subfinder/blob/dev/pkg/passive/sources.go)
- [ProjectDiscovery Subfinder no-auth source test and documented flaky sources](https://github.com/projectdiscovery/subfinder/blob/dev/pkg/passive/sources_wo_auth_test.go)
- [HackerTarget hostsearch endpoint and limits](https://hackertarget.com/find-dns-host-records/)
- [HackerTarget IP Tools API authentication and rate limits](https://hackertarget.com/ip-tools/)
- [A.R.P. Syndicate official API documentation](https://github.com/ARPSyndicate/docs)
- [Internet Archive Wayback CDX Server API](https://github.com/internetarchive/wayback/blob/master/wayback-cdx-server/README.md)
- [urlscan Search API authentication](https://docs.urlscan.io/apis/urlscan-openapi/search)
- [RapidDNS API authentication](https://rapiddns.io/help/api)
- [VirusTotal search API authentication](https://docs.virustotal.com/reference/api-search)
