from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile

from planner.graph_logic import (
    DEFAULT_INTEREST_LEVELS,
    DEFAULT_STATUSES,
    build_course_graph,
    detect_prerequisite_cycles,
    expression_to_course_ids,
    normalize_dataset,
)


class ValidationError(Exception):
    def __init__(self, errors: list[str], warnings: list[str] | None = None):
        super().__init__("\n".join(errors))
        self.errors = errors
        self.warnings = warnings or []


class CourseDataStore:
    def __init__(self, data_path: Path | None = None, history_limit: int = 30):
        root = Path(__file__).resolve().parent.parent
        self.data_path = data_path or root / "data" / "courses.json"
        self.history_limit = history_limit
        self._history: list[dict] = []
        self.data_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.data_path.exists():
            raise FileNotFoundError(f"Missing data file at {self.data_path}")

    def get_data(self) -> dict:
        return normalize_dataset(self._read())

    def save_data(self, data: dict, force: bool = False):
        return self._persist(data, force=force)

    def import_data(self, data: dict, force: bool = False):
        return self._persist(data, force=force)

    def undo(self):
        if not self._history:
            return None
        restored = self._history.pop()
        self._write(restored)
        return normalize_dataset(restored)

    def write_export_snapshot(self) -> Path:
        snapshot = self.get_data()
        with NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
            json.dump(snapshot, handle, indent=2)
            handle.write("\n")
            return Path(handle.name)

    def _persist(self, data: dict, force: bool = False):
        normalized = normalize_dataset(data)
        errors, warnings = validate_dataset(normalized)
        if errors:
            raise ValidationError(errors, warnings)
        if warnings and not force:
            return normalized, warnings
        current = self.get_data()
        self._history.append(deepcopy(current))
        if len(self._history) > self.history_limit:
            self._history.pop(0)
        normalized["meta"]["last_saved"] = datetime.now(timezone.utc).isoformat()
        self._write(normalized)
        return normalized, warnings

    def _read(self) -> dict:
        return json.loads(self.data_path.read_text(encoding="utf-8"))

    def _write(self, data: dict):
        self.data_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def validate_dataset(data: dict):
    errors = []
    warnings = []
    courses = data.get("courses", [])
    ids = [course["id"] for course in courses]
    if not ids:
        errors.append("At least one course is required.")
        return errors, warnings

    duplicates = sorted({course_id for course_id in ids if ids.count(course_id) > 1})
    if duplicates:
        errors.append(f"Duplicate course IDs are not allowed: {', '.join(duplicates)}")

    known_ids = set(ids)

    for course in courses:
        if not course["id"]:
            errors.append("Every course must have a non-empty ID.")
        if course["status"] not in DEFAULT_STATUSES:
            errors.append(f"{course['id'] or 'Unknown course'} has an invalid status: {course['status']}")
        if course["interest"] not in DEFAULT_INTEREST_LEVELS:
            errors.append(f"{course['id'] or 'Unknown course'} has an invalid interest level: {course['interest']}")
        if course["credits"] < 0:
            errors.append(f"{course['id']} cannot have negative credits.")

        prereq_ids = expression_to_course_ids(course["prerequisites"])
        if course["id"] in prereq_ids:
            errors.append(f"{course['id']} cannot list itself as a prerequisite.")

        missing = sorted(prereq_ids - known_ids)
        if missing:
            warnings.append(
                f"{course['id']} references prerequisite courses that do not exist yet: {', '.join(missing)}"
            )

    graph = build_course_graph(data)
    cycles = detect_prerequisite_cycles(graph)
    if cycles:
        for cycle in cycles:
            warnings.append(f"Cycle detected: {' -> '.join(cycle)}")

    return errors, sorted(set(warnings))
