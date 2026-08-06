from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

from hidden_cases import run_hidden_cases


def grade(target: Path) -> dict:
    public = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "checks", "-v"],
                            cwd=target, capture_output=True, text=True)
    try:
        hidden = run_hidden_cases(target)
    except Exception as error:
        hidden = [{"name": "implementation loads", "category": "functional", "passed": False, "error": str(error)}]
    source_path = target / "src" / "rate_limiter.py"
    source = source_path.read_text(encoding="utf-8") if source_path.exists() else ""
    functional = [item for item in hidden if item["category"] == "functional"]
    security = [item for item in hidden if item["category"] == "security"]
    functional_score = 20 * sum(item["passed"] for item in functional) / len(functional) if functional else 0
    security_score = 10 * sum(item["passed"] for item in security) / len(security) if security else 0
    scope_checks = {"dependencyFree": not re.search(r"^(from|import)\s+(?!collections|math|typing|dataclasses\b)", source, re.M),
                    "usesOrderedDict": "OrderedDict" in source, "noTimers": not re.search(r"Timer|sleep|threading", source),
                    "boundedSize": "max_keys" in source, "readable": len(source.splitlines()) <= 180 and len(source) >= 200}
    public_score = 5 if public.returncode == 0 else 0
    scope_score = sum(scope_checks.values())
    return {"target": str(target), "artifactScore": round(public_score + functional_score + security_score + scope_score, 2),
            "maxArtifactScore": 40, "public": {"passed": public.returncode == 0, "score": public_score,
            "output": (public.stdout + "\n" + public.stderr).strip()}, "hidden": hidden,
            "scores": {"hiddenFunctional": round(functional_score, 2), "hiddenSecurity": round(security_score, 2), "scope": scope_score},
            "scopeChecks": scope_checks, "sourceLines": len(source.splitlines())}


def main(argv=None):
    arguments = sys.argv[1:] if argv is None else argv
    if not arguments: raise SystemExit("Usage: python grade.py <arm-directory>")
    print(json.dumps(grade(Path(arguments[0]).resolve()), indent=2))


if __name__ == "__main__": main()
