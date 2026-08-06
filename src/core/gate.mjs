import path from "node:path";

export function evaluateGate(plan, request = {}) {
  const guardrails = plan?.guardrails || {};
  const action = String(request.action || "read").trim().toLowerCase();
  const paths = (request.paths || []).map(normalizePath);
  const denied = guardrails.deniedPathPrefixes || [];
  const allowed = guardrails.allowedPathPrefixes || [];
  const pathBoundActions = new Set(["write", "delete", "external-write"]);

  if (action === "network" && guardrails.allowNetwork !== true) {
    return decision("deny", "network_disabled", action, paths);
  }
  if (pathBoundActions.has(action) && allowed.length && !paths.length) {
    return decision("deny", "path_required_for_allowlist", action, paths);
  }
  for (const candidate of paths) {
    if (candidate.startsWith("!outside:")) {
      return decision("deny", `outside_workspace:${candidate.slice(9)}`, action, paths);
    }
    if (denied.some((prefix) => withinPrefix(candidate, prefix))) {
      return decision("deny", `denied_path:${candidate}`, action, paths);
    }
    if (allowed.length && !allowed.some((prefix) => withinPrefix(candidate, prefix))) {
      return decision("deny", `outside_allowed_paths:${candidate}`, action, paths);
    }
  }
  if ((guardrails.humanApprovalActions || []).map((item) => item.toLowerCase()).includes(action)
    && request.humanApproved !== true) {
    return decision("human_required", `approval_required:${action}`, action, paths);
  }
  return decision("allow", "policy_passed", action, paths);
}

function decision(result, reason, action, paths) {
  return { result, reason, action, paths, allowed: result === "allow" };
}

function normalizePath(value) {
  const text = String(value || "").trim().replaceAll("\\", "/");
  const normalized = path.posix.normalize(text || ".").replace(/^\.\//, "");
  if (normalized === ".." || normalized.startsWith("../") || path.posix.isAbsolute(normalized) || path.win32.isAbsolute(text)) {
    return `!outside:${normalized}`;
  }
  return normalized.toLowerCase();
}

function withinPrefix(candidate, rawPrefix) {
  const prefix = normalizePath(rawPrefix).replace(/\/$/, "");
  return candidate === prefix || candidate.startsWith(`${prefix}/`) || (prefix === ".env" && candidate.startsWith(".env."));
}
