import json

import pytest

from app import create_app
from planner.data_store import CourseDataStore
from planner.domain.course import Course
from planner.graph_logic import normalize_dataset


@pytest.fixture
def dataset():
    def build(*records):
        return normalize_dataset({"meta": {}, "tag_catalog": [], "courses": [
            {"id": record} if isinstance(record, str) else record for record in records
        ]})
    return build


@pytest.fixture
def catalog(dataset):
    def build(*records):
        return {record["id"]: Course.from_dict(record) for record in dataset(*records)["courses"]}
    return build


@pytest.fixture
def repository(tmp_path, dataset):
    path = tmp_path / "courses.json"
    path.write_text(json.dumps(dataset(
        {"id": "A", "credits": 3},
        {"id": "B", "credits": 3, "categories": ["target course"], "prerequisites": {"all_of": ["A"]}},
    )), encoding="utf-8")
    return CourseDataStore(path)


@pytest.fixture
def client(repository):
    app = create_app(repository)
    app.config["TESTING"] = True
    return app.test_client()
