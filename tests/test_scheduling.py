from dataclasses import replace
from itertools import product
import random

import pytest

from planner.services.schedule_optimizer import (
    ConstraintScheduler,
    GreedyScheduler,
    ScheduleRequest,
    offered,
    verify_schedule,
)


@pytest.mark.parametrize("scheduler", [GreedyScheduler(), ConstraintScheduler()])
def test_strict_prerequisite_order_and_completed_or(catalog, scheduler):
    courses = catalog("214", "217", {"id": "465", "credits": 3,
                      "prerequisites": {"any_of": ["214", "217"]}},
                      {"id": "565", "credits": 3, "prerequisites": {"all_of": ["465"]}})
    request = ScheduleRequest(("565",), frozenset({"214"}), max_credits=6)
    result = scheduler.solve(courses, request)
    assert result["status"] in ("optimal", "feasible")
    assert result["course_count"] == 2
    assert [term["courses"][0]["id"] for term in result["terms"]] == ["465", "565"]
    assert verify_schedule(courses, request, result) == []


def test_credit_limit_and_balancing(catalog):
    courses = catalog(*({"id": cid, "credits": 3} for cid in "ABCD"))
    request = ScheduleRequest(tuple("ABCD"), frozenset(), max_credits=9, horizon=3)
    result = ConstraintScheduler().solve(courses, request)
    assert result["status"] == "optimal"
    assert [term["credits"] for term in result["terms"]] == [6, 6]
    assert verify_schedule(courses, request, result) == []


def test_difficult_course_limit(catalog):
    courses = catalog({"id": "A", "credits": 3, "difficulty": 4},
                      {"id": "B", "credits": 3, "difficulty": 5})
    request = ScheduleRequest(("A", "B"), frozenset(), max_difficult=1)
    result = ConstraintScheduler().solve(courses, request)
    assert result["semester_count"] == 2
    assert verify_schedule(courses, request, result) == []


def test_offerings_idle_terms_and_calendar(catalog):
    courses = catalog({"id": "A", "credits": 3, "semester_offered": ["Fall"]},
                      {"id": "B", "credits": 3, "semester_offered": ["Winter"],
                       "prerequisites": {"all_of": ["A"]}})
    request = ScheduleRequest(("B",), frozenset(), start_season="Winter", start_year=2027)
    result = ConstraintScheduler().solve(courses, request)
    assert [term["label"] for term in result["terms"]] == ["Winter 2027", "Fall 2027", "Winter 2028"]
    assert result["terms"][0]["courses"] == []
    assert verify_schedule(courses, request, result) == []


def test_enabled_summer_calendar():
    request = ScheduleRequest(("A",), frozenset(), start_season="Spring", start_year=2027,
                              include_summer=True, horizon=5)
    assert [term.label for term in request.terms()] == [
        "Spring 2027", "Summer 2027", "Fall 2027", "Winter 2028", "Spring 2028"
    ]


def test_objective_priorities_choose_different_alternatives(catalog):
    courses = catalog("A", "X", "Y", "Z", {"id": "B", "prerequisites": {"all_of": ["A"]}},
                      {"id": "T", "prerequisites": {"any_of": ["B", {"all_of": ["X", "Y", "Z"]}]}})
    request = ScheduleRequest(("T",), frozenset(), horizon=4)
    minimum = ConstraintScheduler().solve(courses, request)
    fastest = ConstraintScheduler().solve(courses, replace(request, objective="fastest"))
    assert (minimum["course_count"], minimum["semester_count"]) == (3, 3)
    assert (fastest["course_count"], fastest["semester_count"]) == (4, 2)


def test_solver_selects_available_alternative_not_greedy_minimum(catalog):
    courses = catalog({"id": "A", "credits": 20}, {"id": "B", "credits": 3},
                      {"id": "T", "credits": 3, "prerequisites": {"any_of": ["A", "B"]}})
    request = ScheduleRequest(("T",), frozenset(), max_credits=6)
    result = ConstraintScheduler().solve(courses, request)
    assert result["prerequisite_course_ids"] == ["B"]


@pytest.mark.parametrize("record", [
    {"id": "A", "credits": 20},
    {"id": "A", "semester_offered": ["Summer"]},
    {"id": "A", "prerequisites": {"any_of": []}},
    {"id": "A", "prerequisites": {"all_of": ["MISSING"]}},
])
def test_infeasible_constraints(catalog, record):
    result = ConstraintScheduler().solve(catalog(record), ScheduleRequest(("A",), frozenset()))
    assert result["status"] == "infeasible"
    assert not result["optimal"]


def test_cyclic_or_branch_can_be_avoided(catalog):
    courses = catalog("C", {"id": "A", "prerequisites": {"any_of": ["B", "C"]}},
                      {"id": "B", "prerequisites": {"all_of": ["A"]}})
    request = ScheduleRequest(("A",), frozenset())
    result = ConstraintScheduler().solve(courses, request)
    assert result["status"] == "optimal"
    assert result["prerequisite_course_ids"] == ["C"]
    impossible = ConstraintScheduler().solve(courses, replace(request, excluded=frozenset({"C"})))
    assert impossible["status"] == "infeasible"


@pytest.mark.parametrize("scheduler", [GreedyScheduler(), ConstraintScheduler()])
def test_already_completed_targets_need_no_terms(catalog, scheduler):
    result = scheduler.solve(catalog("A"), ScheduleRequest(("A",), frozenset({"A"})))
    assert result["terms"] == []
    assert result["course_count"] == 0


def test_greedy_failure_does_not_claim_proven_infeasibility(catalog):
    result = GreedyScheduler().solve(catalog({"id": "A", "credits": 20}),
                                     ScheduleRequest(("A",), frozenset()))
    assert result["status"] == "no_plan"


def test_greedy_fallback_prunes_unused_alternatives(catalog, monkeypatch):
    from planner.services.prerequisite_planner import PrerequisitePlan

    monkeypatch.setattr("planner.services.schedule_optimizer.PrerequisitePlanner.plan",
                        lambda *args: PrerequisitePlan("unknown"))
    courses = catalog("A", "B", {"id": "T", "prerequisites": {"any_of": ["A", "B"]}})
    request = ScheduleRequest(("T",), frozenset())
    result = GreedyScheduler().solve(courses, request)
    assert result["status"] == "feasible"
    assert result["course_count"] == 2
    assert verify_schedule(courses, request, result) == []
    assert any("search reached its limit" in warning for warning in result["warnings"])


def test_verify_catches_same_term_prerequisite(catalog):
    courses = catalog("A", {"id": "B", "prerequisites": {"all_of": ["A"]}})
    request = ScheduleRequest(("B",), frozenset())
    result = {"terms": [{"label": "Fall 2027", "credits": 0, "courses": [{"id": "A"}, {"id": "B"}]}]}
    assert any("unsatisfied prerequisite" in error for error in verify_schedule(courses, request, result))


def exhaustive_optimum(courses, request):
    """Independent oracle: try every absent/term assignment on a small catalog."""
    ids = sorted(set(courses) - request.completed)
    best = None
    for slots in product(range(-1, request.horizon), repeat=len(ids)):
        mapping = dict(zip(ids, slots))
        if any(mapping.get(target, -1) < 0 for target in request.targets if target not in request.completed):
            continue
        completed = set(request.completed)
        loads = []
        valid = True
        for index, term in enumerate(request.terms()):
            term_ids = [cid for cid in ids if mapping[cid] == index]
            credits = sum(courses[cid].credits for cid in term_ids)
            if credits > request.max_credits or sum(courses[cid].difficulty >= 4 for cid in term_ids) > request.max_difficult:
                valid = False
                break
            if any(cid in request.excluded or not courses[cid].requirement.satisfied(completed)
                   or not offered(courses[cid], term) for cid in term_ids):
                valid = False
                break
            completed.update(term_ids)
            loads.append(credits)
        if valid:
            count = sum(slot >= 0 for slot in slots)
            finish = max(slots, default=-1) + 1
            square = sum(load ** 2 for load in loads)
            score = (count, finish, square) if request.objective == "fewest_courses" else (finish, count, square)
            if best is None or score < best:
                best = score
    return best


@pytest.mark.parametrize("seed", range(10))
def test_optimizer_matches_exhaustive_oracle(catalog, seed):
    rng = random.Random(seed)
    records = []
    for index in range(5):
        options = [f"C{earlier}" for earlier in range(index) if rng.random() < .5]
        expression = {rng.choice(["all_of", "any_of"]): options} if options else {"all_of": []}
        records.append({"id": f"C{index}", "credits": rng.randint(1, 3), "prerequisites": expression,
                        "difficulty": rng.choice([2, 4]),
                        "semester_offered": rng.choice([[], ["Fall"], ["Winter"]])})
    courses = catalog(*records)
    request = ScheduleRequest(("C3", "C4"), frozenset(), horizon=3, max_credits=4,
                              max_difficult=1, objective=rng.choice(["fewest_courses", "fastest"]))
    oracle = exhaustive_optimum(courses, request)
    result = ConstraintScheduler().solve(courses, request)
    if oracle is None:
        assert result["status"] == "infeasible"
    else:
        assert result["status"] == "optimal"
        score = result["objective_values"]
        actual = (score["course_count"], score["semester_count"], score["workload_squared"])
        if request.objective == "fastest":
            actual = (actual[1], actual[0], actual[2])
        assert actual == oracle
        assert verify_schedule(courses, request, result) == []
