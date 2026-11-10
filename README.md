# Course Dependency Planner

A local Flask application for editing prerequisite graphs and generating semester-by-semester plans.
The existing Michigan course catalog and completion statuses stay in `data/courses.json`.
Planning is read-only; downloading a plan never changes course statuses.

[Measured benchmark results](benchmarks/RESULTS.md) include repeated timings, solver outcomes,
hardware/software details, full synthetic inputs and raw samples.

## Run Locally

Python 3.11-3.14 is supported. On Windows PowerShell, no global `pip` command or virtual-environment activation is needed:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

On macOS/Linux:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python app.py
```

Open `http://127.0.0.1:5000`. Keep the development server bound to localhost.
Graph libraries load from CDN, so the graph requires an internet connection.

## Planning

Select targets in **Semester Planner**. Courses tagged `target course` are selected initially.
All selected targets are mandatory goals. Completed statuses count as prior credit; current/planned/interested statuses do not.
You can optionally exclude a course to avoid an alternative prerequisite path.

- **Constraint optimizer** uses Google's OR-Tools CP-SAT solver. It chooses prerequisites jointly across targets, assigns each chosen course to at most one term, and enforces strict earlier-term prerequisites, credit limits, seasonal offerings, and difficult-course limits.
- **Greedy heuristic** tries minimum-count logical closure search, then packs eligible courses critical-first. If closure search hits a limit, it falls back to broad candidates and removes unused branches afterward. It can miss a valid schedule or the best objective. Packing failure is not proof of infeasibility.
- **Compare both** runs the same input through both strategies. An independent postcondition verifier checks every returned complete schedule.

Priority is lexicographic: either **fewest additional courses, then earliest finish**, or the reverse.
Both then minimize the sum of squared term credit loads to balance workload. Bounded objective weights make lower-priority improvements unable to outweigh higher-priority objectives.
Already completed courses incur no cost. All prerequisite branches are considered together, so shared courses are counted once.

Difficulty is an editable 1-5 estimate; 4-5 counts as difficult. Existing records default to 3, not a measured workload.
`semester_offered` accepts seasonal names: `Fall`, `Winter`, `Spring`, `Summer` (case-insensitive).
With summer disabled, the calendar alternates Fall/Winter; enabled, it cycles Winter/Spring/Summer/Fall.
Empty waiting terms count toward the finish horizon. The year increments between Fall and Winter.

**Results are not graduation audits.** They only satisfy the selected targets and the stored logical prerequisites.
Catalog records may be incomplete even if their stored `verified` flag is true. This upgrade does not reverify those flags or scrape official offerings.
Blank offerings are assumed available every enabled term. Zero-credit/placeholder courses consume no credit capacity and generate a warning if selected.
Permissions, equivalent experience, placement, seats, meeting times, instructor approval, co-requisites, and unmodeled degree rules are not inferred.
Verify records against official sources before relying on a plan.

Solver statuses have different meanings: `optimal` proves the configured objective within this model/horizon;
`feasible` is valid but not proven optimal; `infeasible` proves no plan for these exact constraints;
`unknown` means a search/time limit was reached. A greedy packing failure is `no_plan`.
The UI solver limit is five seconds. Plans are invalidated when inputs or the saved catalog change.

## Architecture

`planner/domain/requirements.py` implements the Composite pattern: immutable `CourseRef`, `AllOf`, and `AnyOf` objects share evaluation, serialization, explanation, and solver-encoding interfaces.
Nested AND/OR logic survives JSON round trips. The graph adapter uses these objects instead of a separate evaluator.
The group editor handles simple expressions; nested expressions use a JSON editor rather than silently flattening them.

`planner/services/` contains eligibility, minimum-prerequisite-set search, interchangeable `SchedulingStrategy` implementations, and schedule verification.
The prerequisite planner retains inclusion-minimal alternatives until all targets have been combined. This is exponential in the worst case, so it has explicit search/time limits.
Structural graph descendants remain useful for visualization, but gateway rankings now count **newly eligible** courses after hypothetically completing one candidate. This respects every AND/OR group and is separate from structural reachability.

`CourseRepository` is a protocol, injected through `create_app(repository)` into the API. `CourseDataStore` is the JSON implementation, retaining the existing import/export and in-process undo behavior.
Writes validate input before normalization, use a temporary file plus atomic replacement, and update undo history only after successful persistence.
Thread locking protects one server process; multiple server processes/external editors are not coordinated.

## API

All POST bodies are JSON objects; invalid input returns `400` with `errors`.

| Route | Purpose |
| --- | --- |
| `GET /api/state` | Catalog, visualization, logical eligibility and analysis |
| `POST /api/save`, `POST /api/import` | `{ "data": catalog, "force": false }`; warnings return `409` before writing |
| `POST /api/undo` | Restore the previous save in this process |
| `GET /api/export` | Download the catalog JSON |
| `POST /api/prerequisite-plan` | Minimum additional-course closure; ignores term constraints |
| `POST /api/schedule` | Schedule saved catalog; does not persist anything |

Example schedule body:

```json
{
  "target_course_ids": ["MATH 525", "MATH 565"],
  "completed_course_ids": [],
  "excluded_course_ids": [],
  "strategy": "constraint",
  "objective": "fewest_courses",
  "max_credits": 16,
  "max_difficult": 2,
  "horizon": 8,
  "start_season": "Winter",
  "start_year": 2027,
  "include_summer": false,
  "time_limit": 5
}
```

`completed_course_ids` adds hypothetical prior credits to stored completion statuses.
Omitting targets defaults to target-tagged courses. IDs must exist in the catalog.
Limits: 200 courses, 16 planning terms, 40 credits per term, solver time 0.01-15 seconds, request size 2 MB.
The response includes `results`, `catalog_fingerprint`, and the completed course IDs used.
Each result reports status, objective values, additional prerequisites, term assignments, witnesses explaining which earlier courses satisfy prerequisites, and assumptions.
`compare` returns both strategies, not a single merged schedule. A successful HTTP response may still contain an infeasible/unknown result.

## Tests And Benchmarks

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
node --check static/app.js
node --check static/schedule.js
node --test tests/test_frontend.cjs
$env:PYTHONHASHSEED = '0'
.\.venv\Scripts\python.exe -m benchmarks.schedule_benchmark --sizes 20 50 100 200 --seconds 2 --repeats 5 --warmups 1 --output benchmark-results.json
```

Tests cover nested logic, shared dependencies, cycles, malformed input, persistence failure, both strategies, term ordering, availability, capacity and infeasible plans.
For small random catalogs, an independent exhaustive assignment oracle verifies the CP-SAT objective, not just example output.
GitHub Actions runs tests and lint on Windows/Linux with Python 3.11/3.14, plus JavaScript syntax checks.
Benchmarks warm up each case/strategy, alternate measurement order, retain every measured outcome,
and verify every complete plan. They include nested AND/OR offerings and infeasible cases in addition to
the requested graph sizes. The two-second limit applies to solver search, not total call latency.
The ignored root `benchmark-results.json` is for your own runs; the published raw report lives in
`benchmarks/results/` and is linked from [the results and methodology](benchmarks/RESULTS.md).
Timings are machine-dependent, not a performance guarantee.

Repository hygiene tests reject tracked Python bytecode. `__pycache__/` and `*.py[cod]` remain ignored;
local caches may exist, but they are no longer part of Git.

Solver reference: [Google's CP-SAT documentation](https://developers.google.com/optimization/cp/cp_solver).
