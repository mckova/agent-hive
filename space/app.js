const PYTHON_FILES = [
  "hive_playground.py",
  "agent_hive/__init__.py",
  "agent_hive/mission.py",
  "agent_hive/planner.py",
  "agent_hive/prompt_compiler.py",
  "agent_hive/protocol.py",
  "agent_hive/token_counter.py",
];

const EXAMPLES = {
  demo: {
    goal: "Add secure passwordless sign-in without breaking existing email/password users",
    must: "Keep backward compatibility\nPreserve existing sessions\nAdd migration and rollback paths",
    avoid: "Do not log secrets or authentication tokens\nDo not deploy automatically",
    done: "Existing login tests pass\nThe new flow has security tests\nA migration guide is documented",
  },
  he: {
    goal: "הוסף אימות דו-שלבי לאפליקציה בלי לשבור משתמשים קיימים",
    must: "שמור על תאימות לאחור\nהוסף בדיקות אבטחה",
    avoid: "אל תשמור סודות בלוגים",
    done: "כל הבדיקות עוברות\nקיים תיעוד migration",
  },
  es: {
    goal: "Migrar la API de pagos sin interrumpir el servicio",
    must: "Mantener compatibilidad\nAñadir rollback",
    avoid: "No desplegar automáticamente",
    done: "Pruebas de integración aprobadas",
  },
  ja: {
    goal: "既存のログイン機能を壊さずにパスワード再設定を追加する",
    must: "回帰テストを追加する",
    avoid: "本番環境へ自動デプロイしない",
    done: "セキュリティテストが成功する",
  },
};

let buildPlan;

async function bootPython() {
  const status = document.querySelector("#runtime-status");
  const dot = document.querySelector("#runtime-dot");
  try {
    const { loadPyodide } = await import(
      "https://cdn.jsdelivr.net/pyodide/v314.0.2/full/pyodide.mjs"
    );
    const pyodide = await loadPyodide({
      indexURL: "https://cdn.jsdelivr.net/pyodide/v314.0.2/full/",
    });
    pyodide.FS.mkdirTree("/app/agent_hive");
    await Promise.all(PYTHON_FILES.map(async (path) => {
      const response = await fetch(path, { cache: "no-cache" });
      if (!response.ok) throw new Error(`Could not load ${path}`);
      pyodide.FS.writeFile(`/app/${path}`, await response.text(), { encoding: "utf8" });
    }));
    await pyodide.runPythonAsync(`
import json
import sys
sys.path.insert(0, "/app")
from hive_playground import build_playground_result

def build_plan_json(goal, must, avoid, done, total, reserve, workers, quality, target):
    result = build_playground_result(goal, must, avoid, done, total, reserve, workers, quality, target)
    return json.dumps(result, ensure_ascii=False)
`);
    buildPlan = pyodide.globals.get("build_plan_json");
    status.textContent = "Python engine ready · runs locally in your browser";
    dot.classList.add("ready");
    document.querySelector("#plan-button").disabled = false;
    if (!value("goal").trim()) {
      applyExample(EXAMPLES.demo);
      runPlanner(false);
    }
  } catch (error) {
    console.error(error);
    status.textContent = "Python engine could not load. Refresh to retry.";
    dot.classList.add("error");
    showPlannerError("The browser could not load Pyodide from its CDN. Refresh to retry.");
  }
}

function value(id) { return document.querySelector(`#${id}`).value; }
function number(id) { return Number(value(id)); }
function formatNumber(value) { return new Intl.NumberFormat().format(value); }

function invalidatePlan() {
  document.querySelector("#results").hidden = true;
  document.querySelector("#form-error").textContent = "";
  ["goal", "total", "reserve", "workers"].forEach((id) => {
    document.querySelector(`#${id}`).removeAttribute("aria-invalid");
  });
}

function showPlannerError(message, field = null) {
  if (field) field.focus();
  document.querySelector("#results").hidden = true;
  document.querySelector("#form-error").textContent = message;
  if (field) {
    field.setAttribute("aria-invalid", "true");
  }
}

function plannerErrorMessage(cause) {
  const lines = String(cause ?? "").split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
  const message = (lines.at(-1) || "").replace(/^(?:[\w.]*Error:\s*)+/, "").trim();
  return message || "Could not create a plan. Check the mission and try again.";
}

function validatePlannerInput() {
  const goal = document.querySelector("#goal");
  if (!goal.value.trim()) {
    showPlannerError("Enter a mission goal in any language.", goal);
    return false;
  }
  const limits = [
    ["total", 1_000, 5_000_000, 1_000, "Total token budget must be a whole number from 1,000 to 5,000,000 in steps of 1,000."],
    ["reserve", 0, 80, 1, "Protected reserve must be a whole percentage from 0 to 80."],
    ["workers", 1, 12, 1, "Maximum cells per wave must be a whole number from 1 to 12."],
  ];
  for (const [id, minimum, maximum, step, message] of limits) {
    const field = document.querySelector(`#${id}`);
    const amount = Number(field.value);
    if (!field.value.trim() || !Number.isInteger(amount) || amount < minimum || amount > maximum || (amount - minimum) % step !== 0) {
      showPlannerError(message, field);
      return false;
    }
  }
  return true;
}

function element(tag, className = "", text = "") {
  const item = document.createElement(tag);
  if (className) item.className = className;
  if (text) item.textContent = text;
  return item;
}

function renderConstraintList(id, items, emptyText) {
  const list = document.querySelector(`#${id}`);
  list.replaceChildren();
  const values = items.length ? items : [emptyText];
  values.forEach((text) => list.appendChild(element("li", items.length ? "" : "empty", text)));
}

function renderAssignments(assignments) {
  const grid = document.querySelector("#assignment-grid");
  grid.replaceChildren();
  assignments.forEach((assignment) => {
    const card = element("article", "assignment-card");
    card.dataset.role = assignment.role;

    const head = element("div", "assignment-head");
    const identity = element("div");
    identity.appendChild(element("span", "assignment-wave", `WAVE ${assignment.wave} · ${assignment.id.toUpperCase()}`));
    identity.appendChild(element("h3", "", assignment.roleName));
    head.appendChild(identity);
    head.appendChild(element("span", "role-pill", assignment.required ? "REQUIRED" : "OPTIONAL"));
    card.appendChild(head);

    const task = element("p", "assignment-task", assignment.task);
    task.dir = "auto";
    card.appendChild(task);
    card.appendChild(element("p", "assignment-purpose", assignment.purpose));

    const contract = element("div", "worker-contract");
    contract.appendChild(element("span", "contract-label", "ASSIGNMENT"));
    const instructions = element("ol");
    assignment.instructions.forEach((instruction) => {
      const row = element("li", "", instruction);
      row.dir = "auto";
      instructions.appendChild(row);
    });
    contract.appendChild(instructions);
    card.appendChild(contract);

    const deliverable = element("div", "deliverable");
    deliverable.appendChild(element("span", "contract-label", "MUST RETURN"));
    deliverable.appendChild(element("p", "", assignment.deliverable));
    card.appendChild(deliverable);

    const meta = element("div", "assignment-meta");
    meta.appendChild(element("span", "tier", assignment.modelTier));
    meta.appendChild(element("span", "", `${formatNumber(assignment.allocation)} tokens allocated`));
    meta.appendChild(element("span", "", `depends on: ${assignment.dependencies.join(" + ") || "queen"}`));
    card.appendChild(meta);
    grid.appendChild(card);
  });
}

function renderTable(bodyId, rows, tierColumn = -1) {
  const body = document.querySelector(`#${bodyId}`);
  body.replaceChildren();
  rows.forEach((row) => {
    const tr = document.createElement("tr");
    row.forEach((cell, index) => {
      const td = document.createElement("td");
      td.textContent = typeof cell === "number" ? formatNumber(cell) : cell;
      if (index === tierColumn) td.className = "tier";
      tr.appendChild(td);
    });
    body.appendChild(tr);
  });
}

function renderResult(result, shouldScroll = true) {
  const metrics = result.metrics;
  document.querySelector("#queen-goal").textContent = result.queen.goal;
  document.querySelector("#queen-rule").textContent = result.queen.rule;
  renderConstraintList("queen-must", result.queen.must, "No explicit must constraints—Scout will identify implied requirements.");
  renderConstraintList("queen-avoid", result.queen.avoid, "No explicit avoid constraints. Define restrictions and real host permissions before execution.");
  renderConstraintList("queen-done", result.queen.doneWhen, "No explicit criteria—Architect must define verifiable acceptance evidence.");
  renderAssignments(result.assignments);
  document.querySelector("#metric-cells").textContent = metrics.cells;
  document.querySelector("#metric-waves").textContent = metrics.waves;
  document.querySelector("#metric-spendable").textContent = formatNumber(metrics.spendable);
  document.querySelector("#metric-reserve").textContent = formatNumber(metrics.reserve);
  document.querySelector("#wave-route").textContent = result.waves;
  renderTable("plan-body", result.planRows, 2);
  renderTable("variant-body", result.variantRows);
  document.querySelector("#best-prompt").textContent = result.bestPrompt;
  document.querySelector("#mission-json").textContent = JSON.stringify(result.mission, null, 2);
  document.querySelector("#payload-text").textContent = result.payloads;
  document.querySelector("#guardrail-json").textContent = JSON.stringify(result.guardrails, null, 2);
  const results = document.querySelector("#results");
  results.hidden = false;
  if (shouldScroll) results.scrollIntoView({ behavior: "smooth", block: "start" });
}

function runPlanner(shouldScroll = true) {
  invalidatePlan();
  if (!validatePlannerInput()) return false;
  if (!buildPlan) { showPlannerError("The Python engine is still loading. Wait until it is ready, then try again."); return false; }
  try {
    const serialized = buildPlan(
      value("goal"), value("must"), value("avoid"), value("done"), number("total"),
      number("reserve"), number("workers"), value("quality"), value("target"),
    );
    renderResult(JSON.parse(String(serialized)), shouldScroll);
    return true;
  } catch (cause) {
    console.error(cause);
    showPlannerError(plannerErrorMessage(cause));
    return false;
  }
}

document.querySelector("#planner-form").addEventListener("submit", (event) => {
  event.preventDefault();
  runPlanner(true);
});

document.querySelector("#planner-form").addEventListener("input", invalidatePlan);
document.querySelector("#planner-form").addEventListener("change", invalidatePlan);

document.querySelector("#try-planner").addEventListener("click", (event) => {
  event.preventDefault();
  document.querySelector("#goal").focus({ preventScroll: true });
  document.querySelector("#planner-form").scrollIntoView({ behavior: "smooth", block: "start" });
});

document.querySelector("#reserve").addEventListener("input", (event) => {
  document.querySelector("#reserve-value").textContent = `${event.target.value}%`;
});
document.querySelector("#workers").addEventListener("input", (event) => {
  document.querySelector("#workers-value").textContent = event.target.value;
});

document.querySelectorAll("[data-example]").forEach((button) => {
  button.addEventListener("click", () => {
    applyExample(EXAMPLES[button.dataset.example]);
    document.querySelector("#goal").focus();
  });
});

function applyExample(example) {
  invalidatePlan();
  Object.entries(example).forEach(([key, text]) => { document.querySelector(`#${key}`).value = text; });
}

document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((item) => item.classList.remove("active"));
    document.querySelectorAll(".tab-panel").forEach((item) => item.classList.remove("active"));
    tab.classList.add("active");
    document.querySelector(`#tab-${tab.dataset.tab}`).classList.add("active");
  });
});

document.querySelectorAll("[data-copy]").forEach((button) => {
  button.addEventListener("click", async () => {
    await navigator.clipboard.writeText(document.querySelector(`#${button.dataset.copy}`).textContent);
    const original = button.textContent;
    button.textContent = "Copied";
    setTimeout(() => { button.textContent = original; }, 1200);
  });
});

bootPython();
