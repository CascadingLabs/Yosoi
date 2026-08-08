# Observation Pruning — design plan

Sets the shape for every modality pruner, not just HTML. Written before the body reducer
exists, because the part that is expensive to change later is the **address**, not the
reduction.

Context: CAS-262 (L1 static HTML), CAS-263 (L2 DOM/AX), CAS-266 (L0 network).
Kernel contracts live in `yosoi/observations/`; corpus design in `observations/boss_fights.md`.

## 1. What we are building for

Multi-shot QA and discovery. The loop is:

```text
index → zoom → (act / scroll) → re-index → diff
```

Not one-shot extraction. That single fact reprices the prior art, and it is the reason
this document exists before the code does.

### What the literature still tells us

| Result | Transfers? | Why |
| --- | --- | --- |
| Flat XPath→text beat nested JSON on extraction F1 (0.96 vs 0.40) — NEXT-EVAL, arXiv:2505.17125 | **Weakly** | Measures one-shot extraction with the page in context. Our index deliberately cannot extract; it routes. Wrong objective. |
| Nested JSON hallucinated 60% of addresses | **Partially** | In a multi-shot loop a hallucinated address is *recoverable* — `inspect` fails closed, the agent retries. It is a wasted hop, not a wrong answer. Cost, not disqualifier. |
| Stripping class/id/style was the *worst* input (F1 0.10, 91% hallucination) | **Fully** | This is about element *identity*, which addressing needs regardless of shot count. Classes and ids are also the raw material Yosoi selectors are made of. **Do not strip them.** |
| Second routing level hurt retrieval, 0.91 → 0.64 — arXiv:2607.17598 | **Fully** | Measures routing, which is exactly our objective. |
| MDR / DEPTA repeated-record mining (2003–2011) | **Fully, repurposed** | Their weakness as *extractors* (recall-first, "extracts all potential records") is a virtue in a *compressor*. |
| DAG / TreeRePair grammar tree compression; XPath over compressed trees (arXiv:1311.5573) | **Fully** | Repeat-once-then-reference is the formalism, and addressability provably survives it. |
| D2Snap DOM downsampling | **Gap** | Explicitly does not handle repeated siblings or large tables — the exact case we care about. |

Net: take the *record-mining* line for finding repeats, take the *flat-emission* discipline
for the surface, ignore the one-shot F1 numbers, and never strip identifying attributes.

## 2. The crux: an address must outlive its snapshot

Today's locator is an absolute XPath (`/html/body/div[2]/table/tbody/tr[3]`). That is a
correct address *within one snapshot* and a silently wrong one across snapshots:

- scroll a virtualized list and `tr[3]` is a different row;
- expand an accordion and every following sibling index shifts;
- a diff between two snapshots then compares two addresses that changed meaning without
  changing text.

Everything downstream — `index/diff.py`, action episodes, discovery reuse, trust tiers —
inherits this. It is the one decision worth spending the ticket on.

### Proposed two-level address

Mirrors what the spike already proved and what `ys.Contract` already means by root:

```text
region   = path to the repeat container   ← SelectorEntry.root; spike's record_unit()
member   = region + content key           ← spike's unique_attr_selector()
```

- **Region** is the container whose children repeat. It survives scroll, paging, and
  re-render because the container is what the page keeps.
- **Member** is keyed by a stable attribute (`id`, `data-*`, a unique attribute) or a text
  digest — *not* an ordinal. When nothing stable exists, fall back to an ordinal and
  **say so in the address**, so a consumer can tell a durable reference from a positional
  guess rather than discovering it during a diff.

This is also what makes a pruned index useful to discovery: a region address *is* a
candidate `SelectorEntry.root`.

## 3. Zoom is scoped re-pruning, not byte slicing

`ObservationInspector.inspect` currently returns the serialized subtree. For a collapsed
`×10 000` group that is either one row or forty megabytes — neither is a zoom.

Native zoom means **re-running the reduction rooted at a reference, one level deeper**:

| Verb | Input | Returns |
| --- | --- | --- |
| `inspect(ref)` | any address | bounded canonical detail for one thing |
| `expand(region_ref, offset, limit)` | a region address | a page of member addresses + summaries |

Both are one hop and both are bounded. `expand` is what makes the 10 000-row case
navigable instead of merely small.

## 4. Scroll is an episode, not a bigger snapshot

Already modelled: `ObservationSnapshot.parent_snapshot_id` and `episode_id`. Pruners stay
pure and single-snapshot; the episode lives above them. Two consequences:

- `index/diff.py` compares indexes across snapshots — which only works if §2 holds.
- A single snapshot of a virtualized list **must report incompleteness**. Today
  `PrunedView` has nowhere to say "20 members observed, container declares ~10 000", so an
  incomplete region is indistinguishable from a complete one. `boss_fights.md` gate 8
  requires exactly this ("missing modalities are explicit capabilities, never empty
  evidence"); the same rule has to apply *within* a modality.

## 5. Pruner shape

- `pruning/_base.py` — `SemanticPruner` template method owns digest validation, policy
  hashing, addressing, budget capping, and omission accounting. A pruner is one `reduce`
  returning ordered `PruneCandidate`s plus the population it considered.
- Identity triple `name` / `version` / `evidence_kind` is the registry pattern; no mutable
  global registry, callers pass pruners explicitly.
- Head and body are **separate pruners over the same artifact** — `html.head` indexes flat
  declarations, `html.body` indexes nested structure. Different reductions, different
  versions, different gates. The compiler already merges views over one artifact.
- Body reduction: MDR-style contiguous repeated-sibling detection over skeleton
  signatures, emitting *container + exemplar + count + sampled varying text*. Never N
  entries. Non-contiguous/interleaved records are DEPTA's job and are recorded as an
  asserted limit, not silently mishandled.

## 6. Sequence

1. **Now (CAS-262):** base class, head/body split, MDR collapse, **and the address scheme**.
   The address is why this is one ticket and not three.
2. Completeness reporting on `PrunedView` (§4) — needs a frozen-model field.
3. `expand` on the inspection surface (§3).
4. `index/diff.py` over stable addresses; episodes.
5. DOM/AX pruners reusing the same base, address scheme, and gates.

## Open

- Ordinal fallback: mark in-band in the locator, or as a separate flag on the fragment?
- Does `expand` land in CAS-262 or after the DOM pruner gives it a second consumer?
