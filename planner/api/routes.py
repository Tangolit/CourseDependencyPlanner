from hashlib import sha256
from io import BytesIO
import json

from flask import Blueprint, jsonify, render_template, request, send_file

from planner.domain.course import Course
from planner.graph_logic import build_state_payload
from planner.repositories.base import CourseRepository
from planner.services.prerequisite_planner import PrerequisitePlanner
from planner.services.schedule_optimizer import ConstraintScheduler, GreedyScheduler, verify_schedule
from planner.validation.input import ValidationError, parse_schedule_request


def create_routes(repository: CourseRepository) -> Blueprint:
    routes = Blueprint("planner", __name__)

    @routes.get("/")
    def index():
        return render_template("index.html")

    @routes.get("/api/state")
    def get_state():
        return jsonify(build_state_payload(repository.get_data()))

    @routes.post("/api/save")
    @routes.post("/api/import")
    def save_state():
        payload = _body()
        if "data" not in payload:
            raise ValidationError(["Request body must include a data object."])
        force = payload.get("force", False)
        if type(force) is not bool:
            raise ValidationError(["force must be true or false."])
        operation = repository.import_data if request.path == "/api/import" else repository.save_data
        saved_data, warnings = operation(payload["data"], force=force)
        if warnings and not force:
            return jsonify({"ok": False, "warnings": warnings, "needs_confirmation": True}), 409
        return jsonify({"ok": True, "warnings": warnings, "state": build_state_payload(saved_data)})

    @routes.post("/api/undo")
    def undo_last_change():
        restored = repository.undo()
        if restored is None:
            raise ValidationError(["Nothing to undo yet."])
        return jsonify({"ok": True, "state": build_state_payload(restored)})

    @routes.get("/api/export")
    def export_state():
        content = (json.dumps(repository.get_data(), indent=2) + "\n").encode("utf-8")
        return send_file(BytesIO(content), mimetype="application/json", as_attachment=True,
                         download_name="courses-export.json")

    @routes.post("/api/schedule")
    def schedule():
        payload = _body()
        data = repository.get_data()
        options, strategy = parse_schedule_request(payload, data)
        courses = {course["id"]: Course.from_dict(course) for course in data["courses"]}
        strategies = {"constraint": ConstraintScheduler(), "greedy": GreedyScheduler()}
        names = strategies if strategy == "compare" else [strategy]
        results = []
        for name in names:
            try:
                result = strategies[name].solve(courses, options)
            except ImportError:
                return jsonify({"ok": False, "errors": [
                    "OR-Tools is not installed. Run .venv\\Scripts\\python.exe -m pip install -r requirements.txt "
                    "or choose the greedy strategy."
                ]}), 503
            if result["status"] in ("optimal", "feasible"):
                errors = verify_schedule(courses, options, result)
                if errors:
                    raise RuntimeError("Scheduler postconditions failed: " + "; ".join(errors))
            results.append(result)
        return jsonify({"ok": True, "results": results, "catalog_fingerprint": _fingerprint(data),
                        "completed_course_ids": sorted(options.completed)})

    @routes.post("/api/prerequisite-plan")
    def prerequisite_plan():
        payload = _body()
        data = repository.get_data()
        options, _ = parse_schedule_request(payload, data)
        courses = {course["id"]: Course.from_dict(course) for course in data["courses"]}
        result = PrerequisitePlanner(courses, time_limit=options.time_limit).plan(
            options.targets, options.completed, options.excluded
        )
        return jsonify({
            "ok": True, "status": result.status, "optimal": result.status == "optimal",
            "course_ids": result.course_ids,
            "prerequisite_course_ids": sorted(set(result.course_ids) - set(options.targets)),
            "target_course_ids": options.targets, "course_count": len(result.course_ids),
            "explored_states": result.explored_states, "alternatives_count": result.alternatives_count,
            "message": "Minimum number of additional courses across all targets; ignores term constraints.",
        })

    return routes


def _body():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise ValidationError(["Request body must be a JSON object."])
    return payload


def _fingerprint(data):
    return sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
