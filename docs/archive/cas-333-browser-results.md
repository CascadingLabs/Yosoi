# CAS-333 browser benchmark evidence

## Evidence classification

The retained local dashboard is under `benchmarks/results/by-change/jj/vlptrxoowyotqzzlqntwwxmzxxqwrkqn/`. Results are machine-specific review evidence, not universal performance thresholds.

The initial native Criterion/allocation group used Yosoi snapshot `78ca8f3562e8710728bf87666de9d0c8cbac61dd`. The 560-attempt native headless process soak used snapshot `c9e32cd939df7ff6c962d7af225644ad2abc87a3` because adapter corrections landed between measurement classes. These groups are useful but must not be compared as one atomic source snapshot.

A later all-four-environment stable-snapshot run was explicitly interrupted by the maintainer and atomically published no result. The completed one-iteration container matrices are retained separately and share Yosoi source hash `633fc8b6a95eab6139e3d2474cf5f9559b48c779fae12950b9a39c618de67343`, provider source hash `e44e7f5b67c43f248a2425e43bfbf8d063c4c7f8f775375542e1384df5c3f719`, build hash `2e21bd8931529aa0fc60cfaadef36eeadf255b97685568b284467fe5978745c9`, and image `sha256:c0b2eb6bdf42a07c18f4b1b72dc3c33e8aaea740ea1687d2e883cb2a7529b487`.

## Native Criterion

All 18 expected combinations completed: capture to staged facts, setup-excluded Yosoi finalization, and end-to-end capture for minimal/full/growth fixtures in headless and headful modes.

Representative medians:

- browser/provider capture: roughly 0.66–1.08 seconds;
- end-to-end capture plus finalization: roughly 0.68–1.06 seconds;
- setup-excluded finalization: about 28 microseconds minimal, 0.10–0.12 milliseconds full, and 0.77–0.80 milliseconds growth.

Headful browser work was generally slower than headless. Ten samples per estimate and observed outliers make small percentage changes unreliable. Browser lifecycle dominates; Yosoi finalization is several orders of magnitude smaller.

## Native process soak

The native headless matrix retained 12 cells and 560 attempts: success, request-confirmed cancellation, bounded deadline, and partial-disconnect failure at concurrency 1, 2, and 4.

Every cell reported:

- process status zero;
- zero finalization failures;
- no cleanup timeout;
- zero remaining/orphan PIDs after cleanup grace.

The largest observed concurrency-4 diagnostic peaks were approximately 1.50 GiB PSS, 6.22 million KiB summed RSS, 61 processes, 2,662 file descriptors, and 742 tasks. Summed RSS double-counts shared pages; PSS is the more useful process-tree memory estimate. Peaks are independently sampled and are not necessarily simultaneous.

## Container matrices

Both `container-headless` and Sway/Wayland `container-headful` completed 12 full-seven-family cells and 28 attempts each at concurrency 1, 2, and 4. Every run had container exit zero, finalization `ok`, attempt cleanup `Complete`, cgroup disappearance, and zero residual labelled containers.

The hardened runtime used UID/GID 10001, `--network none`, a read-only root filesystem, capability drop ALL, no-new-privileges, the reviewed seccomp profile, Chrome sandbox enabled, 1 GiB shared memory, 4 GiB memory/swap limit, 2 CPUs, and a 1,024 PID limit.

Observed one-iteration matrix peaks:

- container headless: about 1.32 GB cgroup memory and 787 PIDs/tasks;
- container headful: about 1.41 GB cgroup memory and 838 PIDs/tasks;
- cancellation-return p99: up to 1.82 seconds headless and 0.72 seconds headful in these samples.

These are functional operating-envelope probes, not stable quantile baselines. Container cgroup metrics and native PID-tree metrics are different scopes and must not be directly substituted.

## Allocation evidence

Divan separates allocation operations, initially allocated bytes, grown bytes, total allocated bytes, and maximum live bytes on the synchronous benchmark thread. Browser process memory is not included.

Payload cloning uses one allocation proportional to exact byte size. SHA-256 stages allocate no payload copy. Structured evidence serialization/deserialization scales with AX bytes and network/runtime event counts; the growth-aware normalizer includes realloc growth rather than reporting only the initial allocation.

## Initial review alerts

For matching environment and source identities:

- any finalization failure, cleanup timeout, remaining process/cgroup/container, nonzero status, or attempt-count mismatch is an immediate correctness alert;
- provider or end-to-end median change above 25%, or a fully displaced Criterion estimate interval, requires review;
- setup-excluded finalization requires review at 2x or +100 microseconds;
- any allocation-count increase, or total/max-live byte increase above 15%, requires review;
- process/cgroup memory, PID, FD, task, CPU, or IO movement above 30% requires review but is not an automatic failure.

Repeated identical-snapshot runs are required before converting these alerts into enforced thresholds.

## Advantages and disadvantages

Advantages: deterministic loopback inputs; explicit provider/finalization separation; exact artifact and source identity; native whole-process-tree and container whole-cgroup scopes; post-ownership cancellation; zero-tolerance cleanup evidence; rootless networkless container execution matching the intended server deployment style.

Disadvantages: fresh Chromium lifecycle dominates latency and process resources; native headful depends on compositor behavior; container builds coordinate two source trees; browser timings are noisy; canonical evidence entails copying/hashing/serialization; current local VoidCrawl path prevents final clean-pin certification.
