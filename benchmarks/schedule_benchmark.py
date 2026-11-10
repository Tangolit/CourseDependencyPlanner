import argparse
import json
import platform
from time import perf_counter

from planner.domain.course import Course
from planner.domain.requirements import AllOf, AnyOf, CourseRef
from planner.services.schedule_optimizer import (
    ConstraintScheduler, GreedyScheduler, ScheduleRequest, relevant_courses, verify_schedule,
)


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


def main():
    parser = argparse.ArgumentParser(description="Benchmark both schedulers on synthetic layered AND/OR catalogs.")
    parser.add_argument("--sizes", type=int, nargs="+", default=[20, 50, 100])
    parser.add_argument("--seconds", type=float, default=2.0)
    args = parser.parse_args()
    if any(size < 5 or size > 200 for size in args.sizes) or not 0.01 <= args.seconds <= 15:
        parser.error("Use sizes 5-200 and a solver limit between 0.01 and 15 seconds.")
    results = []
    for size in args.sizes:
        courses = synthetic_catalog(size)
        target_count = max(2, size // 5)
        options = ScheduleRequest(tuple(sorted(courses)[-target_count:]), frozenset(),
                                  horizon=16, time_limit=args.seconds)
        for scheduler in (GreedyScheduler(), ConstraintScheduler()):
            started = perf_counter()
            result = scheduler.solve(courses, options)
            elapsed_ms = round((perf_counter() - started) * 1000, 2)
            if result["status"] in ("optimal", "feasible"):
                assert not verify_schedule(courses, options, result)
            results.append({"catalog_size": size, "relevant_courses": len(relevant_courses(courses, options)),
                            "strategy": result["strategy"], "status": result["status"],
                            "elapsed_ms": elapsed_ms, "course_count": result.get("course_count"),
                            "semester_count": result.get("semester_count")})
    print(json.dumps({"python": platform.python_version(), "solver_limit_seconds": args.seconds,
                      "results": results}, indent=2))


if __name__ == "__main__":
    main()
