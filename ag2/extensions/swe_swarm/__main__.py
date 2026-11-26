# SPDX-License-Identifier: Apache-2.0
"""JSON stdin/stdout entry point shared by Node and PowerShell launchers."""

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from ag2.config import ModelConfig
from ag2.testing import TestConfig

from .framework import SwarmFramework, WorkflowSpec
from .genaid import GenAIDConfig, GenAIDRunner


async def execute(request: dict[str, Any]) -> dict[str, Any]:
    spec = WorkflowSpec.model_validate(request["workflow"])
    async with asyncio.timeout(spec.timeout_seconds):
        return await execute_workflow(request, spec)


async def execute_workflow(request: dict[str, Any], spec: WorkflowSpec) -> dict[str, Any]:
    configs: dict[str, ModelConfig]
    scripts = request.get("scripts", [])
    script_results = []
    if request.get("smoke", False) and scripts:
        raise ValueError("Smoke mode does not execute GenAID scripts")
    if request.get("smoke", False):
        configs = {agent.name: TestConfig(f"{agent.role}: offline AG2 smoke reply") for agent in spec.agents}
    else:
        model = request.get("model")
        if not isinstance(model, str) or not model.strip():
            raise ValueError("A GenAID model is required for live runs")
        runner = GenAIDRunner(request["genaid_checkout"], timeout_seconds=spec.timeout_seconds, cwd=request.get("cwd"))
        configs = {agent.name: GenAIDConfig(runner, model) for agent in spec.agents}
    if scripts:
        for stage in scripts:
            if not isinstance(stage, dict) or set(stage) - {"id", "files", "options"} or not stage.get("id"):
                raise ValueError("Script stages require id and optional files/options")
            script_results.append(
                await runner.run_script(stage["id"], stage.get("files", []), stage.get("options", {}))
            )
        spec = spec.model_copy(update={"task": spec.task + "\n\nGenAID stage results:\n" + json.dumps(script_results)})
    result = await SwarmFramework(configs).run(spec)
    response = result.to_dict()
    response["genai_results"] = script_results
    response["backend"] = "ag2-test-config" if request.get("smoke", False) else "genaid"
    if output := request.get("output_directory"):
        response["transcript_path"] = str(result.save(Path(output)))
    return response


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    try:
        response = asyncio.run(execute(json.load(sys.stdin)))
    except Exception as exc:
        print(json.dumps({"error": str(exc), "type": type(exc).__name__}), file=sys.stderr)
        return 1
    print(json.dumps(response))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
