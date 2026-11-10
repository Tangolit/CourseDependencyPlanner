const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

const context = vm.createContext({
  cytoscape: { use() {} }, cytoscapeDagre: {}, document: { addEventListener() {} },
});
vm.runInContext(fs.readFileSync("static/app.js", "utf8"), context);
const run = (expression) => vm.runInContext(expression, context);

test("nested requirements do not enter the flattening group editor", () => {
  assert.equal(run('canUseGroupEditor({any_of: [{all_of: ["A", "B"]}, "C"]})'), false);
  assert.equal(run('canUseGroupEditor({all_of: [{any_of: ["A", "B"]}, "C"]})'), true);
});

test("root OR groups round trip without becoming AND", () => {
  assert.equal(run('JSON.stringify(editorGroupsToExpression(prerequisiteExpressionToEditorGroups({any_of: ["A", "B"]})))'),
    '{"all_of":[{"any_of":["A","B"]}]}');
});

test("details preserve visible nested AND/OR structure", () => {
  assert.equal(run('formatRequirement({any_of: [{all_of: ["A", "B"]}, "C"]})'), '((A AND B) OR C)');
  assert.equal(run('formatRequirement({any_of: []})'), 'No valid option');
});
