import argparse
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
from importlib.metadata import version
import json
from math import isfinite
import os
from pathlib import Path
import platform
from statistics import median
import subprocess
import sys
from time import perf_counter_ns

from planner.domain.course import Course
from planner.domain.requirements import AllOf, AnyOf, CourseRef
from planner.services.schedule_optimizer import (
    ConstraintScheduler, GreedyScheduler, ScheduleRequest, relevant_courses, verify_schedule,
)


ROOT = Path(__file__).resolve().parents[1]
SUCCESS_STATUSES = {"optimal", "feasible"}
SOURCE_FILES = (
    "benchmarks/schedule_benchmark.py", "planner/domain/course.py", "planner/domain/requirements.py",
    "planner/services/prerequisite_planner.py", "planner/services/schedule_optimizer.py",
)


@dataclass(frozen=True)
class BenchmarkCase:
    name: str
    description: str
    courses: dict[str, Course]
    request: ScheduleRequest


def synthetic_catalog(size):
    courses = {}
    width = max(2, size // 5)
    for index in range(size):
        children = () if index < width else (
            AnyOf((CourseRef(f"C{index - width:03}"), CourseRef(f"C{index - width + 1:03}"))),
        )
        cid = f"C{index:03}"
        courses[cid] = Course(cid, f"Synthetic course {index}", 3, AllOf(children), difficulty=3)
    return courses


def benchmark_cases(sizes, seconds):
    cases = []
    for size in sorted(set(sizes)):
        courses = synthetic_catalog(size)
        target_count = max(2, size // 5)
        options = ScheduleRequest(tuple(sorted(courses)[-target_count:]), frozenset(),
                                  horizon=16, time_limit=seconds)
        cases.append(BenchmarkCase(
            f"layered_{size}", "Deterministic layered OR graph; all courses have three credits and "
            "difficulty three; all offerings are unconstrained; the last layer is mandatory.", courses, options,
        ))
    availability = {
        "A": Course("A", "Foundation", 3, AllOf(), offerings=("Fall", "Winter")),
        "B": Course("B", "Fall alternative", 3, AllOf(), offerings=("Fall",)),
        "C": Course("C", "Winter alternative", 3, AllOf(), offerings=("Winter",)),
        "D": Course("D", "Combined requirements", 4,
                    AllOf((CourseRef("A"), AnyOf((CourseRef("B"), CourseRef("C"))))),
                    offerings=("Fall", "Winter"), difficulty=4),
        "E": Course("E", "Winter follow-up", 3, CourseRef("D"), offerings=("Winter",), difficulty=4),
        "T": Course("T", "Fall target", 3, CourseRef("E"), offerings=("Fall",), difficulty=4),
    }
    cases.append(BenchmarkCase(
        "and_or_offerings", "Nested AND/OR plus Fall/Winter availability, seven-credit capacity and "
        "at most one difficult course per term; waiting terms count toward finish.", availability,
        ScheduleRequest(("E", "T"), frozenset(), horizon=6, max_credits=7, max_difficult=1, time_limit=seconds),
    ))
    cases.append(BenchmarkCase(
        "credit_infeasible", "One mandatory twenty-credit course exceeds the sixteen-credit term cap.",
        {"T": Course("T", "Oversized target", 20, AllOf())},
        ScheduleRequest(("T",), frozenset(), horizon=16, time_limit=seconds),
    ))
    cases.append(BenchmarkCase(
        "cycle_infeasible", "Two mandatory prerequisites form a cycle with no completed credit or OR escape.",
        {"A": Course("A", "Cyclic target", 3, CourseRef("B")),
         "B": Course("B", "Cyclic prerequisite", 3, CourseRef("A"))},
        ScheduleRequest(("A",), frozenset(), horizon=16, time_limit=seconds),
    ))
    return cases


def case_input(case):
    options = asdict(case.request)
    for key in ("targets", "completed", "excluded"):
        options[key] = sorted(options[key])
    courses = [{
        "id": course.id, "title": course.title, "credits": course.credits,
        "prerequisites": course.requirement.serialize(), "difficulty": course.difficulty,
        "semester_offered": list(course.offerings), "status": course.status, "verified": course.verified,
    } for course in sorted(case.courses.values(), key=lambda course: course.id)]
    return {"courses": courses, "request": options}


def measure(case, scheduler, strategy, trial):
    started = perf_counter_ns()
    result = scheduler.solve(case.courses, case.request)
    elapsed_ms = (perf_counter_ns() - started) / 1_000_000
    successful = result["status"] in SUCCESS_STATUSES
    if successful:
        errors = verify_schedule(case.courses, case.request, result)
        if errors:
            raise RuntimeError(f"Invalid benchmark schedule ({case.name}/{strategy}): {'; '.join(errors)}")
    return {
        "case": case.name, "strategy": strategy, "trial": trial,
        "elapsed_ms": round(elapsed_ms, 3), "status": result["status"],
        "course_count": result.get("course_count"), "semester_count": result.get("semester_count"),
        "objective_values": result.get("objective_values"), "solver": result.get("solver"),
        "validation": "passed" if successful else "not_applicable",
        "message": result.get("message"),
        "assignments": {course["id"]: term["index"] for term in result.get("terms", [])
                        for course in term["courses"]} if successful else None,
    }


def summarize(samples):
    groups = defaultdict(list)
    for sample in samples:
        groups[sample["case"], sample["strategy"]].append(sample)
    summaries = []
    for (case, strategy), values in sorted(groups.items()):
        timings = [value["elapsed_ms"] for value in values]
        sizes = Counter((value["course_count"], value["semester_count"])
                        for value in values if value["status"] in SUCCESS_STATUSES)
        summaries.append({
            "case": case, "strategy": strategy, "trials": len(values),
            "min_elapsed_ms": min(timings), "median_elapsed_ms": round(median(timings), 3),
            "max_elapsed_ms": max(timings), "status_counts": dict(sorted(Counter(
                value["status"] for value in values).items())),
            "verified_plans": sum(value["validation"] == "passed" for value in values),
            "plan_sizes": [{"course_count": courses, "semester_count": terms, "occurrences": count}
                           for (courses, terms), count in sorted(sizes.items())],
        })
    return summaries


def run_benchmarks(cases, repeats, warmups, strategies=None, progress=None):
    strategies = strategies if strategies is not None else {
        "greedy": GreedyScheduler(), "constraint": ConstraintScheduler(),
    }
    samples = []
    for case in cases:
        for warmup in range(warmups):
            for name, scheduler in strategies.items():
                measure(case, scheduler, name, -(warmup + 1))
        for trial in range(1, repeats + 1):
            # Alternate order to avoid always measuring one strategy first.
            order = list(strategies.items())
            if trial % 2 == 0:
                order.reverse()
            for name, scheduler in order:
                sample = measure(case, scheduler, name, trial)
                samples.append(sample)
                if progress:
                    progress(f"{case.name} / {name} / trial {trial}: "
                             f"{sample['status']} in {sample['elapsed_ms']:.3f} ms")
    return samples


def environment_metadata(machine_label):
    try:
        base_commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
                                     text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        base_commit = None
    return {
        "machine_label": machine_label, "os": platform.platform(), "architecture": platform.machine(),
        "logical_cpus": os.cpu_count(), "python": platform.python_version(),
        "python_implementation": platform.python_implementation(), "ortools": version("ortools"),
        "python_hash_seed": os.environ.get("PYTHONHASHSEED"),
        "cp_sat_search_workers": 1, "cp_sat_random_seed": 0, "base_git_commit": base_commit,
        "source_hash_normalization": "UTF-8 text with LF line endings",
        "source_sha256": {path: sha256((ROOT / path).read_text(encoding="utf-8").encode()).hexdigest()
                          for path in SOURCE_FILES},
        "isolation": "Interactive local workstation; no CPU pinning, process isolation or power controls.",
    }


def main():
    parser = argparse.ArgumentParser(description="Measure both schedulers; retain every timing and solver outcome.")
    parser.add_argument("--sizes", type=int, nargs="+", default=[20, 50, 100])
    parser.add_argument("--seconds", type=float, default=2.0)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--machine-label", default=platform.processor())
    parser.add_argument("--output", type=Path, help="Write generated raw JSON to this path instead of stdout.")
    args = parser.parse_args()
    if any(size < 5 or size > 200 for size in args.sizes) or not isfinite(args.seconds) or not 0.01 <= args.seconds <= 15:
        parser.error("Use sizes 5-200 and a solver limit between 0.01 and 15 seconds.")
    if not 1 <= args.repeats <= 20 or not 0 <= args.warmups <= 3:
        parser.error("Use 1-20 measured repetitions and 0-3 warmups per case/strategy.")
    # Exclude dependency import/startup from steady-state solve() measurements.
    from ortools.sat.python import cp_model
    del cp_model
    started_at = datetime.now(timezone.utc).isoformat()
    environment = environment_metadata(args.machine_label)
    cases = benchmark_cases(args.sizes, args.seconds)
    samples = run_benchmarks(cases, args.repeats, args.warmups,
                             progress=lambda message: print(message, file=sys.stderr, flush=True))
    report = {
        "schema_version": 2, "started_at_utc": started_at,
        "finished_at_utc": datetime.now(timezone.utc).isoformat(), "environment": environment,
        "methodology": {
            "measured_repeats": args.repeats, "warmups_per_case_strategy": args.warmups,
            "solver_limit_seconds": args.seconds, "clock": "time.perf_counter_ns",
            "timed_scope": "Direct scheduler.solve(): includes model construction, search and result assembly; "
                           "excludes dependency import, warmups, verification, HTTP, UI and file I/O.",
            "all_measured_outcomes_retained": True, "strategy_order": "Alternated by trial, within each case.",
            "verification": "Every feasible/optimal schedule, including warmups, checked with verify_schedule; "
                            "invalid output aborts the run. No latency thresholds are asserted.",
        },
        "cases": [{"name": case.name, "description": case.description,
                   "catalog_size": len(case.courses),
                   "relevant_courses": len(relevant_courses(case.courses, case.request)),
                   "input_sha256": sha256(json.dumps(case_input(case), sort_keys=True).encode()).hexdigest(),
                   "input": case_input(case)} for case in cases],
        "samples": samples, "summary": summarize(samples),
    }
    content = json.dumps(report, indent=2, allow_nan=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(content, encoding="utf-8")
        print(f"Raw measured results: {args.output}")
        for summary in report["summary"]:
            print(f"{summary['case']:20} {summary['strategy']:10} "
                  f"median {summary['median_elapsed_ms']:9.3f} ms | {summary['status_counts']}")
    else:
        print(content, end="")


if __name__ == "__main__":
    main()
