from __future__ import annotations

from copy import deepcopy
from itertools import islice

import networkx as nx

from planner.domain.course import Course
from planner.domain.requirements import AllOf, AnyOf, CourseRef, parse_requirement
from planner.services.eligibility_service import EligibilityService
from planner.services.prerequisite_planner import PrerequisitePlanner
from planner.services.schedule_optimizer import requirement_witness


DEFAULT_STATUSES = ["completed", "current", "planned", "interested", "not_started"]
DEFAULT_INTEREST_LEVELS = ["low", "medium", "high"]
DEFAULT_TAGS = [
    "target course",
    "prerequisite / foundation",
    "analysis",
    "algebra",
    "combinatorics",
    "probability / statistics",
    "topology",
    "number theory",
    "logic",
    "applied math",
    "theoretical CS",
    "machine learning / data science",
]
STATUS_COLORS = {
    "completed": "#4caf50",
    "current": "#f4c430",
    "planned": "#2f80ed",
    "interested": "#8854d0",
    "not_started": "#8d99ae",
}


def normalize_course(course: dict) -> dict:
    normalized = {
        "id": (course.get("id") or "").strip(),
        "title": (course.get("title") or "").strip(),
        "description": (course.get("description") or "").strip(),
        "credits": int(course.get("credits") or 0),
        "difficulty": int(course.get("difficulty", 3)),
        "status": course.get("status") if course.get("status") in DEFAULT_STATUSES else "not_started",
        "interest": course.get("interest") if course.get("interest") in DEFAULT_INTEREST_LEVELS else "medium",
        "categories": _normalize_list(course.get("categories")),
        "semester_offered": _normalize_list(course.get("semester_offered")),
        "source_url": (course.get("source_url") or "").strip(),
        "verified": bool(course.get("verified")),
        "notes": (course.get("notes") or "").strip(),
        "prerequisite_text": (course.get("prerequisite_text") or "").strip(),
        "prerequisites": normalize_prerequisites(course.get("prerequisites")),
    }
    return normalized


def normalize_dataset(data: dict) -> dict:
    meta = deepcopy(data.get("meta") or {})
    meta.setdefault(
        "disclaimer",
        "Sample data is illustrative only. Official University of Michigan LSA, Math Department, and Course Guide information controls for actual enrollment requirements.",
    )
    meta.setdefault("target_course_id", "")
    courses = [normalize_course(course) for course in data.get("courses", [])]
    known_tags = set(DEFAULT_TAGS if "tag_catalog" not in data else [])
    known_tags.update(_normalize_list(data.get("tag_catalog")))
    for course in courses:
        known_tags.update(course["categories"])
    normalized = {
        "meta": meta,
        "tag_catalog": sorted(tag for tag in known_tags if tag),
        "courses": sorted(courses, key=lambda item: item["id"]),
    }
    return normalized


def normalize_prerequisites(expr):
    requirement = parse_requirement(expr)
    if isinstance(requirement, CourseRef):
        requirement = AllOf((requirement,))
    return requirement.serialize()


def _normalize_list(values) -> list[str]:
    if not values:
        return []
    if isinstance(values, str):
        values = [values]
    seen = []
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text and text not in seen:
            seen.append(text)
    return seen


def build_course_graph(data: dict) -> nx.DiGraph:
    graph = nx.DiGraph()
    for course in data["courses"]:
        graph.add_node(course["id"], course=course)

    for course in data["courses"]:
        edge_map = {}
        for meta in extract_prerequisite_edges(course["prerequisites"]):
            src = meta["course_id"]
            if not graph.has_node(src):
                graph.add_node(src, course={"id": src, "title": "Unknown course"})
            key = (src, course["id"])
            edge_map.setdefault(key, []).append(meta)

        for (src, dest), entries in edge_map.items():
            labels = []
            for entry in entries:
                label = f"{entry['group_type'].replace('_', ' ').upper()} {entry['group_index'] + 1}"
                if label not in labels:
                    labels.append(label)
            graph.add_edge(src, dest, labels=labels, entries=entries)
    return graph


def extract_prerequisite_edges(expr, parent_type="all_of", group_path=()):
    if isinstance(expr, str):
        yield {
            "course_id": expr.strip(),
            "group_type": parent_type,
            "group_index": group_path[-1] if group_path else 0,
            "group_path": group_path,
        }
        return

    if not isinstance(expr, dict):
        return

    for key in ("all_of", "any_of"):
        if key not in expr:
            continue
        items = expr.get(key) or []
        for index, item in enumerate(items):
            if isinstance(item, str):
                yield {
                    "course_id": item.strip(),
                    "group_type": key,
                    "group_index": index,
                    "group_path": group_path + (index,),
                }
            else:
                yield from extract_prerequisite_edges(item, key, group_path + (index,))


def expression_to_course_ids(expr) -> set[str]:
    return set(parse_requirement(expr).course_ids())


def evaluate_prerequisites(expr, completed_courses: set[str]) -> bool:
    return parse_requirement(expr).satisfied(completed_courses)


def _direct_missing(requirement, completed):
    if requirement.satisfied(completed):
        return set()
    if isinstance(requirement, CourseRef):
        return {requirement.course_id}
    choices = [_direct_missing(child, completed) for child in requirement.children]
    if isinstance(requirement, AnyOf):
        valid = [choice for choice in choices if choice is not None]
        return min(valid, key=lambda ids: (len(ids), sorted(ids))) if valid else None
    if any(choice is None for choice in choices):
        return None
    return set().union(*choices)


def summarize_requirement_groups(expr, completed_courses: set[str]):
    requirement = parse_requirement(expr)
    root_items = requirement.children if isinstance(requirement, AllOf) else (requirement,)
    groups = []
    for item in root_items:
        any_of = isinstance(item, AnyOf)
        satisfied = item.satisfied(completed_courses)
        missing = _direct_missing(item, completed_courses)
        groups.append({
            "type": "any_of" if any_of else "all_of", "group_index": len(groups),
            "label": "One of these options is required" if any_of else "All of these are required",
            "expression": item.serialize(), "course_ids": sorted(item.course_ids()),
            "satisfied": satisfied, "missing": sorted(missing or []),
            "satisfied_by": sorted(requirement_witness(item, completed_courses)) if satisfied else [],
        })
    return groups


def get_direct_prerequisites(graph: nx.DiGraph, course_id: str) -> list[str]:
    if not graph.has_node(course_id):
        return []
    return sorted(graph.predecessors(course_id))


def get_all_prerequisites(graph: nx.DiGraph, course_id: str) -> list[str]:
    if not graph.has_node(course_id):
        return []
    return sorted(nx.ancestors(graph, course_id))


def get_directly_unlocked_courses(graph: nx.DiGraph, course_id: str) -> list[str]:
    if not graph.has_node(course_id):
        return []
    return sorted(graph.successors(course_id))


def get_all_unlocked_courses(graph: nx.DiGraph, course_id: str) -> list[str]:
    if not graph.has_node(course_id):
        return []
    return sorted(nx.descendants(graph, course_id))


def get_missing_prerequisites(data: dict, target_course_id: str, completed_courses: set[str]):
    lookup = build_course_lookup(data)
    course = lookup.get(target_course_id)
    if not course:
        return {"missing_course_ids": [], "groups": []}

    groups = summarize_requirement_groups(course["prerequisites"], completed_courses)
    courses = {cid: Course.from_dict(item) for cid, item in lookup.items()}
    plan = PrerequisitePlanner(courses, time_limit=0.3, max_states=10_000).plan(
        [target_course_id], completed_courses
    )
    return {"missing_course_ids": sorted(set(plan.course_ids) - {target_course_id}),
            "groups": groups, "status": plan.status,
            "meaning": "One minimum-count prerequisite closure, not every OR alternative."}


def find_paths_to_target(graph: nx.DiGraph, target_course_id: str, completed_courses: set[str], max_paths: int = 20):
    if not graph.has_node(target_course_id):
        return []

    relevant_nodes = set(nx.ancestors(graph, target_course_id))
    relevant_nodes.add(target_course_id)
    subgraph = graph.subgraph(relevant_nodes).copy()
    if not subgraph.nodes:
        return []

    start_nodes = [node for node in subgraph.nodes if subgraph.in_degree(node) == 0 or node in completed_courses]
    paths = []
    for start in sorted(set(start_nodes)):
        if start == target_course_id:
            continue
        try:
            for path in nx.all_simple_paths(subgraph, source=start, target=target_course_id):
                paths.append(
                    {
                        "path": path,
                        "completed_prefix": [node for node in path if node in completed_courses],
                    }
                )
                if len(paths) >= max_paths:
                    return paths
        except nx.NetworkXNoPath:
            continue
    if not paths and target_course_id in subgraph:
        paths.append({"path": [target_course_id], "completed_prefix": []})
    return paths


def rank_gateway_courses(graph: nx.DiGraph, data: dict | None = None) -> list[dict]:
    rankings = []
    if data is None:
        data = {"courses": [attributes["course"] for _, attributes in graph.nodes(data=True)
                            if "status" in attributes.get("course", {})]}
    courses = {course["id"]: Course.from_dict(course) for course in data["courses"]}
    completed = get_completed_courses(data)
    eligibility = EligibilityService(courses)
    for course_id in graph.nodes:
        if course_id in completed or course_id not in courses:
            continue
        unlocked = eligibility.marginal_unlocks(course_id, completed)
        if not unlocked:
            continue
        rankings.append(
            {
                "course_id": course_id,
                "unlock_count": len(unlocked),
                "unlocks": unlocked[:8],
                "structural_downstream_count": len(nx.descendants(graph, course_id)),
                "eligible_now": course_id in eligibility.eligible(completed),
            }
        )
    rankings.sort(key=lambda item: (-item["unlock_count"], item["course_id"]))
    return rankings


def requirement_edge_metadata(requirement, completed):
    occurrences = {}

    def visit(item, optional=False, active=True):
        if isinstance(item, CourseRef):
            occurrences.setdefault(item.course_id, []).append((optional, active))
            return
        choose_satisfied = isinstance(item, AnyOf) and item.satisfied(completed)
        for child in item.children:
            visit(child, optional or isinstance(item, AnyOf),
                  active and (not choose_satisfied or child.satisfied(completed)))

    visit(requirement)
    return {cid: {
        "isAnyOf": all(optional for optional, _ in entries),
        "isAllOf": any(not optional for optional, _ in entries),
        "hideWhenAlternativeSatisfied": not any(active for _, active in entries),
        "alternativeSatisfiedBy": [cid] if cid in completed and any(active for _, active in entries) else [],
    } for cid, entries in occurrences.items()}


def detect_prerequisite_cycles(graph: nx.DiGraph) -> list[list[str]]:
    try:
        cycles = list(islice(nx.simple_cycles(graph), 20))
    except nx.NetworkXNoCycle:
        return []
    normalized = []
    for cycle in cycles:
        if not cycle:
            continue
        cycle.append(cycle[0])
        normalized.append(cycle)
    return normalized


def build_course_lookup(data: dict) -> dict[str, dict]:
    return {course["id"]: course for course in data["courses"]}


def get_completed_courses(data: dict) -> set[str]:
    return {course["id"] for course in data["courses"] if course["status"] == "completed"}


def find_next_options(data: dict, completed_courses: set[str]) -> list[dict]:
    options = []
    for course in data["courses"]:
        if course["status"] == "completed":
            continue
        groups = summarize_requirement_groups(course["prerequisites"], completed_courses)
        ready = evaluate_prerequisites(course["prerequisites"], completed_courses)
        if ready:
            options.append(
                {
                    "course_id": course["id"],
                    "title": course["title"],
                    "status": course["status"],
                    "interest": course["interest"],
                    "groups": groups,
                }
            )
    return sorted(options, key=lambda item: (item["status"], item["course_id"]))


def build_target_analysis(data: dict, graph: nx.DiGraph, target_course_id: str, completed_courses: set[str]):
    if not target_course_id or not graph.has_node(target_course_id):
        return None

    relevant_nodes = set(nx.ancestors(graph, target_course_id))
    relevant_nodes.add(target_course_id)
    missing = get_missing_prerequisites(data, target_course_id, completed_courses)
    paths = find_paths_to_target(graph, target_course_id, completed_courses)
    return {
        "target_course_id": target_course_id,
        "relevant_course_ids": sorted(relevant_nodes),
        "missing_prerequisites": missing,
        "paths": paths,
        "completed_relevant_course_ids": sorted(node for node in relevant_nodes if node in completed_courses),
        "unfinished_relevant_course_ids": sorted(node for node in relevant_nodes if node not in completed_courses),
    }


def build_state_payload(data: dict) -> dict:
    data = normalize_dataset(data)
    graph = build_course_graph(data)
    completed_courses = get_completed_courses(data)
    course_lookup = build_course_lookup(data)
    nodes = []
    for course_id, node_data in graph.nodes(data=True):
        course = course_lookup.get(course_id) or normalize_course(node_data.get("course") or {"id": course_id, "title": "Missing course"})
        unlocked_count = len(get_all_unlocked_courses(graph, course["id"]))
        is_target = course["id"] == data["meta"].get("target_course_id")
        nodes.append(
            {
                "data": {
                    "id": course["id"],
                    "label": course["id"],
                    "title": course["title"],
                    "status": course["status"],
                    "interest": course["interest"],
                    "verified": course["verified"],
                    "categories": course["categories"],
                    "size": 56 + (18 if course["interest"] == "high" else 0) + (12 if is_target or "target course" in course["categories"] else 0),
                    "borderWidth": 2 + (2 if is_target or "target course" in course["categories"] else 0),
                    "unlockedCount": unlocked_count,
                    "color": STATUS_COLORS.get(course["status"], STATUS_COLORS["not_started"]),
                    "isTarget": is_target,
                    "isPlaceholder": course_id not in course_lookup,
                }
            }
        )

    edges = []
    for src, dest, edge_data in graph.edges(data=True):
        course = course_lookup.get(dest)
        semantics = requirement_edge_metadata(parse_requirement(course["prerequisites"]), completed_courses)[src]
        edges.append(
            {
                "data": {
                    "id": f"{src}->{dest}",
                    "source": src,
                    "target": dest,
                    "labels": edge_data.get("labels", []),
                    "label": " / ".join(edge_data.get("labels", [])),
                    "verified": bool(course and course.get("verified")),
                    **semantics,
                }
            }
        )

    course_insights = {}
    for course in data["courses"]:
        course_insights[course["id"]] = {
            "direct_prerequisites": get_direct_prerequisites(graph, course["id"]),
            "all_prerequisites": get_all_prerequisites(graph, course["id"]),
            "directly_unlocked_courses": get_directly_unlocked_courses(graph, course["id"]),
            "all_unlocked_courses": get_all_unlocked_courses(graph, course["id"]),
            "requirement_groups": summarize_requirement_groups(course["prerequisites"], completed_courses),
        }

    target_analysis = build_target_analysis(data, graph, data["meta"].get("target_course_id", ""), completed_courses)

    return {
        "data": data,
        "graph": {
            "nodes": nodes,
            "edges": edges,
            "gateway_courses": rank_gateway_courses(graph, data),
            "cycles": detect_prerequisite_cycles(graph),
            "next_options": find_next_options(data, completed_courses),
            "course_insights": course_insights,
            "target_analysis": target_analysis,
            "legend": STATUS_COLORS,
        },
    }
