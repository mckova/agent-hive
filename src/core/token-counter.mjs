import { spawn } from "node:child_process";

export function heuristicCount(text) {
  return {
    tokens: Math.max(1, Math.ceil(Buffer.byteLength(text, "utf8") / 4)),
    precision: "heuristic",
    counter: "utf8-bytes/4",
    note: "Planning estimate only; not a provider tokenizer."
  };
}

export async function openAITextCount(text, model, options = {}) {
  if (!model) throw new Error("OpenAI counting requires --model.");
  const script = [
    "import sys, tiktoken",
    "model = sys.argv[1]",
    "text = sys.stdin.read()",
    "enc = tiktoken.encoding_for_model(model)",
    "print(len(enc.encode(text)))"
  ].join("\n");
  const commands = options.python ? [options.python] : ["python3", "python"];
  const failures = [];
  for (const command of commands) {
    try {
      const stdout = await run(command, ["-c", script, model], text);
      const tokens = Number.parseInt(stdout.trim(), 10);
      if (!Number.isInteger(tokens)) throw new Error(`Unexpected tiktoken output: ${stdout}`);
      return {
        tokens,
        precision: "exact-text",
        counter: `tiktoken:${model}`,
        note: "Counts text tokens; API message framing may add tokens."
      };
    } catch (error) {
      failures.push(`${command}: ${error.message}`);
    }
  }
  throw new Error(`OpenAI tokenizer unavailable. Install Python tiktoken. ${failures.join(" | ")}`);
}

export async function anthropicMessageCount(text, model, options = {}) {
  if (!model) throw new Error("Anthropic counting requires --model.");
  const apiKey = options.apiKey || process.env.ANTHROPIC_API_KEY;
  if (!apiKey) throw new Error("Anthropic counting requires ANTHROPIC_API_KEY.");
  const fetchImpl = options.fetch || globalThis.fetch;
  const response = await fetchImpl(`${options.baseUrl || "https://api.anthropic.com"}/v1/messages/count_tokens`, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "x-api-key": apiKey,
      "anthropic-version": "2023-06-01"
    },
    body: JSON.stringify({ model, messages: [{ role: "user", content: text }] })
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`Anthropic token count failed (${response.status}): ${detail}`);
  }
  const body = await response.json();
  if (!Number.isInteger(body.input_tokens)) throw new Error("Anthropic response omitted input_tokens.");
  return {
    tokens: body.input_tokens,
    precision: "provider-estimate",
    counter: `anthropic:${model}`,
    note: "Provider count for a one-message request."
  };
}

export function createTokenCounter(options = {}) {
  const type = options.type || "heuristic";
  if (type === "heuristic") return async (text) => heuristicCount(text);
  if (type === "openai") return (text) => openAITextCount(text, options.model, options);
  if (type === "anthropic") return (text) => anthropicMessageCount(text, options.model, options);
  if (type === "auto") {
    return async (text) => {
      try {
        if (options.model?.startsWith("claude") && (options.apiKey || process.env.ANTHROPIC_API_KEY)) {
          return await anthropicMessageCount(text, options.model, options);
        }
        if (options.model) return await openAITextCount(text, options.model, options);
      } catch (error) {
        const estimate = heuristicCount(text);
        return { ...estimate, note: `Exact counter unavailable: ${error.message}` };
      }
      return heuristicCount(text);
    };
  }
  throw new Error(`Unknown counter: ${type}`);
}

function run(command, args, input) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, { windowsHide: true, stdio: ["pipe", "pipe", "pipe"] });
    let stdout = "";
    let stderr = "";
    child.stdout.setEncoding("utf8");
    child.stderr.setEncoding("utf8");
    child.stdout.on("data", (chunk) => { stdout += chunk; });
    child.stderr.on("data", (chunk) => { stderr += chunk; });
    child.on("error", reject);
    child.on("close", (code) => code === 0 ? resolve(stdout) : reject(new Error(stderr.trim() || `exit ${code}`)));
    child.stdin.end(input);
  });
}
