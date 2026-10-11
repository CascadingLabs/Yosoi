# Yielding under I/O load

Source: `af6b86fb517fbd35b25e1da14a6a3263f127f4e9`  
Browser: Google Chrome 154.0.8037.57 ;image=sha256:355aa95235603948f766f946efbfc4f4f2a54c923d161abdb7adca4d34596537  
Controller/schema: chromiumoxide 0.9.1; CDP 0.10.0-yosoi.m153.1  
Framework: htmx 2.0.11  
Input SHA-256: `4255d17381f53e9a8d9648f69f35fcca83f832c821b56a34fde5101ba1bcc4f4`

Each policy uses an owned browser with the same tab/worker limits. Startup is separate; the first round is an excluded warmup. Values below are warm medians, with batch ranges in parentheses. This measures batch throughput and responsiveness under I/O load, not faster individual actions.

| Scenario | Retain worker: batch seconds | Yield: batch seconds | Completed jobs/s: retain / yield | Later-job submission to service: retain / yield seconds |
| --- | --- | --- | --- | --- |
| one-tab | 1.32 (1.27–1.38) | 1.42 (1.30–1.47) | 0.755 / 0.704 | unavailable / unavailable |
| four-tabs-one-worker | 5.89 (5.48–6.49) | 5.87 (5.69–7.53) | 0.679 / 0.681 | 2.88 / 3.22 |
| four-tabs-two-workers | 6.27 (5.42–7.13) | 4.69 (4.27–6.63) | 0.638 / 0.853 | 3.22 / 1.87 |
| four-tabs-four-workers | 4.70 (4.70–5.09) | 4.62 (4.59–5.52) | 0.851 / 0.865 | 1.59 / 2.19 |
| simultaneous-arrival | 6.08 (5.67–6.32) | 6.23 (5.10–6.88) | 0.658 / 0.642 | 3.49 / 3.88 |
| no-service-wait | 6.08 (5.00–6.46) | 5.10 (4.53–6.50) | 0.658 / 0.785 | 3.40 / 3.03 |
| two-browser-processes | 7.96 (7.48–8.54) | 7.85 (6.95–9.13) | 0.503 / 0.510 | 3.75 / 4.14 |
| slow-htmx-four-tabs | 20.90 (20.39–21.23) | 11.03 (10.62–11.48) | 0.191 / 0.363 | 10.30 / 1.51 |
| slow-htmx-eight-tabs | 24.84 (24.50–25.33) | 18.70 (18.38–19.28) | 0.322 / 0.428 | 11.77 / 5.35 |
| htmx-backend-bottleneck | 13.07 (12.88–13.42) | 12.12 (12.04–12.23) | 0.306 / 0.330 | 6.17 / 1.65 |

## Sampled memory

| Scenario | Cgroup MiB: retain / yield | Chrome PSS MiB: retain / yield | SDK RSS MiB: retain / yield |
| --- | --- | --- | --- |
| one-tab | 450.52 / 448.61 | 722.44 / 710.40 | 32.86 / 32.96 |
| four-tabs-one-worker | 638.67 / 637.46 | 832.43 / 828.23 | 33.47 / 33.90 |
| four-tabs-two-workers | 639.56 / 620.18 | 830.13 / 806.04 | 33.90 / 33.90 |
| four-tabs-four-workers | 637.47 / 625.41 | 830.00 / 811.52 | 33.91 / 33.94 |
| simultaneous-arrival | 635.18 / 633.18 | 826.76 / 806.56 | 33.94 / 34.04 |
| no-service-wait | 648.42 / 607.68 | 816.73 / 795.58 | 34.04 / 34.04 |
| two-browser-processes | 1058.38 / 1104.11 | 1190.73 / 1188.85 | 34.04 / 34.14 |
| slow-htmx-four-tabs | 703.77 / 661.43 | 776.86 / 797.41 | 34.14 / 34.14 |
| slow-htmx-eight-tabs | 779.34 / 743.91 | 830.29 / 848.92 | 34.16 / 34.55 |
| htmx-backend-bottleneck | 647.14 / 684.57 | 781.03 / 796.61 | 34.55 / 34.55 |

Memory is sampled every 100 ms plus a final sample. Cgroup usage includes SDK, browser, cache and kernel charges; Chrome PSS and SDK RSS use different accounting and must not be subtracted from it. Shared file charges can reside outside a container. These measurements do not establish a universal memory increase or decrease. Three repeats and fixed policy order are preliminary evidence, not a statistically controlled performance ranking.

Admission here includes navigation/setup and controller queues: it is the server-observed request timestamp minus the application submission timestamp, not a pure semaphore timing. A constrained upstream or browser HTTP/1 connection pool can limit throughput even when controller slots are available. Foreground input and screenshot capture remain serialized by the browser surface lock.
