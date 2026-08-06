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
  } catch (error) {
    console.error(error);
    status.textContent = "Python engine could not load. Refresh to retry.";
    dot.classList.add("error");
    document.querySelector("#form-error").textContent = "The browser could not load Pyodide from its CDN.";
  }
}

function value(id) { return document.querySelector(`#${id}`).value; }
function number(id) { return Number(value(id)); }
function formatNumber(value) { return new Intl.NumberFormat().format(value); }

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

function renderResult(result) {
  const metrics = result.metrics;
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
  results.scrollIntoView({ behavior: "smooth", block: "start" });
}

document.querySelector("#planner-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const error = document.querySelector("#form-error");
  error.textContent = "";
  if (!buildPlan) { error.textContent = "The Python engine is still loading."; return; }
  try {
    const serialized = buildPlan(
      value("goal"), value("must"), value("avoid"), value("done"), number("total"),
      number("reserve"), number("workers"), value("quality"), value("target"),
    );
    renderResult(JSON.parse(String(serialized)));
  } catch (cause) {
    console.error(cause);
    error.textContent = String(cause).replace(/^PythonError:\s*/, "").split("\n").at(-1);
  }
});

document.querySelector("#reserve").addEventListener("input", (event) => {
  document.querySelector("#reserve-value").textContent = `${event.target.value}%`;
});
document.querySelector("#workers").addEventListener("input", (event) => {
  document.querySelector("#workers-value").textContent = event.target.value;
});

document.querySelectorAll("[data-example]").forEach((button) => {
  button.addEventListener("click", () => {
    const example = EXAMPLES[button.dataset.example];
    Object.entries(example).forEach(([key, text]) => { document.querySelector(`#${key}`).value = text; });
    document.querySelector("#goal").focus();
  });
});

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
