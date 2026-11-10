from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from itertools import product
from typing import Any, Protocol


class RequirementEncoder(Protocol):
    def reference(self, course_id: str) -> Any: ...
    def all_of(self, children: tuple) -> Any: ...
    def any_of(self, children: tuple) -> Any: ...


class Requirement(ABC):
    """Composite interface shared by leaves and nested logical groups."""

    @abstractmethod
    def satisfied(self, completed: set[str] | frozenset[str]) -> bool: ...

    @abstractmethod
    def course_ids(self) -> frozenset[str]: ...

    @abstractmethod
    def serialize(self) -> str | dict: ...

    @abstractmethod
    def encode(self, encoder: RequirementEncoder) -> Any: ...

    @abstractmethod
    def missing_options(self, completed: set[str] | frozenset[str]) -> set[frozenset[str]]: ...

    def explain_missing(self, completed: set[str] | frozenset[str]) -> dict:
        return {
            "expression": self.serialize(),
            "satisfied": self.satisfied(completed),
            "alternatives": [sorted(option) for option in sorted(
                self.missing_options(completed), key=lambda item: (len(item), sorted(item))
            )],
        }


def minimal_sets(options) -> set[frozenset[str]]:
    """Keep incomparable sets, not merely the locally shortest OR branch.

    A larger local branch can share dependencies with another target and become
    cheaper globally. Only supersets are safe to discard.
    """
    result: set[frozenset[str]] = set()
    for option in sorted(set(options), key=lambda item: (len(item), sorted(item))):
        if not any(existing <= option for existing in result):
            result.add(option)
    return result


@dataclass(frozen=True)
class CourseRef(Requirement):
    course_id: str

    def satisfied(self, completed):
        return self.course_id in completed

    def course_ids(self):
        return frozenset((self.course_id,))

    def serialize(self):
        return self.course_id

    def encode(self, encoder):
        return encoder.reference(self.course_id)

    def missing_options(self, completed):
        return {frozenset()} if self.satisfied(completed) else {self.course_ids()}


@dataclass(frozen=True)
class AllOf(Requirement):
    children: tuple[Requirement, ...] = ()

    def satisfied(self, completed):
        return all(child.satisfied(completed) for child in self.children)

    def course_ids(self):
        return frozenset().union(*(child.course_ids() for child in self.children))

    def serialize(self):
        return {"all_of": [child.serialize() for child in self.children]}

    def encode(self, encoder):
        return encoder.all_of(tuple(child.encode(encoder) for child in self.children))

    def missing_options(self, completed):
        options = {frozenset()}
        for child in self.children:
            options = minimal_sets(a | b for a, b in product(options, child.missing_options(completed)))
        return options


@dataclass(frozen=True)
class AnyOf(Requirement):
    children: tuple[Requirement, ...] = ()

    def satisfied(self, completed):
        return any(child.satisfied(completed) for child in self.children)

    def course_ids(self):
        return frozenset().union(*(child.course_ids() for child in self.children))

    def serialize(self):
        return {"any_of": [child.serialize() for child in self.children]}

    def encode(self, encoder):
        return encoder.any_of(tuple(child.encode(encoder) for child in self.children))

    def missing_options(self, completed):
        return minimal_sets(option for child in self.children for option in child.missing_options(completed))


def parse_requirement(value, path="prerequisites") -> Requirement:
    """Read the existing JSON format without silently discarding invalid logic."""
    if value is None:
        return AllOf()
    if isinstance(value, str) and value.strip():
        return CourseRef(value.strip())
    if isinstance(value, list):
        return AllOf(tuple(parse_requirement(item, f"{path}[{index}]") for index, item in enumerate(value)))
    if isinstance(value, dict) and len(value) == 1:
        key = next(iter(value))
        if key in ("all_of", "any_of") and isinstance(value[key], list):
            children = tuple(parse_requirement(item, f"{path}.{key}[{index}]")
                             for index, item in enumerate(value[key]))
            return AllOf(children) if key == "all_of" else AnyOf(children)
    raise ValueError(f"{path} must be a course ID or an all_of/any_of array.")
