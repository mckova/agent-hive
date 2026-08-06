from __future__ import annotations

from agent_hive.mission import default_mission


def two_cell_mission():
    mission = default_mission()
    mission["budget"] = {"unit": "tokens", "total": 10000, "reservePercent": 20}
    mission["policy"] = {"maxWorkers": 1, "qualityFloor": "economy"}
    mission["cells"] = [
        {"id": "build", "title": "Build the artifact", "role": "builder", "priority": 5, "complexity": 3,
         "risk": 3, "dependencies": [], "required": True, "actions": ["write"], "paths": ["src"]},
        {"id": "verify", "title": "Verify the artifact", "role": "guard", "priority": 5, "complexity": 2,
         "risk": 5, "dependencies": ["build"], "required": True, "actions": ["read"], "paths": ["src"]},
    ]
    return mission


def metric(input_tokens, output_tokens):
    return {"modelCalls": 1, "inputTokens": input_tokens, "cachedInputTokens": 0, "outputTokens": output_tokens,
            "reasoningTokens": 0, "latencyMs": 10, "costUsd": 0}


class FakeIO:
    def __init__(self):
        self.output = []

    def log(self, value):
        self.output.append(str(value))

    def table(self, value):
        self.output.append(value)
