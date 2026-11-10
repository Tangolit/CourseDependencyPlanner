import pytest

from benchmarks.schedule_benchmark import (
    BenchmarkCase, benchmark_cases, case_input, measure, run_benchmarks, summarize,
)
from planner.domain.course import Course
from planner.domain.requirements import AllOf
from planner.services.schedule_optimizer import GreedyScheduler, ScheduleRequest


def tiny_case():
    return BenchmarkCase("tiny", "Test fixture", {"T": Course("T", "Target", 3, AllOf())},
                         ScheduleRequest(("T",), frozenset()))


def test_benchmark_cases_cover_graph_size_and_failure_modes():
    cases = benchmark_cases([20, 50, 100, 200], 2.0)
    assert [len(case.courses) for case in cases[:4]] == [20, 50, 100, 200]
    assert {case.name for case in cases[-3:]} == {"and_or_offerings", "credit_infeasible", "cycle_infeasible"}
    assert case_input(cases[0])["request"]["time_limit"] == 2.0
    assert case_input(cases[0])["courses"][0]["prerequisites"] == {"all_of": []}


def test_warmups_are_verified_but_not_in_measured_samples():
    case = tiny_case()
    samples = run_benchmarks([case], repeats=3, warmups=2, strategies={"greedy": GreedyScheduler()})
    assert [sample["trial"] for sample in samples] == [1, 2, 3]
    assert all(sample["validation"] == "passed" for sample in samples)
    assert all(sample["assignments"] == {"T": 0} for sample in samples)


def test_every_outcome_is_retained_in_summary():
    values = [
        {"case": "C", "strategy": "S", "elapsed_ms": timing, "status": status,
         "course_count": 3 if status == "feasible" else None,
         "semester_count": 2 if status == "feasible" else None,
         "validation": "passed" if status == "feasible" else "not_applicable"}
        for timing, status in [(10.0, "feasible"), (30.0, "unknown"), (20.0, "infeasible")]
    ]
    summary, = summarize(values)
    assert (summary["min_elapsed_ms"], summary["median_elapsed_ms"], summary["max_elapsed_ms"]) == (10, 20, 30)
    assert summary["status_counts"] == {"feasible": 1, "infeasible": 1, "unknown": 1}
    assert summary["verified_plans"] == 1
    assert summary["plan_sizes"] == [{"course_count": 3, "semester_count": 2, "occurrences": 1}]


def test_invalid_benchmark_solution_aborts_instead_of_publishing_success():
    class BrokenScheduler:
        def solve(self, courses, request):
            return {"status": "feasible", "terms": []}

    with pytest.raises(RuntimeError, match="Invalid benchmark schedule"):
        measure(tiny_case(), BrokenScheduler(), "broken", 1)
