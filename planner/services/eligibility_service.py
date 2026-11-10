from planner.domain.course import Course


class EligibilityService:
    def __init__(self, courses: dict[str, Course]):
        self.courses = courses

    def eligible(self, completed: set[str] | frozenset[str]) -> set[str]:
        return {course.id for course in self.courses.values()
                if course.id not in completed and course.requirement.satisfied(completed)}

    def marginal_unlocks(self, course_id: str, completed: set[str]) -> list[str]:
        if course_id in completed:
            return []
        before = self.eligible(completed)
        after = self.eligible(completed | {course_id})
        return sorted(after - before - {course_id})
