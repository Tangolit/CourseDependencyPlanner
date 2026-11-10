from copy import deepcopy
import json

import pytest

from planner.data_store import ValidationError
from planner.graph_logic import normalize_dataset


@pytest.mark.parametrize("payload", [None, [], "text", 12])
def test_api_requires_object(client, payload):
    response = client.post("/api/schedule", data=json.dumps(payload), content_type="application/json")
    assert response.status_code == 400
    assert response.get_json()["errors"]


@pytest.mark.parametrize("fields", [
    {"target_course_ids": []}, {"target_course_ids": ["MISSING"]},
    {"target_course_ids": "B"}, {"max_credits": -1}, {"max_credits": True},
    {"horizon": 0}, {"horizon": 30}, {"start_year": 0},
    {"max_difficult": -1}, {"time_limit": float("nan")},
    {"include_summer": "false"}, {"start_season": "Summer"},
    {"objective": "magic"}, {"strategy": "magic"},
    {"excluded_course_ids": ["B"]}, {"completed_course_ids": ["MISSING"]},
])
def test_schedule_input_validation(client, fields):
    response = client.post("/api/schedule", json={"target_course_ids": ["B"], **fields})
    assert response.status_code == 400


def test_schedule_compare_is_read_only(client, repository):
    before = repository.data_path.read_bytes()
    response = client.post("/api/schedule", json={"strategy": "compare"})
    assert response.status_code == 200
    results = response.get_json()["results"]
    assert [result["strategy"] for result in results] == ["constraint", "greedy"]
    assert results[0]["status"] == "optimal"
    assert results[1]["status"] == "feasible"
    assert repository.data_path.read_bytes() == before
    assert repository.undo() is None


def test_stored_completion_is_used_but_current_is_not(client, repository):
    data = repository.get_data()
    data["courses"][0]["status"] = "current"
    repository.save_data(data)
    result = client.post("/api/schedule", json={}).get_json()["results"][0]
    assert result["course_count"] == 2
    data["courses"][0]["status"] = "completed"
    repository.save_data(data)
    result = client.post("/api/schedule", json={}).get_json()["results"][0]
    assert result["course_count"] == 1


def test_unknown_offerings_and_credits_are_explicit(client, repository):
    data = repository.get_data()
    data["courses"][0]["credits"] = 0
    repository.save_data(data)
    warnings = client.post("/api/schedule", json={}).get_json()["results"][0]["warnings"]
    assert any("Unknown offerings" in warning for warning in warnings)
    assert any("Zero/unknown credits" in warning for warning in warnings)


@pytest.mark.parametrize("change", [
    {"credits": "three"}, {"credits": -1}, {"credits": 1.5}, {"difficulty": 6},
    {"status": "fake"}, {"interest": "fake"}, {"id": 123}, {"categories": "tag"},
    {"semester_offered": ["Sometimes"]}, {"prerequisites": {"all_of": "A"}},
    {"prerequisites": {"all_of": [], "any_of": []}}, {"verified": "false"},
])
def test_malformed_courses_do_not_write(client, repository, change):
    before = repository.data_path.read_bytes()
    data = repository.get_data()
    data["courses"][0].update(change)
    response = client.post("/api/save", json={"data": data})
    assert response.status_code == 400
    assert repository.data_path.read_bytes() == before


@pytest.mark.parametrize("data", [[], {}, {"courses": []}, {"courses": [None]},
                                    {"courses": [{"id": "A"}], "meta": []}])
def test_invalid_dataset_shapes(client, data):
    assert client.post("/api/import", json={"data": data}).status_code == 400


def test_duplicate_and_self_reference_rejected(client, repository):
    data = repository.get_data()
    data["courses"].append(deepcopy(data["courses"][0]))
    assert client.post("/api/save", json={"data": data, "force": True}).status_code == 400
    data = repository.get_data()
    data["courses"][0]["prerequisites"] = {"all_of": ["A"]}
    assert client.post("/api/save", json={"data": data, "force": True}).status_code == 400


def test_cycle_warning_requires_confirmation_and_does_not_make_all_or_plans_invalid(client, repository):
    before = repository.data_path.read_bytes()
    data = repository.get_data()
    data["courses"][0]["prerequisites"] = {"all_of": ["B"]}
    response = client.post("/api/save", json={"data": data})
    assert response.status_code == 409
    assert any("Cycle" in warning for warning in response.get_json()["warnings"])
    assert repository.data_path.read_bytes() == before
    assert client.post("/api/save", json={"data": data, "force": True}).status_code == 200
    assert client.post("/api/schedule", json={}).get_json()["results"][0]["status"] == "infeasible"


def test_export_import_and_undo(client, repository):
    assert client.get("/").status_code == 200
    assert client.get("/api/state").status_code == 200
    data = client.get("/api/export").get_json()
    data["courses"][0]["title"] = "Updated title"
    assert client.post("/api/import", json={"data": data}).status_code == 200
    assert repository.get_data()["courses"][0]["title"] == "Updated title"
    assert client.post("/api/undo").status_code == 200
    assert repository.get_data()["courses"][0]["title"] == ""
    assert client.post("/api/undo").status_code == 400


def test_prerequisite_endpoint(client):
    result = client.post("/api/prerequisite-plan", json={}).get_json()
    assert result["status"] == "optimal"
    assert result["prerequisite_course_ids"] == ["A"]
    assert result["course_count"] == 2


def test_force_is_not_coerced_from_string(client, repository):
    response = client.post("/api/save", json={"data": repository.get_data(), "force": "false"})
    assert response.status_code == 400


def test_failed_atomic_write_does_not_record_undo(repository, monkeypatch):
    original = repository.data_path.read_bytes()

    def fail(*args):
        raise OSError("Simulated replace failure")

    monkeypatch.setattr("planner.data_store.os.replace", fail)
    with pytest.raises(OSError):
        repository.save_data(repository.get_data())
    assert repository.data_path.read_bytes() == original
    assert repository.undo() is None
    assert list(repository.data_path.parent.iterdir()) == [repository.data_path]


def test_deleted_default_tag_is_not_reintroduced():
    data = normalize_dataset({"tag_catalog": [], "courses": [{"id": "A"}]})
    assert data["tag_catalog"] == []


def test_repository_validation_exception_is_compatible(repository):
    with pytest.raises(ValidationError):
        repository.save_data({"courses": [{"id": "A", "credits": "bad"}]})
