from __future__ import annotations

from dataclasses import dataclass

from planner.domain.requirements import Requirement, parse_requirement


@dataclass(frozen=True)
class Course:
    id: str
    title: str
    credits: int
    requirement: Requirement
    status: str = "not_started"
    offerings: tuple[str, ...] = ()
    difficulty: int = 3
    verified: bool = False

    @classmethod
    def from_dict(cls, data: dict) -> Course:
        return cls(
            id=data["id"], title=data.get("title", ""), credits=data.get("credits", 0),
            requirement=parse_requirement(data.get("prerequisites")),
            status=data.get("status", "not_started"),
            offerings=tuple(data.get("semester_offered", [])),
            difficulty=data.get("difficulty", 3), verified=data.get("verified", False),
        )
