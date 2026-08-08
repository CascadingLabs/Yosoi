# L1 source-HTML worked example — Wikipedia “Web scraping”

This example deliberately uses only static HTML. No rendered DOM, accessibility tree,
network trace, browser action, or model is involved.

## Scope

Pinned article revision:

```text
https://en.wikipedia.org/api/rest_v1/page/html/Web_scraping/1367063064
```

The article-only representation avoids using Wikipedia navigation chrome as the main example,
while remaining canonical static HTML for an immutable article revision.

```bash
uv run yosoi fetch \
  'https://en.wikipedia.org/api/rest_v1/page/html/Web_scraping/1367063064' \
  --fetcher simple \
  --view raw-html \
  --chars 1000000 \
  --output .yosoi/fetches/wikipedia-web-scraping-rest-l1/source.html \
  --json
```

Measured 2026-08-08 against the CAS-262 working copy:

| Measurement | Result |
| --- | ---: |
| Canonical source HTML | 163,164 bytes |
| Source body elements considered | 1,151 |
| Declaration elements considered | 84 |
| Combined index entries | 1,038 |
| Repeat regions | 81 |
| Structured summary bytes | 84,239 |
| Source/summary ratio | 1.94× |
| Parse + prune + compile wall time | 0.044 seconds |

The timing is one local run, not a benchmark distribution. Peak process RSS was about 60 MiB,
but that includes Python and imported libraries and is not an incremental-memory measurement.

## What parsing and pruning produce

The source contains ordinary article structure:

```html
<section>
  <h2 id="Techniques">Techniques</h2>
  <section>
    <h3 id="HTML_parsing">HTML parsing</h3>
    <p>Many websites have large collections of pages generated dynamically ...</p>
  </section>
</section>
```

The body pruner turns it into addressable entries. Selected real entries:

```text
[82]  h2#History                         History
[116] h2#Techniques                      Techniques
[150] h3#Human_copy-and-paste            Human copy-and-paste
[158] h3#HTTP_programming                 HTTP programming
[163] h3#HTML_parsing                     HTML parsing
[164] p#mwbw                              Many websites have large collections ...
[174] h3#DOM_parsing                      DOM parsing
[197] h2#Legal_issues                     Legal issues
[401] h2#Methods_to_prevent_web_scraping Methods to prevent web scraping
[402] p#mwAUY                             The administrator of a website can use ...
[477] h2#References                       References
```

This is a flat address space. The apparent heading indentation above is for readability; the
agent does not need to traverse a hierarchy before inspecting an entry.

## Worked multi-turn routing

Assume the agent asks: “What does this page say about HTML parsing and defenses against
scraping?”

### Turn 0 — bounded overview

A future renderer selects useful entries from the structured index under a hard token budget:

```text
Techniques
  HTML parsing       ref:164  Many websites have large collections of pages generated ...
  DOM parsing        ref:178  By using a program such as ...
Legal issues          ref:197
Preventing scraping  ref:402  The administrator of a website can use various measures ...
  repeated defenses  ref:419  ×2 related anti-bot list items
References            ref:477
```

The references above stand for exact `RegionRef` values, not free-form model-generated paths.

### Turn 1 — inspect exact HTML-parsing evidence

```text
inspect(ref:164, max_bytes=1200)
```

Returns exact canonical HTML beginning:

```html
<p id="mwbw">Many websites have large collections of pages generated dynamically
from an underlying structured source, like a database. Data of the same category are
typically encoded into similar pages by a common script or template. ...</p>
```

The result was exactly 1,200 bytes and explicitly reported `truncated=true`.

### Turn 2 — inspect and expand anti-bot evidence

```text
inspect(ref:402)
```

```html
<p id="mwAUY">The administrator of a website can use various measures to stop or
slow a bot. Some techniques include:</p>
```

A collapsed repeated region can be expanded separately:

```text
expand(ref:419, max_items=5)
```

```text
coverage: 2 observed / 2 declared, complete

[0] stable  Bots can sometimes be blocked with tools such as a CAPTCHA ...
[1] stable  Commercial anti-bot services ...
```

Both members resolve through unique element IDs rather than positional guesses.

## What this example proves

- Static HTML can be parsed, semantically reduced, and compiled quickly on this article.
- Headings, prose, and repeated structures receive exact snapshot-bound addresses.
- `inspect` returns bounded canonical bytes, not regenerated prose.
- `expand` pages repeated members without placing every member in the resident overview.

## What it does **not** prove yet

The current structured index is **not yet a manageable agent document**. It is 84 KiB and has
1,038 entries because unique prose is intentionally preserved and Wikipedia carries many
metadata/style declarations. `ObservationIndexRenderer` is still a scaffold.

Therefore Turn 0 above is the target rendering, not current executable output. The missing gate
is:

```text
structured index
      │
      ▼
token-budget renderer
      │
      ▼
small overview containing headings, regions, omission signals, and exact refs
```

A passing Wikipedia boss fight should require:

1. all article `h2`/`h3` sections represented in the overview;
2. selected prose and repeated-list evidence reachable in one inspection hop;
3. overview inside a declared token budget;
4. explicit indication of entries omitted from the overview;
5. exact resolution against the pinned source artifact;
6. deterministic output and measured wall time/peak memory.

Wikipedia is consequently a useful **negative control**: repeated lists should collapse, but
unique prose must not disappear merely to produce an impressive compression ratio.
