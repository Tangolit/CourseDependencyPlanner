from flask import Flask, jsonify

from planner.api.routes import create_routes
from planner.data_store import CourseDataStore
from planner.repositories.base import CourseRepository
from planner.validation.input import ValidationError


def create_app(repository: CourseRepository | None = None) -> Flask:
    application = Flask(__name__)
    application.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024
    application.register_blueprint(create_routes(repository if repository is not None else CourseDataStore()))

    @application.errorhandler(ValidationError)
    def invalid_input(error):
        return jsonify({"ok": False, "errors": error.errors, "warnings": error.warnings}), 400

    @application.errorhandler(413)
    def too_large(error):
        return jsonify({"ok": False, "errors": ["Request body exceeds the 2 MB limit."]}), 413

    return application


app = create_app()


if __name__ == "__main__":
    app.run(debug=True)
