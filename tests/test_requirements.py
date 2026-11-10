import pytest

from planner.domain.requirements import AllOf, AnyOf, CourseRef, parse_requirement
from planner.graph_logic import evaluate_prerequisites, normalize_prerequisites


def test_composite_polymorphism_and_round_trip():
    requirement = AllOf((AnyOf((CourseRef("214"), CourseRef("217"))), CourseRef("425")))
    assert requirement.satisfied({"214", "425"})
    assert not requirement.satisfied({"214"})
    assert not requirement.satisfied({"425"})
    assert requirement.course_ids() == {"214", "217", "425"}
    assert parse_requirement(requirement.serialize()) == requirement
    assert evaluate_prerequisites(requirement.serialize(), {"217", "425"})


def test_nested_and_inside_or_is_not_flattened():
    requirement = AnyOf((AllOf((CourseRef("A"), CourseRef("B"))), CourseRef("C")))
    assert not requirement.satisfied({"A"})
    assert requirement.satisfied({"A", "B"})
    assert requirement.satisfied({"C"})
    explanation = requirement.explain_missing({"A"})
    assert explanation["alternatives"] == [["B"], ["C"]]


def test_shared_direct_requirements_are_charged_once():
    requirement = AllOf((AnyOf((CourseRef("A"), CourseRef("B"))),
                         AnyOf((CourseRef("B"), CourseRef("C")))))
    assert requirement.missing_options(set()) == {frozenset({"B"}), frozenset({"A", "C"})}


def test_empty_group_semantics():
    assert AllOf().satisfied(set())
    assert not AnyOf().satisfied(set())
    assert AnyOf().missing_options(set()) == set()
    assert normalize_prerequisites(None) == {"all_of": []}
    assert parse_requirement(["A", "B"]) == AllOf((CourseRef("A"), CourseRef("B")))


@pytest.mark.parametrize("value", [True, 3, "", {}, {"all_of": "A"},
                                       {"all_of": [], "any_of": []}, {"unknown": []}])
def test_malformed_logic_is_rejected(value):
    with pytest.raises(ValueError):
        parse_requirement(value)
