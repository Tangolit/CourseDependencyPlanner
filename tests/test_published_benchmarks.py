from hashlib import sha256
import json
from math import isfinite
from pathlib import Path

from benchmarks.schedule_benchmark import SUCCESS_STATUSES, summarize
from planner.domain.course import Course
from planner.services.schedule_optimizer import ScheduleRequest, verify_schedule


REPORT_PATH = Path(__file__).resolve().parents[1] / "benchmarks/results/windows-ryzen5850u.json"


def test_published_markdown_table_matches_raw_measurements():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    summaries = {(item["case"], item["strategy"]): item for item in report["summary"]}
    labels = {f"{size}-course layered": f"layered_{size}" for size in (20, 50, 100, 200)}
    labels.update({"AND/OR + offerings": "and_or_offerings", "Credit-infeasible": "credit_infeasible",
                   "Cycle-infeasible": "cycle_infeasible"})
    checked = set()
    for line in REPORT_PATH.parents[1].joinpath("RESULTS.md").read_text(encoding="utf-8").splitlines():
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) != 6 or cells[0] not in labels:
            continue
        key = (labels[cells[0]], cells[1].lower())
        summary = summaries[key]
        assert cells[2] == f"{summary['median_elapsed_ms']:.3f}"
        assert cells[3] == f"{summary['min_elapsed_ms']:.3f}-{summary['max_elapsed_ms']:.3f}"
        assert cells[4] == "; ".join(f"{status} {count}/{summary['trials']}"
                                     for status, count in summary["status_counts"].items())
        sizes = summary["plan_sizes"]
        expected_sizes = []
        for size in sizes:
            label = f"{size['course_count']} / {size['semester_count']}"
            if len(sizes) > 1:
                label += f" ({size['occurrences']} {'run' if size['occurrences'] == 1 else 'runs'})"
            expected_sizes.append(label)
        assert cells[5] == ("; ".join(expected_sizes) or "-")
        checked.add(key)
    assert checked == set(summaries)


def test_published_summaries_are_derived_from_every_raw_sample():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    assert report["summary"] == summarize(report["samples"])
    repeats = report["methodology"]["measured_repeats"]
    expected = {(case["name"], strategy, trial) for case in report["cases"]
                for strategy in ("greedy", "constraint") for trial in range(1, repeats + 1)}
    actual = [(sample["case"], sample["strategy"], sample["trial"]) for sample in report["samples"]]
    assert len(actual) == len(set(actual))
    assert set(actual) == expected
    assert all(isfinite(sample["elapsed_ms"]) and sample["elapsed_ms"] >= 0 for sample in report["samples"])


def test_published_inputs_and_complete_schedules_are_verifiable():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    cases = {case["name"]: case for case in report["cases"]}
    for case in cases.values():
        digest = sha256(json.dumps(case["input"], sort_keys=True).encode()).hexdigest()
        assert case["input_sha256"] == digest
    for sample in report["samples"]:
        if sample["status"] not in SUCCESS_STATUSES:
            assert sample["assignments"] is None
            assert sample["validation"] == "not_applicable"
            continue
        inputs = cases[sample["case"]]["input"]
        courses = {record["id"]: Course.from_dict(record) for record in inputs["courses"]}
        options = {**inputs["request"], "targets": tuple(inputs["request"]["targets"]),
                   "completed": frozenset(inputs["request"]["completed"]),
                   "excluded": frozenset(inputs["request"]["excluded"])}
        request = ScheduleRequest(**options)
        assignments = sample["assignments"]
        term_count = max(assignments.values(), default=-1) + 1
        terms = [{"index": index, "label": term.label,
                  "credits": sum(courses[cid].credits for cid, slot in assignments.items() if slot == index),
                  "courses": [{"id": cid} for cid, slot in assignments.items() if slot == index]}
                 for index, term in enumerate(request.terms()[:term_count])]
        assert verify_schedule(courses, request, {"terms": terms}) == []
        assert sample["validation"] == "passed"
        assert sample["course_count"] == len(assignments)
        assert sample["semester_count"] == term_count
        assert sample["objective_values"] == {
            "course_count": len(assignments), "semester_count": term_count,
            "workload_squared": sum(term["credits"] ** 2 for term in terms),
        }
