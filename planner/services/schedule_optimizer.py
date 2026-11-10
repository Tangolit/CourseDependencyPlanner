from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Protocol

from planner.domain.course import Course
from planner.domain.requirements import AllOf, AnyOf, CourseRef
from planner.services.prerequisite_planner import PrerequisitePlanner


SEASONS = ("Fall", "Winter", "Spring", "Summer")


@dataclass(frozen=True)
class Term:
    season: str
    year: int

    @property
    def label(self):
        return f"{self.season} {self.year}"


@dataclass(frozen=True)
class ScheduleRequest:
    targets: tuple[str, ...]
    completed: frozenset[str]
    excluded: frozenset[str] = frozenset()
    max_credits: int = 16
    max_difficult: int = 2
    horizon: int = 8
    start_season: str = "Fall"
    start_year: int = 2027
    include_summer: bool = False
    objective: str = "fewest_courses"
    time_limit: float = 5.0

    def terms(self) -> tuple[Term, ...]:
        seasons = SEASONS if self.include_summer else SEASONS[:2]
        index = seasons.index(self.start_season)
        year = self.start_year
        result = []
        for _ in range(self.horizon):
            season = seasons[index]
            result.append(Term(season, year))
            index = (index + 1) % len(seasons)
            if seasons[index] == "Winter":
                year += 1
        return tuple(result)


class SchedulingStrategy(Protocol):
    def solve(self, courses: dict[str, Course], request: ScheduleRequest) -> dict: ...


def relevant_courses(courses: dict[str, Course], request: ScheduleRequest) -> dict[str, Course]:
    pending = list(request.targets)
    relevant = {}
    while pending:
        cid = pending.pop()
        if cid in request.completed or cid in request.excluded or cid in relevant or cid not in courses:
            continue
        relevant[cid] = courses[cid]
        pending.extend(courses[cid].requirement.course_ids())
    return dict(sorted(relevant.items()))


def offered(course: Course, term: Term) -> bool:
    return not course.offerings or term.season.casefold() in {value.casefold() for value in course.offerings}


def requirement_witness(requirement, completed) -> set[str]:
    if isinstance(requirement, CourseRef):
        return {requirement.course_id} if requirement.satisfied(completed) else set()
    if isinstance(requirement, AllOf):
        return set().union(*(requirement_witness(child, completed) for child in requirement.children))
    if isinstance(requirement, AnyOf):
        choices = [requirement_witness(child, completed) for child in requirement.children
                   if child.satisfied(completed)]
        return min(choices, key=lambda ids: (len(ids), sorted(ids))) if choices else set()
    return set()


def schedule_result(courses, request, assignments, strategy, status, elapsed, **extra):
    used_terms = max(assignments.values(), default=-1) + 1
    terms = []
    completed = set(request.completed)
    selected = set(assignments)
    for index, term in enumerate(request.terms()[:used_terms]):
        ids = sorted(cid for cid, slot in assignments.items() if slot == index)
        terms.append({
            "index": index, "label": term.label, "season": term.season, "year": term.year,
            "credits": sum(courses[cid].credits for cid in ids),
            "difficult_courses": sum(courses[cid].difficulty >= 4 for cid in ids),
            "courses": [{
                "id": cid, "title": courses[cid].title, "credits": courses[cid].credits,
                "difficulty": courses[cid].difficulty, "is_target": cid in request.targets,
                "satisfied_by": sorted(requirement_witness(courses[cid].requirement, completed)),
            } for cid in ids],
        })
        completed.update(ids)
    warnings = ["This is a catalog-model plan, not a graduation audit or enrollment guarantee."]
    unknown_offerings = sorted(cid for cid in selected if not courses[cid].offerings)
    if unknown_offerings:
        warnings.append("Unknown offerings assumed available every enabled term: " + ", ".join(unknown_offerings))
    unknown_credits = sorted(cid for cid in selected if courses[cid].credits == 0)
    if unknown_credits:
        warnings.append("Zero/unknown credits do not consume capacity; verify: " + ", ".join(unknown_credits))
    unverified = sorted(cid for cid in selected if not courses[cid].verified)
    if unverified:
        warnings.append("Unverified course records used: " + ", ".join(unverified))
    return {
        "status": status, "strategy": strategy, "optimal": status == "optimal",
        "terms": terms, "semester_count": used_terms, "course_count": len(selected),
        "total_credits": sum(courses[cid].credits for cid in selected),
        "prerequisite_course_ids": sorted(selected - set(request.targets)),
        "target_course_ids": sorted(request.targets),
        "completed_target_course_ids": sorted(set(request.targets) & request.completed),
        "objective": request.objective,
        "objective_values": {
            "course_count": len(selected), "semester_count": used_terms,
            "workload_squared": sum(term["credits"] ** 2 for term in terms),
        },
        "elapsed_ms": round((perf_counter() - elapsed) * 1000, 2), "warnings": warnings,
        **extra,
    }


class GreedyScheduler:
    """Bounded closure selection followed by deterministic critical-first packing.

    Closure-search exhaustion falls back to broad candidates. Packing is
    heuristic: failure to pack is never proof of infeasibility.
    """

    def solve(self, courses, request):
        started = perf_counter()
        plan = PrerequisitePlanner(courses, time_limit=request.time_limit).plan(
            request.targets, request.completed, request.excluded
        )
        if plan.status == "infeasible":
            return {"status": "infeasible", "strategy": "greedy", "optimal": False, "terms": [],
                    "message": "No logical prerequisite closure exists."}
        broad_candidates = plan.status == "unknown"
        remaining = set(relevant_courses(courses, request)) if broad_candidates else set(plan.course_ids)
        completed = set(request.completed)
        assignments = {}
        for index, term in enumerate(request.terms()):
            ready = [courses[cid] for cid in remaining
                     if courses[cid].requirement.satisfied(completed) and offered(courses[cid], term)]
            ready.sort(key=lambda course: (
                -sum(course.id in courses[cid].requirement.course_ids() for cid in remaining),
                -course.credits, course.id
            ))
            credits = difficult = 0
            picked = set()
            for course in ready:
                if credits + course.credits > request.max_credits:
                    continue
                if difficult + (course.difficulty >= 4) > request.max_difficult:
                    continue
                picked.add(course.id)
                assignments[course.id] = index
                credits += course.credits
                difficult += course.difficulty >= 4
            completed.update(picked)
            remaining -= picked
            if set(request.targets) <= completed:
                break
        if not set(request.targets) <= completed:
            return {"status": "no_plan", "strategy": "greedy", "optimal": False, "terms": [],
                    "unscheduled_course_ids": sorted(set(request.targets) - completed),
                    "message": "Greedy packing could not finish within the horizon. Try the constraint solver; "
                               "a different prerequisite branch or packing may work."}
        if broad_candidates:
            needed = set()
            pending = list(request.targets)
            while pending:
                cid = pending.pop()
                if cid in request.completed or cid in needed:
                    continue
                needed.add(cid)
                earlier = set(request.completed) | {other for other, slot in assignments.items()
                                                    if slot < assignments[cid]}
                pending.extend(requirement_witness(courses[cid].requirement, earlier))
            assignments = {cid: slot for cid, slot in assignments.items() if cid in needed}
        result = schedule_result(courses, request, assignments, "greedy", "feasible", started)
        if broad_candidates:
            result["warnings"].append("Exact closure search reached its limit; greedy packing used broad "
                                      "candidates, then removed unused prerequisite branches.")
        return result


class _TermEncoder:
    def __init__(self, model, before, completed):
        self.model, self.before, self.completed = model, before, completed

    def reference(self, course_id):
        return self.model.new_constant(1) if course_id in self.completed else self.before.get(
            course_id, self.model.new_constant(0)
        )

    def all_of(self, children):
        if not children:
            return self.model.new_constant(1)
        result = self.model.new_bool_var("and")
        self.model.add_min_equality(result, children)
        return result

    def any_of(self, children):
        if not children:
            return self.model.new_constant(0)
        result = self.model.new_bool_var("or")
        self.model.add_max_equality(result, children)
        return result


class ConstraintScheduler:
    """CP-SAT: strict prerequisite order, OR choices, offerings and term capacity."""

    def solve(self, courses, request):
        from ortools.sat.python import cp_model

        started = perf_counter()
        relevant = relevant_courses(courses, request)
        model = cp_model.CpModel()
        terms = request.terms()
        x = {(cid, slot): model.new_bool_var(f"{cid}@{slot}")
             for cid in relevant for slot in range(request.horizon)}
        selected = {cid: model.new_bool_var(f"take:{cid}") for cid in relevant}
        for cid in relevant:
            model.add(sum(x[cid, slot] for slot in range(request.horizon)) == selected[cid])
        for target in request.targets:
            if target not in request.completed:
                model.add(selected[target] == 1) if target in selected else model.add(False)

        loads = []
        for slot, term in enumerate(terms):
            before = {}
            for cid in relevant:
                before[cid] = model.new_bool_var(f"before:{cid}@{slot}")
                model.add(before[cid] == sum(x[cid, earlier] for earlier in range(slot)))
            encoder = _TermEncoder(model, before, request.completed)
            for cid, course in relevant.items():
                model.add_implication(x[cid, slot], course.requirement.encode(encoder))
                if not offered(course, term):
                    model.add(x[cid, slot] == 0)
            load = model.new_int_var(0, request.max_credits, f"load:{slot}")
            model.add(load == sum(course.credits * x[cid, slot] for cid, course in relevant.items()))
            model.add(sum(x[cid, slot] for cid, course in relevant.items()
                          if course.difficulty >= 4) <= request.max_difficult)
            square = model.new_int_var(0, request.max_credits ** 2, f"load_squared:{slot}")
            model.add_multiplication_equality(square, [load, load])
            loads.append(square)

        finish = model.new_int_var(0, request.horizon, "finish")
        for (cid, slot), variable in x.items():
            model.add(finish >= (slot + 1) * variable)
        count = sum(selected.values())
        balance_bound = request.horizon * request.max_credits ** 2
        unit = balance_bound + 1
        if request.objective == "fastest":
            objective = finish * (len(relevant) + 1) * unit + count * unit + sum(loads)
        else:
            objective = count * (request.horizon + 1) * unit + finish * unit + sum(loads)
        model.minimize(objective)
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = request.time_limit
        solver.parameters.num_search_workers = 1
        solver.parameters.random_seed = 0
        status = solver.solve(model)
        if status == cp_model.MODEL_INVALID:
            raise RuntimeError("The scheduling constraint model is invalid.")
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            infeasible = status == cp_model.INFEASIBLE
            return {
                "status": "infeasible" if infeasible else "unknown", "strategy": "constraint",
                "optimal": False, "terms": [], "elapsed_ms": round((perf_counter() - started) * 1000, 2),
                "message": "No plan meets these targets and constraints within the chosen horizon. "
                           "Check credits, offerings, difficult-course limits, exclusions and prerequisite cycles."
                           if infeasible else "Time limit reached without a plan; infeasibility has not been proven.",
            }
        assignments = {cid: slot for (cid, slot), variable in x.items() if solver.value(variable)}
        return schedule_result(
            courses, request, assignments, "constraint",
            "optimal" if status == cp_model.OPTIMAL else "feasible", started,
            solver={"objective_value": solver.objective_value, "best_bound": solver.best_objective_bound,
                    "branches": solver.num_branches, "conflicts": solver.num_conflicts},
        )


def verify_schedule(courses, request, result) -> list[str]:
    """Independent postcondition check, also useful for heuristic implementations."""
    errors = []
    completed = set(request.completed)
    seen = set()
    expected_terms = request.terms()
    for index, term in enumerate(result.get("terms", [])):
        if index >= len(expected_terms):
            errors.append("Schedule exceeds the planning horizon.")
            break
        if term["label"] != expected_terms[index].label:
            errors.append("Term labels are not in calendar order.")
        ids = [course["id"] for course in term["courses"]]
        credits = difficult = 0
        for cid in ids:
            if cid not in courses or cid in seen or cid in request.completed or cid in request.excluded:
                errors.append(f"Invalid or duplicate scheduled course: {cid}")
                continue
            course = courses[cid]
            credits += course.credits
            difficult += course.difficulty >= 4
            if not course.requirement.satisfied(completed):
                errors.append(f"{cid} has an unsatisfied prerequisite before {term['label']}.")
            if not offered(course, expected_terms[index]):
                errors.append(f"{cid} is not offered in {term['label']}.")
            seen.add(cid)
        if credits > request.max_credits or difficult > request.max_difficult:
            errors.append(f"Term capacity exceeded: {term['label']}")
        if credits != term["credits"]:
            errors.append(f"Incorrect credit total: {term['label']}")
        completed.update(ids)
    if not set(request.targets) <= completed:
        errors.append("Not every required target is completed.")
    return errors
