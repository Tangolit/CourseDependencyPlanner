from planner.graph_logic import (
    build_course_graph,
    build_state_payload,
    get_missing_prerequisites,
    rank_gateway_courses,
    summarize_requirement_groups,
)
from planner.services.prerequisite_planner import PrerequisitePlanner


def test_global_shared_dependency_beats_independent_choices(catalog):
    courses = catalog("A", "B", "C",
                      {"id": "T1", "prerequisites": {"any_of": ["A", "B"]}},
                      {"id": "T2", "prerequisites": {"any_of": ["B", "C"]}})
    result = PrerequisitePlanner(courses).plan(["T1", "T2"], set())
    assert result.status == "optimal"
    assert set(result.course_ids) == {"B", "T1", "T2"}


def test_keep_larger_local_choice_when_shared_globally(catalog):
    courses = catalog("A", "B", "C",
                      {"id": "T1", "prerequisites": {"any_of": ["A", {"all_of": ["B", "C"]}]}},
                      {"id": "T2", "prerequisites": {"all_of": ["B", "C"]}})
    assert set(PrerequisitePlanner(courses).plan(["T1", "T2"], set()).course_ids) == {"B", "C", "T1", "T2"}


def test_cycle_is_avoidable_through_an_alternative(catalog):
    courses = catalog("C", {"id": "A", "prerequisites": {"any_of": ["B", "C"]}},
                      {"id": "B", "prerequisites": {"all_of": ["A"]}})
    result = PrerequisitePlanner(courses).plan(["A"], set())
    assert result.status == "optimal"
    assert set(result.course_ids) == {"A", "C"}
    assert PrerequisitePlanner(courses).plan(["A"], set(), {"C"}).status == "infeasible"


def test_completed_stops_prerequisite_traversal(catalog):
    courses = catalog({"id": "A", "prerequisites": {"all_of": ["Missing"]}},
                      {"id": "T", "prerequisites": {"all_of": ["A"]}})
    assert PrerequisitePlanner(courses).plan(["T"], {"A"}).course_ids == ("T",)


def test_search_limit_is_not_infeasibility(catalog):
    result = PrerequisitePlanner(catalog("A"), max_states=0).plan(["A"], set())
    assert result.status == "unknown"


def test_missing_prerequisites_returns_one_valid_closure(dataset):
    data = dataset("A", "B", {"id": "T", "prerequisites": {"any_of": ["A", "B"]}})
    result = get_missing_prerequisites(data, "T", set())
    assert result["status"] == "optimal"
    assert len(result["missing_course_ids"]) == 1


def test_gateway_metric_respects_and_or(dataset):
    data = dataset("A", "B", {"id": "C", "prerequisites": {"all_of": ["A", "B"]}},
                   {"id": "D", "prerequisites": {"any_of": ["A", "B"]}})
    rankings = {item["course_id"]: item for item in rank_gateway_courses(build_course_graph(data), data)}
    assert rankings["A"]["unlocks"] == ["D"]
    assert rankings["A"]["structural_downstream_count"] == 2


def test_completed_or_hides_only_redundant_edges(dataset):
    data = dataset({"id": "A", "status": "completed"}, "B",
                   {"id": "T", "prerequisites": {"any_of": ["A", "B"]}})
    edges = {item["data"]["source"]: item["data"] for item in build_state_payload(data)["graph"]["edges"]}
    assert edges["A"]["isAnyOf"]
    assert not edges["A"]["hideWhenAlternativeSatisfied"]
    assert edges["B"]["hideWhenAlternativeSatisfied"]


def test_required_occurrence_is_not_hidden_by_satisfied_or(dataset):
    data = dataset({"id": "A", "status": "completed"}, "B", {"id": "T", "prerequisites": {
        "all_of": ["B", {"any_of": ["A", "B"]}]
    }})
    edge = next(item["data"] for item in build_state_payload(data)["graph"]["edges"]
                if item["data"]["source"] == "B")
    assert edge["isAllOf"]
    assert not edge["isAnyOf"]
    assert not edge["hideWhenAlternativeSatisfied"]


def test_partial_nested_branch_does_not_satisfy_or(dataset):
    data = dataset({"id": "A", "status": "completed"}, "B", "C", {"id": "T", "prerequisites": {
        "any_of": [{"all_of": ["A", "B"]}, "C"]
    }})
    graph = build_state_payload(data)["graph"]
    assert not graph["course_insights"]["T"]["requirement_groups"][0]["satisfied"]
    assert not any(item["data"]["hideWhenAlternativeSatisfied"] for item in graph["edges"])


def test_impossible_nested_option_is_not_reported_as_a_valid_missing_set():
    groups = summarize_requirement_groups({"any_of": [
        {"all_of": ["A", {"any_of": []}]}, "B"
    ]}, set())
    assert groups[0]["missing"] == ["B"]
