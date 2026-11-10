(() => {
  let catalog = null;
  let initialized = false;
  let generation = 0;
  let lastPlan = null;
  let lastInputs = null;

  const byId = (id) => document.getElementById(id);
  const selected = (id) => [...byId(id).querySelectorAll("input:checked")].map((input) => input.value);
  const element = (tag, text, className) => {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (className) node.className = className;
    return node;
  };

  document.addEventListener("DOMContentLoaded", () => {
    const now = new Date();
    byId("schedule-year").value = now.getFullYear() + (now.getMonth() >= 8 ? 1 : 0);
    byId("schedule-season").value = now.getMonth() >= 8 ? "Winter" : "Fall";
    byId("schedule-form").addEventListener("submit", generate);
    byId("schedule-form").addEventListener("change", () => {
      updateCounts();
      invalidate("Settings changed. Generate a new plan.");
    });
    byId("download-schedule-btn").addEventListener("click", download);
  });

  document.addEventListener("planner:state", (event) => {
    const data = event.detail;
    const targetIds = initialized ? selected("schedule-targets") : data.courses
      .filter((course) => course.categories.includes("target course")).map((course) => course.id);
    const excludedIds = initialized ? selected("schedule-excluded") : [];
    const changed = catalog && JSON.stringify(catalog) !== JSON.stringify(data);
    catalog = data;
    renderChecklist("schedule-targets", targetIds);
    renderChecklist("schedule-excluded", excludedIds);
    initialized = true;
    byId("generate-schedule-btn").disabled = false;
    const completed = catalog.courses.filter((course) => course.status === "completed").map((course) => course.id);
    byId("schedule-completed").textContent = `Prior credit (${completed.length}): ${completed.join(", ") || "None marked completed"}`;
    updateCounts();
    if (changed) invalidate("Catalog changed. Generate a new plan to use the updated data.");
    else if (!lastPlan) byId("schedule-status").textContent = "Plans do not change your saved courses or statuses. Offerings left blank are assumed available every enabled term.";
  });

  function renderChecklist(id, checked) {
    const container = byId(id);
    container.replaceChildren();
    catalog.courses.forEach((course) => {
      const label = element("label", undefined, "checkbox-inline");
      const input = document.createElement("input");
      input.type = "checkbox";
      input.value = course.id;
      input.checked = checked.includes(course.id);
      label.append(input, element("span", `${course.id} - ${course.title}`));
      container.append(label);
    });
  }

  function updateCounts() {
    byId("schedule-target-count").textContent = `(${selected("schedule-targets").length})`;
    byId("schedule-excluded-count").textContent = `(${selected("schedule-excluded").length})`;
    const summer = byId("schedule-summer").checked;
    [...byId("schedule-season").options].forEach((option) => {
      option.disabled = !summer && ["Spring", "Summer"].includes(option.value);
    });
    if (!summer && ["Spring", "Summer"].includes(byId("schedule-season").value)) {
      byId("schedule-season").value = "Fall";
    }
  }

  function invalidate(message) {
    generation += 1;
    lastPlan = null;
    byId("download-schedule-btn").disabled = true;
    byId("schedule-results").replaceChildren();
    byId("schedule-status").textContent = message;
  }

  function inputs() {
    return {
      target_course_ids: selected("schedule-targets"),
      excluded_course_ids: selected("schedule-excluded"),
      max_credits: Number(byId("schedule-credits").value),
      max_difficult: Number(byId("schedule-difficult").value),
      horizon: Number(byId("schedule-horizon").value),
      start_season: byId("schedule-season").value,
      start_year: Number(byId("schedule-year").value),
      include_summer: byId("schedule-summer").checked,
      objective: byId("schedule-objective").value,
      strategy: byId("schedule-strategy").value,
      time_limit: 5,
    };
  }

  async function generate(event) {
    event.preventDefault();
    if (!catalog) return;
    invalidate("Finding prerequisite choices and semester assignments...");
    const ticket = generation;
    const options = inputs();
    byId("generate-schedule-btn").disabled = true;
    byId("schedule-results").setAttribute("aria-busy", "true");
    try {
      const response = await fetch("/api/schedule", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(options),
      });
      const payload = await response.json();
      if (ticket !== generation) return;
      if (!response.ok || !payload.ok) throw new Error((payload.errors || ["Scheduling failed."]).join(" "));
      lastPlan = payload;
      lastInputs = options;
      payload.results.forEach(renderResult);
      const hasPlan = payload.results.some((result) => ["optimal", "feasible"].includes(result.status));
      byId("download-schedule-btn").disabled = !hasPlan;
      byId("schedule-status").textContent = hasPlan
        ? "Plan generated against the saved catalog. Check assumptions below before using it."
        : "No complete plan was returned. Review the solver's explanation below.";
    } catch (error) {
      if (ticket === generation) byId("schedule-status").textContent = error.message;
    } finally {
      byId("generate-schedule-btn").disabled = !catalog;
      byId("schedule-results").removeAttribute("aria-busy");
    }
  }

  function renderResult(result) {
    const section = element("section", undefined, "schedule-result");
    const name = result.strategy === "constraint" ? "Constraint optimizer" : "Greedy heuristic";
    const labels = { optimal: "Proven optimal for this model", feasible: "Feasible, not proven optimal",
      infeasible: "Infeasible under these constraints", unknown: "Search limit reached", no_plan: "Heuristic found no plan" };
    const heading = element("div", undefined, "section-heading");
    heading.append(element("h3", name), element("span", labels[result.status] || result.status, "schedule-badge"));
    section.append(heading);
    if (!["optimal", "feasible"].includes(result.status)) {
      section.append(element("p", result.message, "error-box"));
      byId("schedule-results").append(section);
      return;
    }
    section.append(element("p", `${result.course_count} courses / ${result.total_credits} credits / ${result.semester_count} planning terms / ${result.elapsed_ms} ms`, "schedule-metrics"));
    const lists = element("div", undefined, "schedule-course-lists");
    for (const [title, ids] of [["Additional prerequisites", result.prerequisite_course_ids], ["Your targets", result.target_course_ids]]) {
      const column = element("div");
      column.append(element("h4", title));
      const list = element("ul");
      if (!ids.length) list.append(element("li", "None"));
      ids.forEach((id) => list.append(element("li", id + (result.completed_target_course_ids.includes(id) ? " (already completed)" : ""))));
      column.append(list);
      lists.append(column);
    }
    section.append(lists);
    const timeline = element("div", undefined, "schedule-timeline");
    result.terms.forEach((term) => {
      const card = element("article", undefined, "semester-card");
      card.append(element("p", `TERM ${term.index + 1}`, "eyebrow"), element("h4", term.label),
        element("p", `${term.credits} credits`, "semester-credits"));
      if (!term.courses.length) card.append(element("p", "Waiting for an available offering.", "helper-text"));
      term.courses.forEach((course) => {
        const row = element("div", undefined, "semester-course");
        const button = element("button", course.id, "schedule-course-link");
        button.type = "button";
        button.addEventListener("click", () => document.dispatchEvent(new CustomEvent("planner:focus", { detail: course.id })));
        row.append(button, element("span", course.is_target ? "Target" : "Prerequisite", "section-kicker"),
          element("p", course.title), element("small", `${course.credits} cr / difficulty ${course.difficulty}`),
          element("small", course.satisfied_by.length ? `After: ${course.satisfied_by.join(", ")}` : "No listed prerequisites"));
        card.append(row);
      });
      timeline.append(card);
    });
    section.append(timeline);
    const assumptions = element("details", undefined, "schedule-assumptions");
    assumptions.append(element("summary", "Assumptions and limitations"));
    const warnings = element("ul");
    result.warnings.forEach((warning) => warnings.append(element("li", warning)));
    assumptions.append(warnings);
    section.append(assumptions);
    byId("schedule-results").append(section);
  }

  function download() {
    if (!lastPlan) return;
    const blob = new Blob([JSON.stringify({ request: lastInputs, ...lastPlan }, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "semester-plan.json";
    anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
})();
