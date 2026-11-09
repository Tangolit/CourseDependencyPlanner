cytoscape.use(cytoscapeDagre);

const STATUSES = ["completed", "current", "planned", "interested", "not_started"];
const STATUS_LABELS = {
  completed: "Completed",
  current: "Current",
  planned: "Planned",
  interested: "Interested",
  not_started: "Not started",
};

const appState = {
  data: null,
  graph: null,
  cy: null,
  selectedCourseId: null,
  layoutMode: "tree",
  filters: {
    statuses: new Set(STATUSES),
    interest: "all",
    tag: "all",
    verified: "all",
    pathOnly: false,
  },
  searchQuery: "",
  addLinkMode: false,
  addLinkSource: null,
  lastTap: { id: null, at: 0 },
};

document.addEventListener("DOMContentLoaded", () => {
  bindPersistentControls();
  loadState();
});

async function loadState() {
  setSaveIndicator("saving", "Loading planner...");
  try {
    const response = await fetch("/api/state");
    const payload = await response.json();
    applyState(payload);
    setSaveIndicator("saved", "Loaded");
  } catch (error) {
    setSaveIndicator("error", "Load failed");
    showToast(`Could not load planner data: ${error.message}`);
  }
}

function bindPersistentControls() {
  document.getElementById("add-course-btn").addEventListener("click", () => openCourseModal());
  document.getElementById("undo-btn").addEventListener("click", undoLastChange);
  document.getElementById("import-btn").addEventListener("click", () => document.getElementById("import-file-input").click());
  document.getElementById("export-btn").addEventListener("click", () => window.open("/api/export", "_blank"));
  document.getElementById("export-png-btn").addEventListener("click", exportGraphPng);
  document.getElementById("export-svg-btn").addEventListener("click", exportGraphSvg);
  document.getElementById("tree-layout-btn").addEventListener("click", () => {
    appState.layoutMode = "tree";
    runLayout(true, "tree");
  });
  document.getElementById("target-layout-btn").addEventListener("click", () => {
    appState.layoutMode = "target";
    runLayout(true, "target");
  });
  document.getElementById("fit-graph-btn").addEventListener("click", () => appState.cy?.fit(undefined, 50));
  document.getElementById("reset-layout-btn").addEventListener("click", () => {
    appState.layoutMode = "tree";
    runLayout(true, "tree");
  });
  document.getElementById("clear-selection-btn").addEventListener("click", () => {
    appState.selectedCourseId = null;
    renderDetailPanel();
    refreshGraphDecorations();
  });
  document.getElementById("search-input").addEventListener("input", (event) => {
    appState.searchQuery = event.target.value.trim();
    renderSearchResults();
    refreshGraphDecorations();
  });
  document.getElementById("interest-filter").addEventListener("change", (event) => {
    appState.filters.interest = event.target.value;
    refreshGraphDecorations();
  });
  document.getElementById("tag-filter").addEventListener("change", (event) => {
    appState.filters.tag = event.target.value;
    refreshGraphDecorations();
  });
  document.getElementById("verified-filter").addEventListener("change", (event) => {
    appState.filters.verified = event.target.value;
    refreshGraphDecorations();
  });
  document.getElementById("path-only-filter").addEventListener("change", (event) => {
    appState.filters.pathOnly = event.target.checked;
    refreshGraphDecorations();
    appState.layoutMode = event.target.checked ? "target" : "tree";
    runLayout(true, appState.layoutMode);
  });
  document.getElementById("add-link-btn").addEventListener("click", toggleAddLinkMode);
  document.getElementById("add-tag-btn").addEventListener("click", () => openTagModal("create"));
  document.getElementById("import-file-input").addEventListener("change", handleImportFile);
}

function applyState(payload, options = {}) {
  appState.data = payload.data;
  appState.graph = payload.graph;
  if (Object.prototype.hasOwnProperty.call(options, "selectedCourseId")) {
    appState.selectedCourseId = options.selectedCourseId;
  } else if (appState.selectedCourseId && !getCourse(appState.selectedCourseId)) {
    appState.selectedCourseId = null;
  }
  renderStaticSections();
  renderSearchResults();
  renderGatewayList();
  renderNextOptions();
  renderDetailPanel();
  renderGraph();
}

function renderStaticSections() {
  document.getElementById("disclaimer-banner").textContent = appState.data.meta.disclaimer;
  const targetId = appState.data.meta.target_course_id || "None selected";
  document.getElementById("target-course-pill").textContent = targetId;
  renderStatusFilters();
  renderTagFilter();
  renderTagManager();
  renderLegend();
}

function renderStatusFilters() {
  const container = document.getElementById("status-filters");
  container.innerHTML = "";
  STATUSES.forEach((status) => {
    const checked = appState.filters.statuses.has(status) ? "checked" : "";
    const wrapper = document.createElement("label");
    wrapper.className = "checkbox-inline";
    wrapper.innerHTML = `
      <input type="checkbox" value="${status}" ${checked}>
      <span>${STATUS_LABELS[status]}</span>
    `;
    wrapper.querySelector("input").addEventListener("change", (event) => {
      if (event.target.checked) {
        appState.filters.statuses.add(status);
      } else {
        appState.filters.statuses.delete(status);
      }
      refreshGraphDecorations();
    });
    container.appendChild(wrapper);
  });
}

function renderTagFilter() {
  const select = document.getElementById("tag-filter");
  const current = appState.filters.tag;
  const options = ['<option value="all">All tags</option>'].concat(
    appState.data.tag_catalog.map((tag) => `<option value="${escapeHtml(tag)}">${escapeHtml(tag)}</option>`)
  );
  select.innerHTML = options.join("");
  select.value = appState.data.tag_catalog.includes(current) ? current : "all";
  appState.filters.tag = select.value;
}

function renderLegend() {
  const container = document.getElementById("legend-inline");
  container.innerHTML = "";
  Object.entries(appState.graph.legend).forEach(([status, color]) => {
    const chip = document.createElement("div");
    chip.className = "legend-chip";
    chip.innerHTML = `<span class="legend-dot" style="background:${color}"></span>${escapeHtml(STATUS_LABELS[status] || status)}`;
    container.appendChild(chip);
  });
}

function renderTagManager() {
  const container = document.getElementById("tag-manager-list");
  container.innerHTML = "";
  appState.data.tag_catalog.forEach((tag) => {
    const row = document.createElement("div");
    row.className = "tag-row";
    row.innerHTML = `
      <div>
        <div class="item-title">${escapeHtml(tag)}</div>
        <div class="item-subtitle">Available for course labels and filtering</div>
      </div>
      <div class="inline-actions">
        <button class="secondary-btn small-btn" data-action="rename">Rename</button>
        <button class="danger-btn small-btn" data-action="delete">Delete</button>
      </div>
    `;
    row.querySelector('[data-action="rename"]').addEventListener("click", () => openTagModal("rename", tag));
    row.querySelector('[data-action="delete"]').addEventListener("click", () => openTagModal("delete", tag));
    container.appendChild(row);
  });
}

function renderSearchResults() {
  const container = document.getElementById("search-results");
  const query = appState.searchQuery.toLowerCase();
  const matches = getCourses()
    .filter((course) => {
      if (!query) {
        return true;
      }
      const haystack = `${course.id} ${course.title}`.toLowerCase();
      return haystack.includes(query);
    })
    .slice(0, query ? 10 : 6);
  container.innerHTML = "";
  if (!matches.length) {
    container.innerHTML = '<div class="empty-list">No matching courses.</div>';
    return;
  }
  matches.forEach((course) => {
    const card = document.createElement("div");
    card.className = "search-result";
    card.innerHTML = `
      <div>
        <div class="item-title">${escapeHtml(course.id)}</div>
        <div class="item-subtitle">${escapeHtml(course.title)}</div>
      </div>
      <button class="secondary-btn small-btn">Locate</button>
    `;
    card.querySelector("button").addEventListener("click", () => focusCourse(course.id));
    container.appendChild(card);
  });
}

function renderGatewayList() {
  const container = document.getElementById("gateway-list");
  const items = appState.graph.gateway_courses.slice(0, 8);
  container.innerHTML = "";
  if (!items.length) {
    container.innerHTML = '<div class="empty-list">No gateway rankings available yet.</div>';
    return;
  }
  items.forEach((item) => {
    const card = document.createElement("div");
    card.className = "mini-card";
    card.innerHTML = `
      <div>
        <div class="item-title">${escapeHtml(item.course_id)}</div>
        <div class="item-subtitle">Unlocks ${item.unlock_count} downstream courses</div>
      </div>
      <button class="secondary-btn small-btn">View</button>
    `;
    card.querySelector("button").addEventListener("click", () => focusCourse(item.course_id));
    container.appendChild(card);
  });
}

function renderNextOptions() {
  const container = document.getElementById("next-options-list");
  const items = appState.graph.next_options.slice(0, 10);
  container.innerHTML = "";
  if (!items.length) {
    container.innerHTML = '<div class="empty-list">No courses are fully unlocked by the current completed set.</div>';
    return;
  }
  items.forEach((item) => {
    const card = document.createElement("div");
    card.className = "mini-card";
    card.innerHTML = `
      <div>
        <div class="item-title">${escapeHtml(item.course_id)}</div>
        <div class="item-subtitle">${escapeHtml(item.title)}</div>
      </div>
      <button class="secondary-btn small-btn">Inspect</button>
    `;
    card.querySelector("button").addEventListener("click", () => focusCourse(item.course_id));
    container.appendChild(card);
  });
}

function renderDetailPanel() {
  const panel = document.getElementById("course-detail-panel");
  const course = getCourse(appState.selectedCourseId);
  if (!course) {
    if (appState.selectedCourseId) {
      panel.className = "detail-panel";
      panel.innerHTML = `
        <div class="detail-header">
          <h3>${escapeHtml(appState.selectedCourseId)}</h3>
          <div class="detail-subtitle">This course is referenced in prerequisites but does not exist as a full course record yet.</div>
        </div>
        <div class="detail-section">
          <div class="warning-box">Add the missing course to resolve the reference warning and make it editable.</div>
        </div>
        <div class="detail-actions">
          <button class="primary-btn" id="create-missing-course-btn">Create Course Record</button>
        </div>
      `;
      panel.querySelector("#create-missing-course-btn").addEventListener("click", () => {
        openCourseModalFromPlaceholder(appState.selectedCourseId);
      });
      return;
    }
    panel.className = "detail-panel empty-state";
    panel.textContent = "Select a course node to inspect details, edit status, manage tags, and work with prerequisites.";
    return;
  }

  const insights = appState.graph.course_insights[course.id];
  const targetAnalysis = appState.graph.target_analysis;
  const statusColor = appState.graph.legend[course.status];
  panel.className = "detail-panel";
  panel.innerHTML = `
    <div class="detail-header">
      <div class="pill-status" style="background:${statusColor}">${escapeHtml(STATUS_LABELS[course.status])}</div>
      <h3>${escapeHtml(course.id)}</h3>
      <div class="detail-subtitle">${escapeHtml(course.title)}</div>
    </div>

    <div class="detail-grid">
      <div class="detail-metric">
        <span class="detail-metric-label">Credits</span>
        <strong>${escapeHtml(String(course.credits))}</strong>
      </div>
      <div class="detail-metric">
        <span class="detail-metric-label">Interest</span>
        <strong>${escapeHtml(capitalize(course.interest))}</strong>
      </div>
      <div class="detail-metric">
        <span class="detail-metric-label">Semester</span>
        <strong>${escapeHtml(course.semester_offered.join(", ") || "Not set")}</strong>
      </div>
      <div class="detail-metric">
        <span class="detail-metric-label">Verified</span>
        <strong>${course.verified ? "Yes" : "No"}</strong>
      </div>
    </div>

    <div class="detail-section">
      <h4>Status</h4>
      <div class="status-select-row">
        <select id="detail-status-select" class="text-input">
          ${STATUSES.map((status) => `<option value="${status}" ${status === course.status ? "selected" : ""}>${escapeHtml(STATUS_LABELS[status])}</option>`).join("")}
        </select>
        <label class="checkbox-inline">
          <input id="detail-verified-toggle" type="checkbox" ${course.verified ? "checked" : ""}>
          <span>Verified</span>
        </label>
      </div>
    </div>

    <div class="detail-section">
      <h4>Categories / Tags</h4>
      <div class="chip-list">
        ${course.categories.length ? course.categories.map((tag) => `<span class="chip">${escapeHtml(tag)} <button type="button" data-remove-tag="${escapeHtml(tag)}">×</button></span>`).join("") : '<span class="muted-text">No tags yet.</span>'}
      </div>
      <div class="tag-edit-row" style="margin-top:12px;">
        <select id="detail-add-existing-tag" class="text-input">
          <option value="">Add existing tag</option>
          ${appState.data.tag_catalog.filter((tag) => !course.categories.includes(tag)).map((tag) => `<option value="${escapeHtml(tag)}">${escapeHtml(tag)}</option>`).join("")}
        </select>
        <button class="secondary-btn small-btn" id="detail-add-existing-tag-btn">Add</button>
      </div>
      <div class="tag-edit-row" style="margin-top:10px;">
        <input id="detail-new-tag-input" class="text-input" type="text" placeholder="Create custom tag">
        <button class="secondary-btn small-btn" id="detail-create-tag-btn">Create Tag</button>
      </div>
    </div>

    <div class="detail-section">
      <h4>Notes</h4>
      <textarea id="detail-notes-input" class="textarea-input" placeholder="Add planning notes here">${escapeHtml(course.notes)}</textarea>
      <div class="inline-actions" style="margin-top:10px;">
        <button class="secondary-btn small-btn" id="save-notes-btn">Save Notes</button>
      </div>
    </div>

    <div class="detail-section">
      <h4>Source</h4>
      <div class="list-block">
        <div class="list-pill"><strong>URL:</strong> ${course.source_url ? `<a href="${escapeAttribute(course.source_url)}" target="_blank" rel="noreferrer">${escapeHtml(course.source_url)}</a>` : '<span class="muted-text">Not set</span>'}</div>
      </div>
    </div>

    <div class="detail-section">
      <h4>Description</h4>
      <div class="list-pill">${course.description ? escapeHtml(course.description) : '<span class="muted-text">No description saved.</span>'}</div>
    </div>

    <div class="detail-section">
      <h4>Prerequisite Groups</h4>
      <div class="list-block">
        ${renderRequirementGroups(insights.requirement_groups)}
      </div>
    </div>

    <div class="detail-section">
      <h4>Official prerequisite wording</h4>
      <div class="list-pill">${course.prerequisite_text ? escapeHtml(course.prerequisite_text) : '<span class="muted-text">No exact prerequisite text saved.</span>'}</div>
    </div>

    <div class="detail-section">
      <h4>Direct prerequisites</h4>
      <div class="list-block">${renderIdList(insights.direct_prerequisites)}</div>
    </div>

    <div class="detail-section">
      <h4>Directly unlocked courses</h4>
      <div class="list-block">${renderIdList(insights.directly_unlocked_courses)}</div>
    </div>

    <div class="detail-section">
      <h4>All downstream courses</h4>
      <div class="list-block">${renderIdList(insights.all_unlocked_courses)}</div>
    </div>

    <div class="detail-section">
      <h4>Path to target</h4>
      <div class="path-summary">
        ${renderTargetSummary(course.id, targetAnalysis)}
      </div>
    </div>

    <div class="detail-actions">
      <button class="primary-btn" id="set-target-btn">Set as Target Course</button>
      <button class="secondary-btn" id="edit-course-btn">Edit Course</button>
      <button class="secondary-btn" id="edit-prereq-btn">Add Prerequisite</button>
      <button class="danger-btn" id="delete-course-btn">Delete Course</button>
    </div>
  `;

  panel.querySelector("#detail-status-select").addEventListener("change", (event) => quickUpdateCourse(course.id, (draft) => {
    draft.status = event.target.value;
  }));
  panel.querySelector("#detail-verified-toggle").addEventListener("change", (event) => quickUpdateCourse(course.id, (draft) => {
    draft.verified = event.target.checked;
  }));
  panel.querySelector("#save-notes-btn").addEventListener("click", () => quickUpdateCourse(course.id, (draft) => {
    draft.notes = document.getElementById("detail-notes-input").value.trim();
  }, { message: "Notes saved." }));
  panel.querySelector("#detail-add-existing-tag-btn").addEventListener("click", () => {
    const select = document.getElementById("detail-add-existing-tag");
    if (!select.value) {
      showToast("Choose an existing tag first.");
      return;
    }
    quickUpdateCourse(course.id, (draft, data) => {
      if (!draft.categories.includes(select.value)) {
        draft.categories.push(select.value);
      }
      if (!data.tag_catalog.includes(select.value)) {
        data.tag_catalog.push(select.value);
      }
    }, { message: `Added tag to ${course.id}.` });
  });
  panel.querySelector("#detail-create-tag-btn").addEventListener("click", () => {
    const input = document.getElementById("detail-new-tag-input");
    const value = input.value.trim();
    if (!value) {
      showToast("Enter a new tag name first.");
      return;
    }
    quickUpdateCourse(course.id, (draft, data) => {
      if (!data.tag_catalog.includes(value)) {
        data.tag_catalog.push(value);
      }
      if (!draft.categories.includes(value)) {
        draft.categories.push(value);
      }
    }, { message: `Created tag ${value}.` });
  });
  panel.querySelectorAll("[data-remove-tag]").forEach((button) => {
    button.addEventListener("click", () => {
      const tag = button.getAttribute("data-remove-tag");
      quickUpdateCourse(course.id, (draft) => {
        draft.categories = draft.categories.filter((item) => item !== tag);
      }, { message: `Removed ${tag}.` });
    });
  });
  panel.querySelector("#set-target-btn").addEventListener("click", () => setTargetCourse(course.id));
  panel.querySelector("#edit-course-btn").addEventListener("click", () => openCourseModal(course.id));
  panel.querySelector("#edit-prereq-btn").addEventListener("click", () => openPrerequisiteModal(course.id));
  panel.querySelector("#delete-course-btn").addEventListener("click", () => confirmDeleteCourse(course.id));
  panel.querySelectorAll("[data-focus-id]").forEach((button) => {
    button.addEventListener("click", () => focusCourse(button.getAttribute("data-focus-id")));
  });
}

function renderRequirementGroups(groups) {
  if (!groups.length) {
    return '<div class="list-pill muted-text">No prerequisites listed.</div>';
  }
  return groups
    .map(
      (group) => `
        <div class="list-pill">
          <strong>${escapeHtml(group.label)}</strong><br>
          <span>${escapeHtml(group.course_ids.join(", "))}</span><br>
          <span class="muted-text">${group.satisfied ? `Satisfied by: ${escapeHtml((group.satisfied_by || []).join(", ") || "completed coursework")}` : `Missing: ${escapeHtml(group.missing.join(", "))}`}</span>
        </div>
      `
    )
    .join("");
}

function renderIdList(ids) {
  if (!ids.length) {
    return '<div class="list-pill muted-text">None</div>';
  }
  return ids
    .map((courseId) => `<button class="list-pill mono" data-focus-id="${escapeHtml(courseId)}">${escapeHtml(courseId)}</button>`)
    .join("");
}

function renderTargetSummary(courseId, targetAnalysis) {
  if (!targetAnalysis) {
    return '<div class="list-pill muted-text">Set a target course to highlight relevant prerequisite paths.</div>';
  }
  if (courseId === targetAnalysis.target_course_id) {
    return `
      <div class="list-pill">Current target course. ${targetAnalysis.missing_prerequisites.missing_course_ids.length ? `Missing: ${escapeHtml(targetAnalysis.missing_prerequisites.missing_course_ids.join(", "))}` : "All listed prerequisite groups are satisfied by completed courses."}</div>
      ${targetAnalysis.paths.map((item) => `<div class="list-pill mono">${escapeHtml(item.path.join(" → "))}</div>`).join("") || '<div class="list-pill muted-text">No prerequisite path found yet.</div>'}
    `;
  }
  if (targetAnalysis.relevant_course_ids.includes(courseId)) {
    return '<div class="list-pill">This course is on the currently selected target path.</div>';
  }
  return '<div class="list-pill muted-text">This course is not part of the active target prerequisite subgraph.</div>';
}

function renderGraph() {
  const container = document.getElementById("graph");
  if (appState.cy) {
    appState.cy.destroy();
  }
  const graphElements = buildGraphElements();
  appState.cy = cytoscape({
    container,
    elements: graphElements,
    layout: { name: "preset" },
    style: [
      {
        selector: "node",
        style: {
          label: "data(label)",
          "font-size": 13,
          "font-weight": 800,
          color: "#10213d",
          "text-wrap": "wrap",
          "text-max-width": 110,
          "background-color": "data(color)",
          width: "data(size)",
          height: "data(size)",
          "border-width": "data(borderWidth)",
          "border-color": "#ffffff",
          "text-valign": "center",
          "text-halign": "center",
          "overlay-padding": 6,
          "overlay-opacity": 0,
        },
      },
      {
        selector: 'node[?isPlaceholder]',
        style: {
          "border-style": "dashed",
          "background-color": "#c9d1db",
          color: "#4e5968",
        },
      },
      {
        selector: "edge",
        style: {
          width: 2.6,
          "curve-style": "bezier",
          "line-color": "#8a95a7",
          "target-arrow-color": "#8a95a7",
          "target-arrow-shape": "triangle",
          "arrow-scale": 1.15,
          label: "data(displayLabel)",
          "font-size": 10,
          color: "#4d5b70",
          "text-rotation": "autorotate",
          "text-background-color": "#fffdf8",
          "text-background-opacity": 0.92,
          "text-background-padding": 3,
        },
      },
      {
        selector: ".required-edge",
        style: {
          width: 3.2,
          "line-color": "#50617a",
          "target-arrow-color": "#50617a",
        },
      },
      {
        selector: ".selected",
        style: {
          "border-color": "#00274c",
          "border-width": 6,
          "shadow-blur": 22,
          "shadow-color": "#ffcb05",
          "shadow-opacity": 0.6,
        },
      },
      {
        selector: ".hidden",
        style: {
          display: "none",
        },
      },
      {
        selector: ".dimmed",
        style: {
          opacity: 0.16,
        },
      },
      {
        selector: ".target-relevant",
        style: {
          "border-color": "#ffcb05",
        },
      },
      {
        selector: ".target-missing",
        style: {
          "background-color": "#f08a89",
          "line-color": "#f08a89",
          "target-arrow-color": "#f08a89",
        },
      },
      {
        selector: ".alternative-edge",
        style: {
          "line-style": "dashed",
          width: 2.4,
          "line-color": "#9d7ccc",
          "target-arrow-color": "#9d7ccc",
        },
      },
      {
        selector: ".satisfied-alternative-edge",
        style: {
          width: 3.2,
          "line-color": "#2d9d5b",
          "target-arrow-color": "#2d9d5b",
        },
      },
      {
        selector: ".target-completed",
        style: {
          "border-color": "#2d9d5b",
        },
      },
      {
        selector: ".target-unfinished",
        style: {
          "border-style": "double",
        },
      },
      {
        selector: ".search-hit",
        style: {
          "shadow-color": "#00274c",
          "shadow-opacity": 0.28,
          "shadow-blur": 12,
        },
      },
      {
        selector: ".link-source",
        style: {
          "border-color": "#ffcb05",
          "border-width": 7,
        },
      },
    ],
  });

  appState.cy.on("tap", "node", (event) => {
    const nodeId = event.target.id();
    if (appState.addLinkMode) {
      handleAddLinkTap(nodeId);
      return;
    }
    const now = Date.now();
    if (appState.lastTap.id === nodeId && now - appState.lastTap.at < 320 && !event.target.data("isPlaceholder")) {
      openCourseModal(nodeId);
      appState.lastTap = { id: null, at: 0 };
      return;
    }
    appState.lastTap = { id: nodeId, at: now };
    appState.selectedCourseId = nodeId;
    renderDetailPanel();
    refreshGraphDecorations();
  });

  appState.cy.on("tap", "edge", (event) => openEdgeModal(event.target.data()));
  appState.cy.on("tap", (event) => {
    if (event.target === appState.cy && !appState.addLinkMode) {
      appState.selectedCourseId = null;
      renderDetailPanel();
      refreshGraphDecorations();
    }
  });

  appState.cy.ready(() => {
    refreshGraphDecorations();
    runLayout(false, appState.layoutMode);
    appState.cy.fit(undefined, 50);
  });
}

function buildGraphElements() {
  const nodes = appState.graph.nodes.map((node) => structuredClone(node));
  const edges = appState.graph.edges.map((edge) => {
    const copy = structuredClone(edge);
    copy.data.displayLabel = copy.data.isAnyOf ? "One-of option" : "";
    if (copy.data.isAnyOf) {
      copy.classes = [copy.classes, "alternative-edge"].filter(Boolean).join(" ");
    } else {
      copy.classes = [copy.classes, "required-edge"].filter(Boolean).join(" ");
    }
    return copy;
  });
  return [...nodes, ...edges];
}

function refreshGraphDecorations() {
  if (!appState.cy) {
    return;
  }
  const targetAnalysis = appState.graph.target_analysis;
  const relevant = new Set(targetAnalysis?.relevant_course_ids || []);
  const missing = new Set(targetAnalysis?.missing_prerequisites?.missing_course_ids || []);
  const completedRelevant = new Set(targetAnalysis?.completed_relevant_course_ids || []);
  const unfinishedRelevant = new Set(targetAnalysis?.unfinished_relevant_course_ids || []);
  const query = appState.searchQuery.toLowerCase();

  appState.cy.nodes().forEach((node) => {
    const course = getCourse(node.id());
    const isPlaceholder = node.data("isPlaceholder");
    const matchesStatus = !course || appState.filters.statuses.has(course.status);
    const matchesInterest = !course || appState.filters.interest === "all" || course.interest === appState.filters.interest;
    const matchesTag = !course || appState.filters.tag === "all" || course.categories.includes(appState.filters.tag);
    const matchesVerified =
      !course ||
      appState.filters.verified === "all" ||
      (appState.filters.verified === "verified" && course.verified) ||
      (appState.filters.verified === "unverified" && !course.verified);
    const passesBaseFilters = matchesStatus && matchesInterest && matchesTag && matchesVerified;
    const matchesSearch = !query || `${node.id()} ${(course?.title || "")}`.toLowerCase().includes(query);
    const shouldDimForPath = appState.filters.pathOnly && targetAnalysis && !relevant.has(node.id());

    node.removeClass("hidden dimmed selected target-relevant target-missing target-completed target-unfinished search-hit link-source");
    if (!passesBaseFilters || (query && !matchesSearch && !appState.selectedCourseId)) {
      node.addClass("hidden");
      return;
    }
    if (shouldDimForPath) {
      node.addClass("dimmed");
    }
    if (relevant.has(node.id())) {
      node.addClass("target-relevant");
    }
    if (missing.has(node.id())) {
      node.addClass("target-missing");
    }
    if (completedRelevant.has(node.id())) {
      node.addClass("target-completed");
    }
    if (unfinishedRelevant.has(node.id())) {
      node.addClass("target-unfinished");
    }
    if (appState.selectedCourseId === node.id()) {
      node.addClass("selected");
    }
    if (query && matchesSearch) {
      node.addClass("search-hit");
    }
    if (appState.addLinkSource === node.id()) {
      node.addClass("link-source");
    }
    if (isPlaceholder && !passesBaseFilters) {
      node.addClass("hidden");
    }
  });

  appState.cy.edges().forEach((edge) => {
    edge.removeClass("hidden dimmed target-relevant target-missing satisfied-alternative-edge");
    const sourceHidden = edge.source().hasClass("hidden");
    const targetHidden = edge.target().hasClass("hidden");
    if (sourceHidden || targetHidden) {
      edge.addClass("hidden");
      return;
    }
    if (edge.data("isAnyOf") && edge.data("hideWhenAlternativeSatisfied")) {
      edge.addClass("hidden");
      return;
    }
    if (appState.filters.pathOnly && targetAnalysis && !(relevant.has(edge.source().id()) && relevant.has(edge.target().id()))) {
      edge.addClass("dimmed");
    }
    if (missing.has(edge.source().id())) {
      edge.addClass("target-missing");
    }
    if (edge.data("isAnyOf") && (edge.data("alternativeSatisfiedBy") || []).includes(edge.source().id())) {
      edge.addClass("satisfied-alternative-edge");
    }
  });

}

function focusCourse(courseId) {
  appState.selectedCourseId = courseId;
  renderDetailPanel();
  refreshGraphDecorations();
  const node = appState.cy?.getElementById(courseId);
  if (node?.length) {
    if (appState.layoutMode === "target") {
      runLayout(true, "target");
    }
    appState.cy.animate({ center: { eles: node }, zoom: 1.15 }, { duration: 350 });
  }
}

function runLayout(animate = true, mode = appState.layoutMode) {
  if (!appState.cy) {
    return;
  }
  const positions = computeTreePositions(mode);
  appState.cy.layout({
    name: "preset",
    positions: (node) => positions[node.id()] || node.position(),
    fit: false,
    animate,
    animationDuration: animate ? 500 : 0,
  }).run();
}

function computeTreePositions(mode = "tree") {
  const visibleNodes = appState.cy.nodes().filter((node) => !node.hasClass("hidden"));
  const allVisibleIds = new Set(visibleNodes.map((node) => node.id()));
  const includedIds = selectLayoutNodeIds(mode, allVisibleIds);
  const predecessorMap = new Map();
  const successorMap = new Map();
  const indegreeMap = new Map();

  includedIds.forEach((id) => {
    predecessorMap.set(id, []);
    successorMap.set(id, []);
    indegreeMap.set(id, 0);
  });

  appState.cy.edges().forEach((edge) => {
    const source = edge.source().id();
    const target = edge.target().id();
    if (!includedIds.has(source) || !includedIds.has(target)) {
      return;
    }
    predecessorMap.get(target).push(source);
    successorMap.get(source).push(target);
    indegreeMap.set(target, indegreeMap.get(target) + 1);
  });

  const queue = [...includedIds]
    .filter((id) => indegreeMap.get(id) === 0)
    .sort(compareLayoutNodes);
  const levels = new Map();
  const processed = new Set();

  queue.forEach((id) => levels.set(id, 0));

  while (queue.length) {
    const current = queue.shift();
    processed.add(current);
    const currentLevel = levels.get(current) || 0;
    const successors = [...successorMap.get(current)].sort(compareLayoutNodes);
    successors.forEach((next) => {
      levels.set(next, Math.max(levels.get(next) || 0, currentLevel + 1));
      indegreeMap.set(next, indegreeMap.get(next) - 1);
      if (indegreeMap.get(next) === 0) {
        queue.push(next);
        queue.sort(compareLayoutNodes);
      }
    });
  }

  [...includedIds].forEach((id) => {
    if (processed.has(id)) {
      return;
    }
    const parentLevels = (predecessorMap.get(id) || []).map((pred) => levels.get(pred) || 0);
    levels.set(id, parentLevels.length ? Math.max(...parentLevels) + 1 : 0);
  });

  const byLevel = new Map();
  [...includedIds].forEach((id) => {
    const level = levels.get(id) || 0;
    if (!byLevel.has(level)) {
      byLevel.set(level, []);
    }
    byLevel.get(level).push(id);
  });

  const positions = {};
  const levelGap = mode === "target" ? 300 : 260;
  const rowGap = mode === "target" ? 120 : 138;
  [...byLevel.keys()].sort((a, b) => a - b).forEach((level) => {
    const ids = byLevel.get(level).sort(compareLayoutNodes);
    const totalHeight = Math.max((ids.length - 1) * rowGap, 0);
    ids.forEach((id, index) => {
      positions[id] = {
        x: 120 + level * levelGap,
        y: 200 + index * rowGap - totalHeight / 2,
      };
    });
  });

  appState.cy.nodes().forEach((node) => {
    if (!positions[node.id()]) {
      positions[node.id()] = node.position();
    }
  });

  return positions;
}

function selectLayoutNodeIds(mode, visibleIds) {
  if (mode !== "target") {
    return visibleIds;
  }

  const targetIds = new Set(appState.graph.target_analysis?.relevant_course_ids || []);
  if (targetIds.size) {
    return new Set([...visibleIds].filter((id) => targetIds.has(id)));
  }

  if (appState.selectedCourseId) {
    const selectedInsight = appState.graph.course_insights[appState.selectedCourseId];
    const selectedSet = new Set([appState.selectedCourseId, ...(selectedInsight?.all_prerequisites || [])]);
    return new Set([...visibleIds].filter((id) => selectedSet.has(id)));
  }

  return visibleIds;
}

function compareLayoutNodes(leftId, rightId) {
  const left = appState.cy?.getElementById(leftId);
  const right = appState.cy?.getElementById(rightId);
  const leftTarget = Number(Boolean(left?.data("isTarget")));
  const rightTarget = Number(Boolean(right?.data("isTarget")));
  if (leftTarget !== rightTarget) {
    return rightTarget - leftTarget;
  }
  const leftUnlocked = Number(left?.data("unlockedCount") || 0);
  const rightUnlocked = Number(right?.data("unlockedCount") || 0);
  if (leftUnlocked !== rightUnlocked) {
    return rightUnlocked - leftUnlocked;
  }
  return leftId.localeCompare(rightId);
}

function toggleAddLinkMode() {
  appState.addLinkMode = !appState.addLinkMode;
  appState.addLinkSource = null;
  document.getElementById("add-link-btn").classList.toggle("is-active", appState.addLinkMode);
  refreshGraphDecorations();
  showToast(appState.addLinkMode ? "Select a prerequisite course first, then the dependent course." : "Add prerequisite link mode turned off.");
}

function handleAddLinkTap(nodeId) {
  if (!appState.addLinkSource) {
    appState.addLinkSource = nodeId;
    refreshGraphDecorations();
    showToast(`Selected ${nodeId} as the prerequisite. Now click the dependent course.`);
    return;
  }
  if (appState.addLinkSource === nodeId) {
    showToast("A course cannot depend on itself.");
    return;
  }
  const prereqId = appState.addLinkSource;
  const dependentId = nodeId;
  appState.addLinkSource = null;
  appState.addLinkMode = false;
  document.getElementById("add-link-btn").classList.remove("is-active");

  const data = cloneData();
  const course = data.courses.find((item) => item.id === dependentId);
  const groups = prerequisiteExpressionToEditorGroups(course.prerequisites);
  const alreadyPresent = groups.some((group) => group.courseIds.includes(prereqId));
  if (alreadyPresent) {
    showToast(`${prereqId} is already listed for ${dependentId}.`);
    refreshGraphDecorations();
    return;
  }
  groups.push({ type: "all_of", courseIds: [prereqId] });
  course.prerequisites = editorGroupsToExpression(groups);
  persistData(data, { message: `Added ${prereqId} → ${dependentId}.`, selectedCourseId: dependentId });
}

function openCourseModal(courseId = null) {
  const course = courseId ? structuredClone(getCourse(courseId)) : {
    id: "",
    title: "",
    description: "",
    credits: 3,
    status: "planned",
    interest: "medium",
    categories: [],
    semester_offered: [],
    source_url: "",
    verified: false,
    notes: "",
    prerequisite_text: "",
    prerequisites: { all_of: [] },
  };
  const isEdit = Boolean(courseId);
  showModal(`
    <div class="modal-card">
      <h3>${isEdit ? "Edit Course" : "Add Course"}</h3>
      <p class="helper-text">${isEdit ? "Update course metadata here. Use the prerequisite editor for requirement groups." : "Create a new course node and add details without touching JSON directly."}</p>
      <form id="course-modal-form">
        <div class="modal-grid">
          <div>
            <label class="field-label" for="course-id-input">Course ID</label>
            <input id="course-id-input" class="text-input" type="text" value="${escapeAttribute(course.id)}" placeholder="MATH 451" required>
          </div>
          <div>
            <label class="field-label" for="course-title-input">Course title</label>
            <input id="course-title-input" class="text-input" type="text" value="${escapeAttribute(course.title)}" required>
          </div>
          <div>
            <label class="field-label" for="course-credits-input">Credits</label>
            <input id="course-credits-input" class="text-input" type="number" min="0" step="1" value="${escapeAttribute(String(course.credits))}">
          </div>
          <div>
            <label class="field-label" for="course-status-input">Status</label>
            <select id="course-status-input" class="text-input">
              ${STATUSES.map((status) => `<option value="${status}" ${status === course.status ? "selected" : ""}>${escapeHtml(STATUS_LABELS[status])}</option>`).join("")}
            </select>
          </div>
          <div>
            <label class="field-label" for="course-interest-input">Interest level</label>
            <select id="course-interest-input" class="text-input">
              ${["high", "medium", "low"].map((interest) => `<option value="${interest}" ${interest === course.interest ? "selected" : ""}>${escapeHtml(capitalize(interest))}</option>`).join("")}
            </select>
          </div>
          <div>
            <label class="field-label" for="course-semesters-input">Semester offered</label>
            <input id="course-semesters-input" class="text-input" type="text" value="${escapeAttribute(course.semester_offered.join(", "))}" placeholder="Fall, Winter">
          </div>
          <div class="full-width">
            <label class="field-label" for="course-categories-input">Topic tags</label>
            <input id="course-categories-input" class="text-input" type="text" value="${escapeAttribute(course.categories.join(", "))}" placeholder="analysis, target course, proofs">
          </div>
          <div class="full-width">
            <label class="field-label" for="course-source-url-input">Official source URL</label>
            <input id="course-source-url-input" class="text-input" type="url" value="${escapeAttribute(course.source_url)}" placeholder="https://lsa.umich.edu/...">
          </div>
          <div class="full-width">
            <label class="checkbox-inline">
              <input id="course-verified-input" type="checkbox" ${course.verified ? "checked" : ""}>
              <span>Verified against an official source</span>
            </label>
          </div>
          <div class="full-width">
            <label class="field-label" for="course-description-input">Brief description</label>
            <textarea id="course-description-input" class="textarea-input">${escapeHtml(course.description || "")}</textarea>
          </div>
          <div class="full-width">
            <label class="field-label" for="course-prereq-text-input">Exact prerequisite text</label>
            <textarea id="course-prereq-text-input" class="textarea-input">${escapeHtml(course.prerequisite_text || "")}</textarea>
          </div>
          <div class="full-width">
            <label class="field-label" for="course-notes-input">Notes</label>
            <textarea id="course-notes-input" class="textarea-input">${escapeHtml(course.notes)}</textarea>
          </div>
        </div>
        <div id="course-modal-error"></div>
        <div class="modal-actions">
          <button type="button" class="ghost-btn" data-close-modal>Cancel</button>
          <button type="submit" class="primary-btn">${isEdit ? "Save Course" : "Create Course"}</button>
        </div>
      </form>
    </div>
  `);

  document.getElementById("course-modal-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const nextId = document.getElementById("course-id-input").value.trim();
    const title = document.getElementById("course-title-input").value.trim();
    const errorBox = document.getElementById("course-modal-error");
    if (!nextId || !title) {
      errorBox.innerHTML = '<div class="error-box">Course ID and title are required.</div>';
      return;
    }
    const duplicate = getCourses().some((item) => item.id === nextId && item.id !== courseId);
    if (duplicate) {
      errorBox.innerHTML = `<div class="error-box">Duplicate course ID detected: ${escapeHtml(nextId)}</div>`;
      return;
    }
    const data = cloneData();
    const parsedCourse = {
      ...course,
      id: nextId,
      title,
      description: document.getElementById("course-description-input").value.trim(),
      credits: Number(document.getElementById("course-credits-input").value) || 0,
      status: document.getElementById("course-status-input").value,
      interest: document.getElementById("course-interest-input").value,
      categories: parseCommaList(document.getElementById("course-categories-input").value),
      semester_offered: parseCommaList(document.getElementById("course-semesters-input").value),
      source_url: document.getElementById("course-source-url-input").value.trim(),
      verified: document.getElementById("course-verified-input").checked,
      prerequisite_text: document.getElementById("course-prereq-text-input").value.trim(),
      notes: document.getElementById("course-notes-input").value.trim(),
    };
    if (isEdit) {
      const index = data.courses.findIndex((item) => item.id === courseId);
      data.courses[index] = parsedCourse;
      if (data.meta.target_course_id === courseId) {
        data.meta.target_course_id = nextId;
      }
      renameCourseReferences(data, courseId, nextId);
    } else {
      data.courses.push(parsedCourse);
    }
    parsedCourse.categories.forEach((tag) => {
      if (!data.tag_catalog.includes(tag)) {
        data.tag_catalog.push(tag);
      }
    });
    closeModal();
    persistData(data, { message: `${parsedCourse.id} saved.`, selectedCourseId: parsedCourse.id });
  });
}

function openCourseModalFromPlaceholder(courseId) {
  openCourseModal(null);
  const idInput = document.getElementById("course-id-input");
  if (idInput) {
    idInput.value = courseId;
  }
}

function renameCourseReferences(data, previousId, nextId) {
  if (previousId === nextId) {
    return;
  }
  data.courses.forEach((course) => {
    course.prerequisites = renamePrereqReference(course.prerequisites, previousId, nextId);
  });
}

function renamePrereqReference(expr, previousId, nextId) {
  if (!expr) {
    return { all_of: [] };
  }
  if (typeof expr === "string") {
    return expr === previousId ? nextId : expr;
  }
  if (Array.isArray(expr)) {
    return expr.map((item) => renamePrereqReference(item, previousId, nextId));
  }
  if (typeof expr === "object") {
    const key = Object.keys(expr).includes("any_of") ? "any_of" : "all_of";
    return {
      [key]: (expr[key] || []).map((item) => renamePrereqReference(item, previousId, nextId)),
    };
  }
  return expr;
}

function openPrerequisiteModal(courseId) {
  const course = getCourse(courseId);
  const state = {
    courseId,
    groups: prerequisiteExpressionToEditorGroups(course.prerequisites),
  };
  if (!state.groups.length) {
    state.groups = [{ type: "all_of", courseIds: [] }];
  }

  const render = (errorMessage = "") => {
    showModal(`
      <div class="modal-card">
        <h3>Prerequisites for ${escapeHtml(courseId)}</h3>
        <p class="helper-text">Build requirement groups visually. Use "All of these are required" for required groups and "One of these options is required" for alternatives.</p>
        ${errorMessage ? `<div class="error-box">${escapeHtml(errorMessage)}</div>` : ""}
        <datalist id="course-options">
          ${getCourses().filter((item) => item.id !== courseId).map((item) => `<option value="${escapeAttribute(`${item.id} - ${item.title}`)}"></option>`).join("")}
        </datalist>
        <div id="prereq-groups-container">
          ${state.groups.map((group, index) => `
            <div class="group-card">
              <div class="group-header">
                <div>
                  <strong>Requirement group ${index + 1}</strong>
                  <div class="helper-text">${group.type === "any_of" ? "Any one course in this group satisfies it." : "Every course in this group is required."}</div>
                </div>
                <button class="danger-btn small-btn" type="button" data-remove-group="${index}">Remove Group</button>
              </div>
              <label class="field-label">Requirement type</label>
              <select class="text-input" data-group-type="${index}">
                <option value="all_of" ${group.type === "all_of" ? "selected" : ""}>All of these are required</option>
                <option value="any_of" ${group.type === "any_of" ? "selected" : ""}>One of these options is required</option>
              </select>
              <div class="field-label">Courses in this group</div>
              <div class="chip-list">
                ${group.courseIds.length ? group.courseIds.map((item) => `<span class="chip">${escapeHtml(item)} <button type="button" data-remove-course="${index}|${escapeHtml(item)}">×</button></span>`).join("") : '<span class="muted-text">No courses added yet.</span>'}
              </div>
              <div class="group-controls">
                <input class="text-input" type="text" list="course-options" placeholder="Search by course ID or title" data-group-input="${index}">
                <button class="secondary-btn small-btn" type="button" data-add-course="${index}">Add Course</button>
              </div>
            </div>
          `).join("")}
        </div>
        <div class="inline-actions">
          <button class="ghost-btn" type="button" id="add-prereq-group-btn">Add Requirement Group</button>
        </div>
        <div class="modal-actions">
          <button type="button" class="ghost-btn" data-close-modal>Cancel</button>
          <button type="button" class="primary-btn" id="save-prereq-groups-btn">Save Prerequisites</button>
        </div>
      </div>
    `);

    document.querySelectorAll("[data-group-type]").forEach((select) => {
      select.addEventListener("change", () => {
        state.groups[Number(select.getAttribute("data-group-type"))].type = select.value;
      });
    });
    document.querySelectorAll("[data-remove-group]").forEach((button) => {
      button.addEventListener("click", () => {
        state.groups.splice(Number(button.getAttribute("data-remove-group")), 1);
        render();
      });
    });
    document.querySelectorAll("[data-remove-course]").forEach((button) => {
      button.addEventListener("click", () => {
        const [groupIndex, courseCode] = button.getAttribute("data-remove-course").split("|");
        state.groups[Number(groupIndex)].courseIds = state.groups[Number(groupIndex)].courseIds.filter((item) => item !== courseCode);
        render();
      });
    });
    document.querySelectorAll("[data-add-course]").forEach((button) => {
      button.addEventListener("click", () => {
        const groupIndex = Number(button.getAttribute("data-add-course"));
        const input = document.querySelector(`[data-group-input="${groupIndex}"]`);
        const raw = input.value.trim();
        const courseCode = raw.includes(" - ") ? raw.split(" - ")[0].trim() : raw;
        if (!courseCode) {
          render("Choose a course to add.");
          return;
        }
        if (courseCode === courseId) {
          render("A course cannot depend on itself.");
          return;
        }
        const valid = getCourses().some((item) => item.id === courseCode);
        if (!valid) {
          render(`No course found with ID ${courseCode}.`);
          return;
        }
        if (!state.groups[groupIndex].courseIds.includes(courseCode)) {
          state.groups[groupIndex].courseIds.push(courseCode);
        }
        render();
      });
    });
    document.getElementById("add-prereq-group-btn").addEventListener("click", () => {
      state.groups.push({ type: "all_of", courseIds: [] });
      render();
    });
    document.getElementById("save-prereq-groups-btn").addEventListener("click", () => {
      if (state.groups.some((group) => group.courseIds.length === 0)) {
        render("Every requirement group needs at least one course, or you can remove the empty group.");
        return;
      }
      const data = cloneData();
      const editable = data.courses.find((item) => item.id === courseId);
      editable.prerequisites = editorGroupsToExpression(state.groups);
      closeModal();
      persistData(data, { message: `Updated prerequisites for ${courseId}.`, selectedCourseId: courseId });
    });
  };

  render();
}

function prerequisiteExpressionToEditorGroups(expr) {
  if (!expr || !expr.all_of || !expr.all_of.length) {
    return [];
  }
  return expr.all_of.map((entry) => {
    if (typeof entry === "string") {
      return { type: "all_of", courseIds: [entry] };
    }
    if (entry.any_of) {
      return { type: "any_of", courseIds: flattenPrereqExpression(entry) };
    }
    if (entry.all_of) {
      return { type: "all_of", courseIds: flattenPrereqExpression(entry) };
    }
    return { type: "all_of", courseIds: [] };
  });
}

function editorGroupsToExpression(groups) {
  return {
    all_of: groups.map((group) => ({
      [group.type]: [...new Set(group.courseIds)].sort(),
    })),
  };
}

function flattenPrereqExpression(expr) {
  if (!expr) {
    return [];
  }
  if (typeof expr === "string") {
    return [expr];
  }
  if (Array.isArray(expr)) {
    return expr.flatMap(flattenPrereqExpression);
  }
  if (expr.any_of) {
    return expr.any_of.flatMap(flattenPrereqExpression);
  }
  if (expr.all_of) {
    return expr.all_of.flatMap(flattenPrereqExpression);
  }
  return [];
}

function openEdgeModal(edgeData) {
  const source = edgeData.source;
  const target = edgeData.target;
  showModal(`
    <div class="modal-card">
      <h3>Prerequisite Link</h3>
      <p class="helper-text"><span class="mono">${escapeHtml(source)}</span> must be completed before <span class="mono">${escapeHtml(target)}</span>.</p>
      <div class="list-pill"><strong>Group label:</strong> ${escapeHtml(edgeData.label || "Unlabeled")}</div>
      <div class="modal-actions">
        <button type="button" class="ghost-btn" data-close-modal>Close</button>
        <button type="button" class="secondary-btn" id="open-edge-editor-btn">Edit in Prerequisite Editor</button>
        <button type="button" class="danger-btn" id="remove-edge-btn">Remove Link</button>
      </div>
    </div>
  `);
  document.getElementById("open-edge-editor-btn").addEventListener("click", () => {
    closeModal();
    openPrerequisiteModal(target);
  });
  document.getElementById("remove-edge-btn").addEventListener("click", () => {
    closeModal();
    const data = cloneData();
    const course = data.courses.find((item) => item.id === target);
    course.prerequisites = removePrereqReference(course.prerequisites, source);
    persistData(data, { message: `Removed ${source} → ${target}.`, selectedCourseId: target });
  });
}

function removePrereqReference(expr, courseId) {
  if (!expr) {
    return { all_of: [] };
  }
  if (typeof expr === "string") {
    return expr === courseId ? null : expr;
  }
  const key = expr.any_of ? "any_of" : "all_of";
  const nextItems = (expr[key] || [])
    .map((item) => removePrereqReference(item, courseId))
    .filter((item) => {
      if (!item) {
        return false;
      }
      if (typeof item === "object") {
        const innerKey = item.any_of ? "any_of" : "all_of";
        return item[innerKey]?.length;
      }
      return true;
    });
  if (!nextItems.length) {
    return { all_of: [] };
  }
  return { [key]: nextItems };
}

function confirmDeleteCourse(courseId) {
  const insights = appState.graph.course_insights[courseId];
  const relationshipCount = insights.direct_prerequisites.length + insights.directly_unlocked_courses.length;
  showConfirmModal({
    title: `Delete ${courseId}?`,
    message: `This will remove the course and ${relationshipCount} connected prerequisite relationship${relationshipCount === 1 ? "" : "s"}.`,
    confirmLabel: "Delete Course",
    danger: true,
    onConfirm: () => {
      const data = cloneData();
      data.courses = data.courses.filter((item) => item.id !== courseId);
      if (data.meta.target_course_id === courseId) {
        data.meta.target_course_id = "";
      }
      data.courses.forEach((course) => {
        course.prerequisites = removePrereqReference(course.prerequisites, courseId);
      });
      persistData(data, { message: `${courseId} deleted.`, selectedCourseId: null });
    },
  });
}

function setTargetCourse(courseId) {
  const data = cloneData();
  data.meta.target_course_id = courseId;
  const course = data.courses.find((item) => item.id === courseId);
  if (course && !course.categories.includes("target course")) {
    course.categories.push("target course");
  }
  if (!data.tag_catalog.includes("target course")) {
    data.tag_catalog.push("target course");
  }
  persistData(data, { message: `${courseId} is now the active target course.`, selectedCourseId: courseId });
}

function openTagModal(mode, tag = "") {
  if (mode === "delete") {
    showConfirmModal({
      title: `Delete tag "${tag}"?`,
      message: "This will remove the tag from the tag catalog and from any course currently using it.",
      confirmLabel: "Delete Tag",
      danger: true,
      onConfirm: () => {
        const data = cloneData();
        data.tag_catalog = data.tag_catalog.filter((item) => item !== tag);
        data.courses.forEach((course) => {
          course.categories = course.categories.filter((item) => item !== tag);
        });
        persistData(data, { message: `Deleted tag ${tag}.`, selectedCourseId: appState.selectedCourseId });
      },
    });
    return;
  }

  showModal(`
    <div class="modal-card">
      <h3>${mode === "rename" ? "Rename Tag" : "Create Tag"}</h3>
      <label class="field-label" for="tag-name-input">Tag name</label>
      <input id="tag-name-input" class="text-input" type="text" value="${escapeAttribute(tag)}" placeholder="analysis">
      <div id="tag-modal-error"></div>
      <div class="modal-actions">
        <button type="button" class="ghost-btn" data-close-modal>Cancel</button>
        <button type="button" class="primary-btn" id="save-tag-btn">${mode === "rename" ? "Save Tag" : "Create Tag"}</button>
      </div>
    </div>
  `);
  document.getElementById("save-tag-btn").addEventListener("click", () => {
    const nextValue = document.getElementById("tag-name-input").value.trim();
    const errorBox = document.getElementById("tag-modal-error");
    if (!nextValue) {
      errorBox.innerHTML = '<div class="error-box">Tag name cannot be empty.</div>';
      return;
    }
    if (appState.data.tag_catalog.includes(nextValue) && nextValue !== tag) {
      errorBox.innerHTML = '<div class="error-box">That tag already exists.</div>';
      return;
    }
    const data = cloneData();
    if (mode === "rename") {
      data.tag_catalog = data.tag_catalog.map((item) => (item === tag ? nextValue : item));
      data.courses.forEach((course) => {
        course.categories = course.categories.map((item) => (item === tag ? nextValue : item));
      });
    } else if (!data.tag_catalog.includes(nextValue)) {
      data.tag_catalog.push(nextValue);
    }
    closeModal();
    persistData(data, { message: mode === "rename" ? `Renamed ${tag} to ${nextValue}.` : `Created tag ${nextValue}.`, selectedCourseId: appState.selectedCourseId });
  });
}

async function quickUpdateCourse(courseId, updater, options = {}) {
  const data = cloneData();
  const course = data.courses.find((item) => item.id === courseId);
  updater(course, data);
  await persistData(data, { message: options.message || `${courseId} updated.`, selectedCourseId: courseId });
}

async function persistData(data, options = {}) {
  setSaveIndicator("saving", "Saving...");
  try {
    const response = await fetch("/api/save", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        data,
        force: Boolean(options.force),
      }),
    });
    const payload = await response.json();
    if (response.status === 409 && payload.needs_confirmation) {
      setSaveIndicator("warning", "Needs confirmation");
      showConfirmModal({
        title: "Validation warning",
        message: payload.warnings.join(" "),
        confirmLabel: "Save Anyway",
        onConfirm: () => persistData(data, { ...options, force: true }),
      });
      return;
    }
    if (!response.ok || !payload.ok) {
      const messages = payload.errors || payload.warnings || ["Save failed."];
      throw new Error(messages.join(" "));
    }
    const applyOptions = {};
    if (Object.prototype.hasOwnProperty.call(options, "selectedCourseId")) {
      applyOptions.selectedCourseId = options.selectedCourseId;
    }
    applyState(payload.state, applyOptions);
    setSaveIndicator("saved", "Saved");
    showToast(options.message || "Saved changes.");
  } catch (error) {
    setSaveIndicator("error", "Save failed");
    showToast(error.message);
  }
}

async function undoLastChange() {
  setSaveIndicator("saving", "Undoing...");
  try {
    const response = await fetch("/api/undo", { method: "POST" });
    const payload = await response.json();
    if (!response.ok || !payload.ok) {
      throw new Error((payload.errors || ["Undo failed."]).join(" "));
    }
    applyState(payload.state);
    setSaveIndicator("saved", "Undo complete");
    showToast("Restored the previous saved version.");
  } catch (error) {
    setSaveIndicator("error", "Undo failed");
    showToast(error.message);
  }
}

async function handleImportFile(event) {
  const file = event.target.files?.[0];
  if (!file) {
    return;
  }
  try {
    const text = await file.text();
    const parsed = JSON.parse(text);
    await importData(parsed);
  } catch (error) {
    showToast(`Could not import JSON: ${error.message}`);
  } finally {
    event.target.value = "";
  }
}

async function importData(data, force = false) {
  setSaveIndicator("saving", "Importing...");
  try {
    const response = await fetch("/api/import", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ data, force }),
    });
    const payload = await response.json();
    if (response.status === 409 && payload.needs_confirmation) {
      setSaveIndicator("warning", "Import warning");
      showConfirmModal({
        title: "Import warning",
        message: payload.warnings.join(" "),
        confirmLabel: "Import Anyway",
        onConfirm: () => importData(data, true),
      });
      return;
    }
    if (!response.ok || !payload.ok) {
      throw new Error((payload.errors || ["Import failed."]).join(" "));
    }
    applyState(payload.state);
    setSaveIndicator("saved", "Import complete");
    showToast("Imported graph data.");
  } catch (error) {
    setSaveIndicator("error", "Import failed");
    showToast(error.message);
  }
}

function exportGraphPng() {
  if (!appState.cy) {
    return;
  }
  const png = appState.cy.png({ bg: "#fffdf8", full: true, scale: 2 });
  downloadDataUrl(png, "math-planner-graph.png");
}

function exportGraphSvg() {
  if (!appState.cy || typeof appState.cy.svg !== "function") {
    showToast("SVG export is not available in this browser.");
    return;
  }
  const svg = appState.cy.svg({ full: true, scale: 1 });
  const blob = new Blob([svg], { type: "image/svg+xml;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "math-planner-graph.svg";
  link.click();
  URL.revokeObjectURL(url);
}

function showModal(content) {
  const root = document.getElementById("modal-root");
  root.hidden = false;
  root.innerHTML = content;
  root.querySelectorAll("[data-close-modal]").forEach((button) => button.addEventListener("click", closeModal));
  root.onclick = (event) => {
    if (event.target.id === "modal-root") {
      closeModal();
    }
  };
}

function closeModal() {
  const root = document.getElementById("modal-root");
  root.onclick = null;
  root.hidden = true;
  root.innerHTML = "";
}

function showConfirmModal({ title, message, confirmLabel, danger = false, onConfirm }) {
  showModal(`
    <div class="modal-card">
      <h3>${escapeHtml(title)}</h3>
      <div class="${danger ? "warning-box" : "list-pill"}">${escapeHtml(message)}</div>
      <div class="modal-actions">
        <button type="button" class="ghost-btn" data-close-modal>Cancel</button>
        <button type="button" class="${danger ? "danger-btn" : "primary-btn"}" id="confirm-modal-btn">${escapeHtml(confirmLabel)}</button>
      </div>
    </div>
  `);
  document.getElementById("confirm-modal-btn").addEventListener("click", () => {
    closeModal();
    onConfirm();
  });
}

function setSaveIndicator(state, text) {
  const pill = document.getElementById("save-indicator");
  pill.dataset.state = state;
  pill.textContent = text;
}

let toastTimer = null;
function showToast(message) {
  const toast = document.getElementById("toast");
  toast.textContent = message;
  toast.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    toast.hidden = true;
  }, 3200);
}

function cloneData() {
  return structuredClone(appState.data);
}

function getCourses() {
  return appState.data?.courses || [];
}

function getCourse(courseId) {
  return getCourses().find((course) => course.id === courseId) || null;
}

function parseCommaList(value) {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function capitalize(value) {
  return value ? `${value[0].toUpperCase()}${value.slice(1)}` : "";
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function escapeAttribute(value) {
  return escapeHtml(value);
}

function downloadDataUrl(dataUrl, filename) {
  const link = document.createElement("a");
  link.href = dataUrl;
  link.download = filename;
  link.click();
}
