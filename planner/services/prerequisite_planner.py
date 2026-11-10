from __future__ import annotations

from dataclasses import dataclass
from time import monotonic

from planner.domain.course import Course
from planner.domain.requirements import AllOf, AnyOf, CourseRef


class SearchLimitReached(Exception):
    pass


@dataclass
class PrerequisitePlan:
    status: str
    course_ids: tuple[str, ...] = ()
    alternatives_count: int = 0
    explored_states: int = 0


class PrerequisitePlanner:
    """Exact, bounded search over inclusion-minimal prerequisite closures.

    AND combines sets by union, so shared dependencies are charged once. OR
    retains incomparable choices until every target has been considered.
    Cyclic branches are rejected, rather than rejecting an otherwise valid OR.
    """

    def __init__(self, courses: dict[str, Course], max_states=50_000, time_limit=2.0):
        self.courses = courses
        self.max_states = max_states
        self.time_limit = time_limit

    def plan(self, targets, completed, excluded=frozenset()) -> PrerequisitePlan:
        self.explored = 0
        self.deadline = monotonic() + self.time_limit
        self.completed = frozenset(completed)
        self.excluded = frozenset(excluded)
        try:
            choices = {frozenset()}
            for target in sorted(set(targets)):
                choices = self._combine(choices, self._course(target, frozenset()))
            if not choices:
                return PrerequisitePlan("infeasible", explored_states=self.explored)
            best = min(choices, key=lambda ids: (
                len(ids), sum(self.courses[cid].credits for cid in ids), sorted(ids)
            ))
            return PrerequisitePlan("optimal", tuple(sorted(best)), len(choices), self.explored)
        except SearchLimitReached:
            return PrerequisitePlan("unknown", explored_states=self.explored)

    def _tick(self):
        self.explored += 1
        if self.explored > self.max_states or monotonic() > self.deadline:
            raise SearchLimitReached

    def _combine(self, left, right):
        return self._minimal(first | second for first in left for second in right)

    def _minimal(self, options):
        result = set()
        for option in options:
            self._tick()
            redundant = False
            supersets = set()
            for existing in result:
                self._tick()
                if existing <= option:
                    redundant = True
                    break
                if option < existing:
                    supersets.add(existing)
            if not redundant:
                result.difference_update(supersets)
                result.add(option)
        return result

    def _course(self, course_id, visiting):
        self._tick()
        if course_id in self.completed:
            return {frozenset()}
        if course_id in visiting or course_id in self.excluded or course_id not in self.courses:
            return set()
        options = self._requirement(self.courses[course_id].requirement, visiting | {course_id})
        return {option | {course_id} for option in options}

    def _requirement(self, requirement, visiting):
        self._tick()
        if requirement.satisfied(self.completed):
            return {frozenset()}
        if isinstance(requirement, CourseRef):
            return self._course(requirement.course_id, visiting)
        if isinstance(requirement, AllOf):
            options = {frozenset()}
            for child in requirement.children:
                options = self._combine(options, self._requirement(child, visiting))
            return options
        if isinstance(requirement, AnyOf):
            return self._minimal(option for child in requirement.children
                                 for option in self._requirement(child, visiting))
        raise TypeError("Unsupported requirement object")
