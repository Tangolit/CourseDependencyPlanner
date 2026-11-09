# Michigan Math Planner

A polished local web application for planning University of Michigan LSA math coursework as an interactive directed prerequisite graph.

The app uses:

- `Flask` for the local web app
- `NetworkX` for graph representation and analysis
- `Cytoscape.js` for the interactive prerequisite graph
- local JSON storage in [data/courses.json](/c:/Users/pn217/Downloads/New%20folder%20%285%29/data/courses.json)

Sample prerequisites and offerings are illustrative only. Official University of Michigan LSA, Math Department, and Course Guide information controls for actual enrollment requirements.

## Project structure

```text
New folder (5)/
├── app.py
├── README.md
├── requirements.txt
├── data/
│   └── courses.json
├── planner/
│   ├── __init__.py
│   ├── data_store.py
│   └── graph_logic.py
├── static/
│   ├── app.js
│   └── styles.css
└── templates/
    └── index.html
```

## Setup

### Windows

1. Open PowerShell in the project folder.
2. Create a virtual environment:

```powershell
py -m venv .venv
```

3. Activate it:

```powershell
.\.venv\Scripts\Activate.ps1
```

4. Install dependencies:

```powershell
pip install -r requirements.txt
```

5. Run the app:

```powershell
py app.py
```

6. Open `http://127.0.0.1:5000`.

### macOS

1. Open Terminal in the project folder.
2. Create a virtual environment:

```bash
python3 -m venv .venv
```

3. Activate it:

```bash
source .venv/bin/activate
```

4. Install dependencies:

```bash
pip install -r requirements.txt
```

5. Run the app:

```bash
python3 app.py
```

6. Open `http://127.0.0.1:5000`.

## How the visual editor works

### Course editing

- Use `Add Course` to create a new node.
- Click any course node to open the detail panel.
- Double-click a node or use `Edit Course` to change metadata.
- Change status directly from the detail panel. Node color updates immediately after save.
- Edit notes, verified state, and tags directly in the detail panel.
- Delete a course from the detail panel. The app warns that connected prerequisite relationships will also be removed.

### Prerequisite editing

- Select a course and click `Add Prerequisite`.
- Build requirement groups visually:
  - `All of these are required`
  - `One of these options is required`
- Add multiple groups to represent combinations like:

```text
Requires:
- one of: MATH 217, MATH 214
- and one of: STATS 412, MATH 425
```

- Use `Add Prerequisite Link` for quick graph editing:
  1. click the prerequisite course
  2. click the dependent course
  3. the app creates `prerequisite -> dependent`
- Click an edge to open its relationship dialog, then remove it or jump into the full prerequisite editor.

### Analysis tools

- Set any course as the active target from the detail panel.
- Turn on `Path to selected target only` to dim unrelated courses.
- Use `Gateway Courses` to find nodes with the largest downstream impact.
- Use `My Next Options` to see courses whose prerequisites are satisfied by completed courses.
- Clicking search results, gateway items, downstream courses, or next options will focus that course in the graph.

## Back up, import, and export

- `Export JSON` downloads the current graph data as a JSON backup.
- `Import JSON` lets you restore a previous backup or load an externally edited file.
- `Undo Last Change` restores the previous saved snapshot in the current session.
- The app auto-saves to [data/courses.json](/c:/Users/pn217/Downloads/New%20folder%20%285%29/data/courses.json) and shows a visible saved state indicator.

## Validation and safeguards

- Duplicate course IDs are blocked.
- Self-prerequisites are blocked.
- Missing prerequisite references generate warnings before save.
- Detected cycles generate warnings before save.
- Invalid imports surface clear error messages instead of silently discarding changes.

## Notes

- Front-end graph libraries are loaded from CDN in [templates/index.html](/c:/Users/pn217/Downloads/New%20folder%20%285%29/templates/index.html).
- All planner data is stored locally. No login, hosted database, or cloud account is required.
