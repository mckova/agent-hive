"""Offline UI regressions: real app.js handlers, a small DOM, no Pyodide/CDN.

Node is optional for Python-only consumers. These tests exercise JavaScript and
semantic HTML/CSS contracts; they do not claim browser rendering coverage.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import unittest
from html.parser import HTMLParser
from pathlib import Path


SPACE = Path(__file__).resolve().parents[1] / "space"
NODE = shutil.which("node")


class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.nodes = []
        self.stack = []
        self.feed((SPACE / "index.html").read_text(encoding="utf-8"))
        self.ids = {node["attrs"]["id"]: node for node in self.nodes if "id" in node["attrs"]}

    def handle_starttag(self, tag, attrs):
        node = {"tag": tag, "attrs": dict(attrs), "parent": self.stack[-1] if self.stack else None, "text": ""}
        index = len(self.nodes)
        self.nodes.append(node)
        if tag not in {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}:
            self.stack.append(index)

    def handle_endtag(self, tag):
        for position in range(len(self.stack) - 1, -1, -1):
            if self.nodes[self.stack[position]]["tag"] == tag:
                del self.stack[position:]
                break

    def handle_data(self, data):
        for index in self.stack:
            self.nodes[index]["text"] += data


HARNESS = r"""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const metadata = input.nodes;
class Element {
  constructor(node) {
    this.tagName = node.tag.toUpperCase();
    this.attrs = {...node.attrs};
    this.id = this.attrs.id || '';
    this.value = this.attrs.value || '';
    this.textContent = node.text;
    this.hidden = Object.hasOwn(this.attrs, 'hidden');
    this.disabled = Object.hasOwn(this.attrs, 'disabled');
    this.dataset = {};
    for (const [key, value] of Object.entries(this.attrs)) {
      if (key.startsWith('data-')) this.dataset[key.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase())] = value;
    }
    this.className = this.attrs.class || '';
    const classes = new Set(this.className.split(/\s+/).filter(Boolean));
    this.classList = {add: value => classes.add(value), remove: value => classes.delete(value), contains: value => classes.has(value)};
    this.handlers = {};
    this.children = [];
    this.scrolls = [];
    this.focuses = [];
  }
  addEventListener(type, handler) { (this.handlers[type] ||= []).push(handler); }
  emit(type, target = this) {
    const event = {type, target, defaultPrevented: false, preventDefault() { this.defaultPrevented = true; }};
    let node = this;
    do {
      for (const handler of node.handlers[type] || []) handler(event);
      node = node.parentElement;
    } while (node && (type === 'input' || type === 'change'));
    return event;
  }
  appendChild(child) { this.children.push(child); child.parentElement = this; return child; }
  replaceChildren(...children) { this.children = children; }
  setAttribute(name, value) { this.attrs[name] = String(value); }
  getAttribute(name) { return Object.hasOwn(this.attrs, name) ? this.attrs[name] : null; }
  removeAttribute(name) { delete this.attrs[name]; }
  focus(options) { this.focuses.push(options); }
  scrollIntoView(options) { this.scrolls.push(options); }
}
const nodes = metadata.map(node => new Element(node));
metadata.forEach((node, index) => { if (node.parent !== null) nodes[node.parent].appendChild(nodes[index]); });
const byId = Object.fromEntries(nodes.filter(node => node.id).map(node => [node.id, node]));
function matches(node, selector) {
  if (selector.startsWith('#')) return node.id === selector.slice(1);
  if (selector.startsWith('.')) return node.classList.contains(selector.slice(1));
  const attr = selector.match(/^\[([^\]=]+)(?:=["']?([^"'\]]+)["']?)?\]$/);
  if (attr) return Object.hasOwn(node.attrs, attr[1]) && (attr[2] === undefined || node.attrs[attr[1]] === attr[2]);
  return node.tagName.toLowerCase() === selector;
}
const document = {
  querySelector(selector) { const node = nodes.find(item => matches(item, selector)); assert.ok(node, `Unknown selector: ${selector}`); return node; },
  querySelectorAll(selector) { return nodes.filter(item => matches(item, selector)); },
  createElement(tag) { return new Element({tag, attrs: {}, text: ''}); },
};
byId.goal.value = 'Review a synthetic project';
byId.quality.value = 'balanced';
byId.target.value = 'codex';
const h = {byId, nodes, calls: [], failure: null, raw: null};
function mockPlanner(...args) {
  h.calls.push(args);
  if (h.failure !== null) throw h.failure;
  if (h.raw !== null) return h.raw;
  return JSON.stringify({
    queen: {goal: args[0], rule: 'Review before execution', must: [], avoid: [], doneWhen: []},
    assignments: [], metrics: {cells: 6, waves: 5, spendable: 80000, reserve: 20000},
    waves: 'survey + forage -> design -> build -> verify -> archive', planRows: [], variantRows: [],
    bestPrompt: 'synthetic prompt', mission: {goal: args[0]}, payloads: 'synthetic payload', guardrails: {allowNetwork: false},
  });
}
const context = vm.createContext({document, console: {error() {}}, Intl, navigator: {clipboard: {writeText: async () => {}}}, setTimeout() {}, h, assert, mockPlanner});
const source = fs.readFileSync(process.argv[1], 'utf8');
// Only the final bootstrap is suppressed. All tested functions and handlers are
// evaluated unchanged; neither Pyodide nor any project network code runs.
assert.match(source, /\bbootPython\(\);\s*$/);
vm.runInContext(source.replace(/\bbootPython\(\);\s*$/, ''), context);
vm.runInContext('buildPlan = mockPlanner;', context);
vm.runInContext(input.scenario, context);
"""


@unittest.skipUnless(NODE, "Node is unavailable; offline JavaScript behavior tests require Node")
class SpaceUIBehaviorTests(unittest.TestCase):
    def run_js(self, scenario):
        completed = subprocess.run(
            [NODE, "-e", HARNESS, str(SPACE / "app.js")],
            input=json.dumps({"nodes": Page().nodes, "scenario": scenario}),
            capture_output=True, text=True, encoding="utf-8", timeout=20, check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)

    def test_empty_and_whitespace_submit_hide_old_result_without_planning(self):
        self.run_js(r"""
          const {byId: e} = h;
          e['planner-form'].emit('submit');
          assert.equal(e.results.hidden, false);
          for (const goal of ['', '   ', '\t\n ']) {
            e.goal.value = goal;
            const event = e['planner-form'].emit('submit');
            assert.equal(event.defaultPrevented, true);
            assert.equal(e.results.hidden, true);
            assert.ok(e['form-error'].textContent.trim());
            assert.equal(e.goal.getAttribute('aria-invalid'), 'true');
          }
          assert.equal(h.calls.length, 1);
        """)

    def test_input_and_change_invalidate_each_editable_field(self):
        self.run_js(r"""
          const {byId: e} = h;
          for (const id of ['goal', 'must', 'avoid', 'done', 'total', 'reserve', 'workers', 'quality', 'target']) {
            for (const event of ['input', 'change']) {
              e['planner-form'].emit('submit');
              assert.equal(e.results.hidden, false);
              const calls = h.calls.length;
              e[id].emit(event);
              assert.equal(e.results.hidden, true, `${id} ${event} must hide the previous plan`);
              assert.equal(h.calls.length, calls);
            }
          }
        """)

    def test_presets_hide_old_plan_without_implicitly_planning(self):
        self.run_js(r"""
          const {byId: e} = h;
          const presets = h.nodes.filter(node => node.dataset.example);
          assert.ok(presets.length > 0, 'Prepared examples must remain available');
          for (const button of presets) {
            e['planner-form'].emit('submit');
            const calls = h.calls.length;
            button.emit('click');
            assert.equal(e.results.hidden, true);
            assert.equal(h.calls.length, calls);
            assert.ok(e.goal.value.trim());
            assert.ok(e.goal.focuses.length);
          }
        """)

    def test_valid_submit_recovers_after_validation_error_and_clears_marker(self):
        self.run_js(r"""
          const {byId: e} = h;
          e.goal.value = ' ';
          e['planner-form'].emit('submit');
          e.goal.value = 'New synthetic goal';
          e.goal.emit('input');
          assert.equal(e['form-error'].textContent, '');
          assert.notEqual(e.goal.getAttribute('aria-invalid'), 'true');
          e['planner-form'].emit('submit');
          assert.equal(e.results.hidden, false);
          assert.equal(e['queen-goal'].textContent, 'New synthetic goal');
          assert.equal(e['form-error'].textContent, '');
          assert.equal(h.calls.length, 1);
          assert.equal(e.results.scrolls.length, 1);
        """)

    def test_multiline_python_error_with_trailing_newline_is_visible(self):
        self.run_js(r"""
          const {byId: e} = h;
          e['planner-form'].emit('submit');
          h.failure = 'PythonError: Traceback (most recent call last):\n  File "synthetic.py", line 1\nValueError: Enter a mission goal.\n\n';
          e['planner-form'].emit('submit');
          assert.equal(e.results.hidden, true);
          assert.equal(e['form-error'].textContent, 'Enter a mission goal.');
          h.failure = null;
          e['planner-form'].emit('submit');
          assert.equal(e.results.hidden, false);
          assert.equal(e['form-error'].textContent, '');
        """)

    def test_empty_exception_and_invalid_json_do_not_reveal_old_output(self):
        self.run_js(r"""
          const {byId: e} = h;
          e['planner-form'].emit('submit');
          h.failure = '';
          e['planner-form'].emit('submit');
          assert.equal(e.results.hidden, true);
          assert.ok(e['form-error'].textContent.trim());
          h.failure = null;
          h.raw = '{invalid json';
          e['planner-form'].emit('submit');
          assert.equal(e.results.hidden, true);
          assert.ok(e['form-error'].textContent.trim());
        """)

    def test_numeric_constraint_errors_never_reach_planner(self):
        self.run_js(r"""
          const {byId: e} = h;
          for (const [id, invalidValues] of [
            ['total', ['', '0', '5000001', '1500', 'not a number']],
            ['reserve', ['-1', '81', '1.5']],
            ['workers', ['0', '13', '1.5']],
          ]) {
            const original = e[id].value;
            for (const value of invalidValues) {
              e[id].value = value;
              e['planner-form'].emit('submit');
              assert.equal(e.results.hidden, true);
              assert.ok(e['form-error'].textContent.trim(), `${id}=${value}`);
              assert.equal(e[id].getAttribute('aria-invalid'), 'true');
              assert.equal(h.calls.length, 0);
            }
            e[id].value = original;
          }
          e['planner-form'].emit('submit');
          assert.equal(h.calls.length, 1);
          assert.equal(e.results.hidden, false);
        """)

    def test_engine_unavailable_hides_previous_result_with_visible_error(self):
        self.run_js(r"""
          const {byId: e} = h;
          e['planner-form'].emit('submit');
          buildPlan = undefined;
          e['planner-form'].emit('submit');
          assert.equal(e.results.hidden, true);
          assert.ok(e['form-error'].textContent.trim());
          assert.equal(h.calls.length, 1);
        """)

    def test_cta_scrolls_actual_form_and_focuses_goal_without_extra_scroll(self):
        self.run_js(r"""
          const {byId: e} = h;
          const event = e['try-planner'].emit('click');
          assert.equal(event.defaultPrevented, true);
          assert.equal(e['planner-form'].scrolls.length, 1);
          assert.equal(e['planner-form'].scrolls[0].block, 'start');
          assert.equal(e.goal.focuses.at(-1).preventScroll, true);
          assert.equal(h.calls.length, 0);
        """)


class SpaceUISemanticsTests(unittest.TestCase):
    def test_error_and_field_labels_are_programmatically_connected(self):
        page = Page()
        self.assertEqual(page.ids["form-error"]["attrs"].get("role"), "alert")
        # Custom validation handles submit for both native-empty and whitespace
        # values; retaining required/bounds communicates constraints to browsers.
        self.assertIn("novalidate", page.ids["planner-form"]["attrs"])
        self.assertIn("required", page.ids["goal"]["attrs"])
        for field, label in {"goal": "Mission goal", "total": "Total token budget", "reserve": "Protected reserve", "workers": "Maximum cells per wave"}.items():
            with self.subTest(field=field):
                node = page.ids[field]
                self.assertIn("form-error", node["attrs"].get("aria-describedby", "").split())
                parent = node["parent"]
                while parent is not None and page.nodes[parent]["tag"] != "label":
                    parent = page.nodes[parent]["parent"]
                self.assertIsNotNone(parent, f"{field} needs an associated label")
                self.assertIn(label, page.nodes[parent]["text"])
        for field, bounds in {"total": ("1000", "5000000"), "reserve": ("0", "80"), "workers": ("1", "12")}.items():
            self.assertEqual(tuple(page.ids[field]["attrs"].get(key) for key in ("min", "max")), bounds)
        self.assertEqual(page.ids["total"]["attrs"].get("step"), "1000")

    def test_hero_cta_links_to_form_before_form_and_results(self):
        page = Page()
        cta = page.ids["try-planner"]
        self.assertEqual(cta["tag"], "a")
        self.assertEqual(cta["attrs"].get("href"), "#planner-form")
        self.assertIn("try the planner", cta["text"].lower())
        self.assertEqual(page.ids["planner-form"]["tag"], "form")
        self.assertLess(page.nodes.index(cta), page.nodes.index(page.ids["planner-form"]))
        self.assertIn("hidden", page.ids["results"]["attrs"])

    def test_scroll_margin_clears_sticky_header_for_form_and_results(self):
        css = (SPACE / "styles.css").read_text(encoding="utf-8")
        rules = re.findall(r"([^{}]+)\{([^{}]*)\}", css)
        header = next(body for selectors, body in rules if selectors.strip() == ".site-header")
        self.assertRegex(header, r"position\s*:\s*sticky")
        height = int(re.search(r"height\s*:\s*(\d+)px", header).group(1))
        for target in ("#planner-form", "#results"):
            margins = [int(match.group(1)) for selectors, body in rules if target in [s.strip() for s in selectors.split(",")]
                       if (match := re.search(r"scroll-margin(?:-top|-block-start)?\s*:\s*(\d+)px", body))]
            self.assertTrue(any(margin > height for margin in margins), f"{target} must clear the {height}px sticky header")


if __name__ == "__main__":
    unittest.main()
