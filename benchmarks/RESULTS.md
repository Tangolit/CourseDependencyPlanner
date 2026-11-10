# Measured Scheduling Benchmarks

These are actual local measurements, not illustrative estimates. The complete inputs, all 70 measured
samples, returned assignments, objective values/bounds, environment metadata and source fingerprints
are published in [the raw JSON report](results/windows-ryzen5850u.json).

## Environment

- Measured November 9, 2026, 19:46:41-19:47:39 America/New_York; raw timestamps are UTC.
- Windows 11, build 26200; AMD Ryzen 7 PRO 5850U, 8 cores / 16 logical CPUs.
- CPython 3.14.3; OR-Tools 9.15.6755; `PYTHONHASHSEED=0`.
- CP-SAT uses one search worker and random seed zero. No GPU is used.
- Measured code revision: [`ab8a096`](https://github.com/Tangolit/CourseDependencyPlanner/commit/ab8a096f702d5a8c5bfe8dfcb0f601dacc672244).
  The raw report also hashes the benchmark driver and every scheduling/domain source it uses, with LF-normalized text.

## Results

Each row contains **five measured runs**, following one excluded warmup for that case and strategy.
Latency is milliseconds, measured around the full `scheduler.solve()` call. Strategy order alternates
between trials. No failures or timeouts are discarded. Plan size is **courses / planning terms**;
empty waiting terms count. A dash means no complete plan was returned, not a zero-course solution.

| Case | Strategy | Median (ms) | Min-max (ms) | Outcomes | Plan courses / terms |
| --- | --- | ---: | --- | --- | --- |
| 20-course layered | Greedy | 37.788 | 31.543-43.438 | feasible 5/5 | 20 / 5 |
| 20-course layered | Constraint | 2071.341 | 2063.640-2080.245 | feasible 5/5 | 9 / 6 |
| 50-course layered | Greedy | 43.191 | 40.365-51.786 | feasible 5/5 | 49 / 10 |
| 50-course layered | Constraint | 2131.781 | 2127.632-2156.015 | feasible 5/5 | 24 / 6 |
| 100-course layered | Greedy | 103.603 | 98.918-106.440 | no_plan 5/5 | - |
| 100-course layered | Constraint | 2303.884 | 2258.992-2324.279 | feasible 5/5 | 58 / 16 (4 runs); 59 / 12 (1 run) |
| 200-course layered | Greedy | 387.912 | 357.832-445.144 | no_plan 5/5 | - |
| 200-course layered | Constraint | 2548.431 | 2534.871-2581.978 | unknown 5/5 | - |
| AND/OR + offerings | Greedy | 0.500 | 0.344-0.570 | feasible 5/5 | 5 / 5 |
| AND/OR + offerings | Constraint | 15.747 | 15.004-16.675 | optimal 5/5 | 5 / 5 |
| Credit-infeasible | Greedy | 0.233 | 0.168-0.261 | no_plan 5/5 | - |
| Credit-infeasible | Constraint | 5.548 | 4.822-7.155 | infeasible 5/5 | - |
| Cycle-infeasible | Greedy | 0.049 | 0.042-0.149 | infeasible 5/5 | - |
| Cycle-infeasible | Constraint | 12.878 | 10.069-15.480 | infeasible 5/5 | - |

All **35 complete measured plans** passed independent schedule verification. The tests also reconstruct
and reverify those published assignments and recompute every JSON summary from its raw samples.

### Interpretation

The faster greedy strategy trades solution quality and success rate for speed. Its bounded logical
closure search can hit its 50,000-state limit, fall back to broad candidates, and take unnecessary
prerequisite branches. That explains the larger 20- and 50-course plans; it is not a pure topological-sort baseline.

The constraint solver found much smaller plans at 20 and 50 courses, and found plans at 100 courses
when greedy packing failed. **None of the layered constraint results is proven optimal within this
budget.** The 200-course result is inconclusive: no plan was returned before the time limit, and
infeasibility was not proven. This is a measured limitation, not a successful scalability claim.

The configured priority is fewest courses, then earliest finish, then balanced workload. Thus a
58-course/16-term incumbent is preferred to a 59-course/12-term incumbent. These are observed plans,
not optimum bounds on course count. `no_plan` means heuristic packing failed; `unknown` means the
constraint search was inconclusive; `infeasible` is a proof for the modeled constraints. Greedy can
prove logical infeasibility in the cycle case before packing, but its credit-cap packing failure
alone is not a proof.

## Workloads And Timing

Layered cases are deterministic synthetic DAGs, not students' course records. For size `N`, width is
`max(2, N // 5)`. The first width courses have no prerequisites. Each later course requires either
course `index - width` or `index - width + 1`; all IDs refer to earlier nodes. The final width courses
are mandatory targets. All `N` courses are relevant to the targets.

Each layered course has three credits and difficulty three. There are no completed or excluded
courses. Offerings are unconstrained. Limits are 16 credits per term, two difficult courses per term,
16 Fall/Winter terms, and two seconds of solver search. The objective is `fewest_courses`.

The six-course AND/OR case requires a foundation AND one of two alternatives, followed by a
Winter-only course and a Fall-only target. It uses six planning terms, a seven-credit cap and at most
one difficult course per term. The remaining cases isolate a 20-credit mandatory course exceeding a
16-credit cap, and a two-course cycle with no OR escape. Exact catalogs and requests are in the raw JSON.

Timing uses `time.perf_counter_ns`. It includes model construction, prerequisite selection, search,
and result assembly. Dependency imports, warmups, verification, JSON output, HTTP and rendering are
excluded. The two-second search limit is **not an end-to-end latency cap**, which is why full
constraint calls can exceed 2000 ms. Every feasible/optimal warmup is verified too; invalid output
aborts the run instead of producing a successful benchmark record.

These are steady-state measurements on one interactive workstation, with no CPU pinning, process
isolation or power controls. Five samples are not a confidence interval, and the smallest cases are
especially sensitive to timer/scheduling overhead. Memory usage, cold starts, API throughput and
larger catalogs were not measured. Wall-clock limits can change incumbents across repetitions even
with a fixed solver seed. No latency claim or performance threshold is enforced by CI.

## Reproduce

From the repository root, with dependencies installed:

```powershell
$env:PYTHONHASHSEED = '0'
.\.venv\Scripts\python.exe -m benchmarks.schedule_benchmark --sizes 20 50 100 200 --seconds 2 --repeats 5 --warmups 1 --machine-label 'AMD Ryzen 7 PRO 5850U; 8 cores / 16 logical CPUs' --output benchmark-results.json
```

On macOS/Linux, replace the executable and machine label appropriately:

```sh
PYTHONHASHSEED=0 .venv/bin/python -m benchmarks.schedule_benchmark --sizes 20 50 100 200 --seconds 2 --repeats 5 --warmups 1 --output benchmark-results.json
```

The root output file is ignored, so rerunning does not overwrite the published measurement.
Expect different timings on other machines. Use a new raw result file and report the environment
when publishing another run; do not replace failed outcomes with successful reruns.
