from math import isfinite

from planner.domain.requirements import parse_requirement
from planner.services.schedule_optimizer import SEASONS, ScheduleRequest


class ValidationError(Exception):
    def __init__(self, errors: list[str], warnings: list[str] | None = None):
        super().__init__("\n".join(errors))
        self.errors = errors
        self.warnings = warnings or []


def validate_raw_dataset(data):
    errors = []
    if not isinstance(data, dict) or not isinstance(data.get("courses"), list):
        raise ValidationError(["Data must be an object with a courses array."])
    if not 1 <= len(data["courses"]) <= 200:
        errors.append("The catalog must contain between 1 and 200 courses.")
    if "meta" in data and not isinstance(data["meta"], dict):
        errors.append("meta must be an object.")
    if isinstance(data.get("meta"), dict):
        for field in ("disclaimer", "target_course_id"):
            if field in data["meta"] and not isinstance(data["meta"][field], str):
                errors.append(f"meta.{field} must be text.")
    if "tag_catalog" in data and not _string_list(data["tag_catalog"]):
        errors.append("tag_catalog must be an array of text values.")
    for index, course in enumerate(data["courses"]):
        label = f"Course {index + 1}"
        if not isinstance(course, dict):
            errors.append(f"{label} must be an object.")
            continue
        for field in ("id", "title", "description", "source_url", "notes", "prerequisite_text"):
            value = course.get(field, "")
            if not isinstance(value, str) or len(value) > (100 if field == "id" else 20_000):
                errors.append(f"{label}: {field} must be text of a reasonable length.")
        for field, default, minimum, maximum in (("credits", 0, 0, 40), ("difficulty", 3, 1, 5)):
            value = course.get(field, default)
            if type(value) is not int or not minimum <= value <= maximum:
                errors.append(f"{label}: {field} must be an integer from {minimum} to {maximum}.")
        if course.get("status", "not_started") not in (
            "completed", "current", "planned", "interested", "not_started"
        ):
            errors.append(f"{label}: invalid status.")
        if course.get("interest", "medium") not in ("low", "medium", "high"):
            errors.append(f"{label}: invalid interest level.")
        if "verified" in course and type(course["verified"]) is not bool:
            errors.append(f"{label}: verified must be true or false.")
        for field in ("categories", "semester_offered"):
            if field in course and not _string_list(course[field]):
                errors.append(f"{label}: {field} must be an array of text values.")
        if _string_list(course.get("semester_offered", [])) and any(
            value.casefold() not in {season.casefold() for season in SEASONS}
            for value in course.get("semester_offered", [])
        ):
            errors.append(f"{label}: offerings must use Fall, Winter, Spring or Summer.")
        try:
            _check_expression_size(course.get("prerequisites"))
            parse_requirement(course.get("prerequisites"))
        except ValueError as exc:
            errors.append(f"{label}: {exc}")
    if errors:
        raise ValidationError(errors)


def _string_list(value):
    return isinstance(value, list) and len(value) <= 200 and all(isinstance(item, str) for item in value)


def _check_expression_size(value, depth=0, count=None):
    count = count if count is not None else [0]
    count[0] += 1
    if depth > 12 or count[0] > 300:
        raise ValueError("Prerequisite expressions may have at most 12 levels and 300 nodes.")
    children = value if isinstance(value, list) else next(iter(value.values()), []) if isinstance(value, dict) else []
    if isinstance(children, list):
        for child in children:
            _check_expression_size(child, depth + 1, count)


def parse_schedule_request(payload, data):
    if not isinstance(payload, dict):
        raise ValidationError(["Schedule request must be a JSON object."])
    known = {course["id"] for course in data["courses"]}
    defaults = [course["id"] for course in data["courses"] if "target course" in course["categories"]]
    targets = payload.get("target_course_ids", defaults)
    completed = payload.get("completed_course_ids", [])
    excluded = payload.get("excluded_course_ids", [])
    errors = []
    for label, values in (("target_course_ids", targets), ("completed_course_ids", completed),
                          ("excluded_course_ids", excluded)):
        if not _string_list(values):
            errors.append(f"{label} must be an array of course IDs.")
        elif set(values) - known:
            errors.append(f"{label} contains unknown courses: {', '.join(sorted(set(values) - known))}")
    if errors:
        raise ValidationError(errors)
    if not targets:
        errors.append("Select at least one target course.")
    completed = set(completed) | {course["id"] for course in data["courses"] if course["status"] == "completed"}
    if set(excluded) & (set(targets) | completed):
        errors.append("Excluded courses cannot also be targets or completed courses.")
    numbers = {}
    for key, default, minimum, maximum in (
        ("max_credits", 16, 1, 40), ("max_difficult", 2, 0, 40),
        ("horizon", 8, 1, 16), ("start_year", 2027, 2000, 2100),
    ):
        value = payload.get(key, default)
        if type(value) is not int or not minimum <= value <= maximum:
            errors.append(f"{key} must be an integer from {minimum} to {maximum}.")
        numbers[key] = value
    include_summer = payload.get("include_summer", False)
    if type(include_summer) is not bool:
        errors.append("include_summer must be true or false.")
    season = payload.get("start_season", "Fall")
    if season not in (SEASONS if include_summer is True else SEASONS[:2]):
        errors.append("Choose an enabled starting season (enable summer terms for Spring/Summer).")
    objective = payload.get("objective", "fewest_courses")
    if objective not in ("fewest_courses", "fastest"):
        errors.append("objective must be fewest_courses or fastest.")
    strategy = payload.get("strategy", "constraint")
    if strategy not in ("constraint", "greedy", "compare"):
        errors.append("strategy must be constraint, greedy or compare.")
    time_limit = payload.get("time_limit", 5.0)
    if type(time_limit) not in (int, float) or not isfinite(time_limit) or not 0.01 <= time_limit <= 15:
        errors.append("time_limit must be a finite number from 0.01 to 15 seconds.")
    if errors:
        raise ValidationError(errors)
    return ScheduleRequest(
        targets=tuple(sorted(set(targets))), completed=frozenset(completed), excluded=frozenset(excluded),
        include_summer=include_summer, start_season=season, objective=objective,
        time_limit=float(time_limit), **numbers
    ), strategy
