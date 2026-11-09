from __future__ import annotations

from collections import deque
from copy import deepcopy

import networkx as nx


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
    known_tags = set(DEFAULT_TAGS)
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
    if not expr:
        return {"all_of": []}
    if isinstance(expr, str):
        return {"all_of": [expr.strip()]}
    if isinstance(expr, list):
        return {"all_of": [item.strip() for item in expr if isinstance(item, str) and item.strip()]}
    if isinstance(expr, dict):
        if "all_of" in expr:
            return {"all_of": [normalize_prerequisites(item) if isinstance(item, (dict, list)) else item.strip() for item in expr["all_of"] if _valid_prereq_item(item)]}
        if "any_of" in expr:
            return {"any_of": [normalize_prerequisites(item) if isinstance(item, (dict, list)) else item.strip() for item in expr["any_of"] if _valid_prereq_item(item)]}
    return {"all_of": []}


def _valid_prereq_item(item) -> bool:
    if isinstance(item, str):
        return bool(item.strip())
    return isinstance(item, (dict, list))


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
    course_ids = set()
    if isinstance(expr, str):
        if expr.strip():
            course_ids.add(expr.strip())
        return course_ids
    if isinstance(expr, dict):
        for key in ("all_of", "any_of"):
            for item in expr.get(key, []):
                course_ids.update(expression_to_course_ids(item))
    return course_ids


def evaluate_prerequisites(expr, completed_courses: set[str]) -> bool:
    if not expr:
        return True
    if isinstance(expr, str):
        return expr.strip() in completed_courses
    if isinstance(expr, dict):
        if "all_of" in expr:
            return all(evaluate_prerequisites(item, completed_courses) for item in expr.get("all_of", []))
        if "any_of" in expr:
            options = expr.get("any_of", [])
            if not options:
                return False
            return any(evaluate_prerequisites(item, completed_courses) for item in options)
    return True


def summarize_requirement_groups(expr, completed_courses: set[str]):
    if not expr:
        return []
    root_items = expr.get("all_of", []) if isinstance(expr, dict) and "all_of" in expr else [expr]
    groups = []
    for item in root_items:
        if isinstance(item, str):
            course_id = item.strip()
            groups.append(
                {
                    "type": "all_of",
                    "group_index": len(groups),
                    "label": "All of these are required",
                    "course_ids": [course_id],
                    "satisfied": course_id in completed_courses,
                    "missing": [] if course_id in completed_courses else [course_id],
                    "satisfied_by": [course_id] if course_id in completed_courses else [],
                }
            )
            continue

        if isinstance(item, dict):
            group_type = "any_of" if "any_of" in item else "all_of"
            course_ids = sorted(expression_to_course_ids(item))
            satisfied_by = sorted(course_id for course_id in course_ids if course_id in completed_courses)
            groups.append(
                {
                    "type": group_type,
                    "group_index": len(groups),
                    "label": "One of these options is required" if group_type == "any_of" else "All of these are required",
                    "course_ids": course_ids,
                    "satisfied": evaluate_prerequisites(item, completed_courses),
                    "missing": [] if evaluate_prerequisites(item, completed_courses) else course_ids,
                    "satisfied_by": satisfied_by,
                }
            )
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
    missing = []
    for group in groups:
        if not group["satisfied"]:
            for course_id in group["missing"]:
                if course_id not in missing:
                    missing.append(course_id)
    return {"missing_course_ids": missing, "groups": groups}


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


def rank_gateway_courses(graph: nx.DiGraph) -> list[dict]:
    rankings = []
    for course_id in graph.nodes:
        unlocked = sorted(nx.descendants(graph, course_id))
        if not unlocked:
            continue
        rankings.append(
            {
                "course_id": course_id,
                "unlock_count": len(unlocked),
                "unlocks": unlocked[:8],
            }
        )
    rankings.sort(key=lambda item: (-item["unlock_count"], item["course_id"]))
    return rankings


def detect_prerequisite_cycles(graph: nx.DiGraph) -> list[list[str]]:
    try:
        cycles = list(nx.simple_cycles(graph))
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
        requirement_groups = summarize_requirement_groups(course["prerequisites"], completed_courses) if course else []
        edge_group_indexes = sorted(
            {
                entry["group_path"][0]
                for entry in edge_data.get("entries", [])
                if entry.get("group_path")
            }
        )
        related_groups = [group for group in requirement_groups if group["group_index"] in edge_group_indexes]
        is_any_of = any(group["type"] == "any_of" for group in related_groups)
        alternative_hidden = False
        satisfied_by = []
        if is_any_of:
            satisfied_by = sorted({course_id for group in related_groups for course_id in group.get("satisfied_by", [])})
            alternative_hidden = bool(satisfied_by) and src not in satisfied_by
        edges.append(
            {
                "data": {
                    "id": f"{src}->{dest}",
                    "source": src,
                    "target": dest,
                    "labels": edge_data.get("labels", []),
                    "label": " / ".join(edge_data.get("labels", [])),
                    "verified": bool(course and course.get("verified")),
                    "isAnyOf": is_any_of,
                    "isAllOf": any(group["type"] == "all_of" for group in related_groups),
                    "alternativeSatisfiedBy": satisfied_by,
                    "hideWhenAlternativeSatisfied": alternative_hidden,
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
            "gateway_courses": rank_gateway_courses(graph),
            "cycles": detect_prerequisite_cycles(graph),
            "next_options": find_next_options(data, completed_courses),
            "course_insights": course_insights,
            "target_analysis": target_analysis,
            "legend": STATUS_COLORS,
        },
    }
