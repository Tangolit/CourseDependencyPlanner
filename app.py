from flask import Flask, jsonify, render_template, request, send_file

from planner.data_store import CourseDataStore, ValidationError
from planner.graph_logic import build_state_payload


app = Flask(__name__)
store = CourseDataStore()


@app.route("/")
def index():
    return render_template("index.html")


@app.get("/api/state")
def get_state():
    return jsonify(build_state_payload(store.get_data()))


@app.post("/api/save")
def save_state():
    payload = request.get_json(silent=True) or {}
    data = payload.get("data")
    force = bool(payload.get("force"))

    if data is None:
        return jsonify({"ok": False, "errors": ["Request body must include a data object."]}), 400

    try:
        saved_data, warnings = store.save_data(data, force=force)
    except ValidationError as exc:
        return jsonify({"ok": False, "errors": exc.errors, "warnings": exc.warnings}), 400

    if warnings and not force:
        return jsonify({"ok": False, "warnings": warnings, "needs_confirmation": True}), 409

    return jsonify({"ok": True, "warnings": warnings, "state": build_state_payload(saved_data)})


@app.post("/api/import")
def import_state():
    payload = request.get_json(silent=True) or {}
    data = payload.get("data")
    force = bool(payload.get("force"))

    if data is None:
        return jsonify({"ok": False, "errors": ["Import request must include parsed JSON data."]}), 400

    try:
        saved_data, warnings = store.import_data(data, force=force)
    except ValidationError as exc:
        return jsonify({"ok": False, "errors": exc.errors, "warnings": exc.warnings}), 400

    if warnings and not force:
        return jsonify({"ok": False, "warnings": warnings, "needs_confirmation": True}), 409

    return jsonify({"ok": True, "warnings": warnings, "state": build_state_payload(saved_data)})


@app.post("/api/undo")
def undo_last_change():
    restored = store.undo()
    if restored is None:
        return jsonify({"ok": False, "errors": ["Nothing to undo yet."]}), 400
    return jsonify({"ok": True, "state": build_state_payload(restored)})


@app.get("/api/export")
def export_state():
    export_path = store.write_export_snapshot()
    return send_file(export_path, as_attachment=True, download_name="courses-export.json")


if __name__ == "__main__":
    app.run(debug=True)
