# CAS-294 reference scenarios

Status: design and future implementation fixtures

Linear: [CAS-294](https://linear.app/cascadinglabs/issue/CAS-294/define-bounded-capture-windows-and-termination-outcomes)

## Why these scenarios exist

The observation-window model must eventually survive both deterministic tests and changing public websites. Public sites provide realism but are unsuitable as required CI dependencies. Controlled pages provide repeatability but cannot reveal every production behavior. Yosoi should use both.

## Primary real-world scenario: discover a Yahoo Finance quote recipe

Goal: discover and later replay a recipe that extracts the current AAPL price, currency, market state, and observation time.

A plausible run might look like this:

```text
0 ms      document navigation begins
180 ms    initial HTML arrives
420 ms    first paint exposes the page shell
700 ms    quote data appears in a network response
950 ms    accessibility data exposes the quote
1.1 s     rendered DOM displays a validated price
1.2 s     the discovery controller has sufficient evidence and stops
ongoing   advertisements, analytics, and unrelated page activity continue
```

These exact timings and sources are hypotheses to validate with the future collector, not assertions about Yahoo's current implementation. The important model result is independent of the exact sequence:

```json
{
  "termination": {
    "outcome": "controller_stopped",
    "evidence": "goal_satisfied"
  },
  "window": {
    "elapsed": 1200000
  },
  "terminal_state": {
    "observed_through": 1200000,
    "events": {
      "admitted": 860,
      "retained": 860,
      "dropped": { "status": "known", "value": 0 }
    },
    "bytes": {
      "admitted": 240000,
      "retained": 240000,
      "dropped": { "status": "known", "value": 0 }
    },
    "in_flight": {
      "total": 14,
      "settlement_relevant": 0
    }
  }
}
```

The capture does not claim that Yahoo Finance settled. It claims that the controller obtained enough evidence while other activity remained in flight.

A configured elapsed deadline is the instant when the future coordinator must request termination, not permission to rewrite the measured duration. Already-running work may yield and terminal accounting may finish slightly later, so a deadline outcome can honestly record actual elapsed time greater than its configured deadline. Event and byte admission limits remain strict because the coordinator can stop admitting more data; time already spent cannot be undone.

Discovery might compile the observations into a deterministic recipe:

```text
1. Inspect embedded quote data after the initial response.
2. Otherwise inspect matching quote API responses.
3. Otherwise wait for the validated quote DOM or accessibility field.
4. Race those conditions against a three-second deadline.
5. Ignore advertisement and analytics activity for readiness.
6. Escalate to rediscovery if the extracted fields fail validation.
```

The contract states what quote fields mean. The recipe states how and when to acquire them. The capture records evidence from discovery or replay.

### Model pressure exercised

- useful evidence before global settlement;
- multiple possible evidence sources;
- controller-directed successful completion;
- background in-flight activity at termination;
- relative timing;
- changing values that cannot be golden-tested literally;
- consent, geography, bot-defense, or markup variation;
- bounded failure when the expected field never appears.

### Live-canary assertions

A public-site canary should assert durable properties rather than a specific price or selector:

- the observation terminates within its declared deadline;
- every terminal outcome is valid and fully accounted;
- any reported quote satisfies structural validation;
- a missing quote remains explicit rather than becoming an empty value;
- dropped-data availability is explicit;
- retained artifacts identify their acquisition environment and producer.

The canary should not block ordinary CI when the public site is unavailable, changed, rate-limited, or protected by a bot challenge.

## Static baseline: example.com

`https://example.com/` provides a simple public baseline:

- one small document;
- no application framework;
- no expected long-lived activity;
- useful content in the initial response;
- a quiet-period outcome should be possible.

It exercises the opposite end of the model from Yahoo Finance. Five-second and ten-second policies must remain distinguishable even if both settle much earlier.

This public dependency should still be treated as a canary. A locally controlled equivalent should supply deterministic CI coverage.

## Advanced scenario: advertisement discovery

Goal: discover an advertisement token and destination URL on a page whose main content is already usable.

Potential complications include:

- the advertisement arriving after first paint;
- an iframe or different browsing context;
- a consent action creating another interaction epoch;
- a network response containing the token before the DOM does;
- rotating creatives invalidating an earlier candidate;
- unrelated continuous DOM and network activity;
- no advertisement for the current geography or profile.

This scenario tests whether observation can continue across agent actions and turns without conflating page readiness, advertisement readiness, and global settlement.

## Deterministic local stress pages

Future collector work should create controlled pages for required CI behavior:

| Page | Behavior | Expected model pressure |
| --- | --- | --- |
| `static` | Immediate fixed content | Early quiet settlement |
| `late-field` | Required field appears after a timer | Controller waits only for relevant evidence |
| `heartbeat-network` | Endless polling or stream | Valid deadline with in-flight activity |
| `unrelated-dom-churn` | Advertisement or clock mutates continuously | Relevant quiet despite global mutation |
| `progressive-ax` | Accessibility representation expands in stages | Snapshot/checkpoint revision handling |
| `candidate-replaced` | Early candidate is later replaced | Provisional evidence and invalidation |
| `event-flood` | Events exceed a configured count | Exact event-limit outcome and loss accounting |
| `byte-flood` | Body exceeds a byte budget | Exact byte-limit outcome and truncation |
| `disconnect` | Producer closes unexpectedly | Interrupted outcome with reason and in-flight state |

These pages should use ordinary web-platform behavior and should not encode provider-specific assumptions into the domain fixtures.

## Test pyramid

### 1. Type and invariant tests

Small hand-authored values cover every valid outcome and contradictory wire state. These tests belong in required CI and do not start a browser.

### 2. Recorded event-log fixtures

Future real captures can be sanitized into versioned traces. Deterministic replay tests then exercise projection, checkpointing, termination, gaps, and recipe behavior without contacting a third party.

Fixtures derived from public sites should record source URL, acquisition date, environment, transformation notes, and content-safety decisions. They should avoid retaining unnecessary third-party or personal data.

### 3. Controlled browser integration tests

Local stress pages validate the future collector and controller under real browser scheduling while retaining deterministic content and timing bounds.

### 4. Public canaries

Example.com provides a minimal canary. Yahoo Finance or a similarly dynamic site provides a changing adversarial canary. Failures are research signals requiring classification, not automatically product regressions.

## Initial implementation sequence

1. Implement CAS-294 terminal types and invariants without a browser runtime.
2. Hand-author JSON fixtures representing the static and never-settling cases.
3. Define typed artifact families before committing to event payload schemas.
4. Implement a minimal collector against controlled local pages.
5. Capture and sanitize representative dynamic traces.
6. Add non-blocking public canaries.
7. Benchmark binary framing and compression using observed event distributions rather than synthetic assumptions alone.
