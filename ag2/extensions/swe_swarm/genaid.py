# SPDX-License-Identifier: Apache-2.0
"""GenAID's supported JavaScript API, isolated behind a JSON subprocess boundary."""

import asyncio
import json
import os
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Self

from ag2.config import ModelConfig, ModelProvider
from ag2.context import ConversationContext
from ag2.events import BaseEvent, ModelMessage, ModelResponse


@dataclass(frozen=True, slots=True)
class GenAIDRunner:
    checkout: str | os.PathLike[str]
    node: str = "node"
    timeout_seconds: float = 300
    cwd: str | os.PathLike[str] | None = None

    async def run_script(
        self, script: str, files: Sequence[str] = (), options: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        root = Path(self.checkout).resolve()
        api = root / "packages" / "cli" / "built" / "api.mjs"
        cli = api.with_name("genaid.cjs")
        if not api.is_file() or not cli.is_file():
            raise FileNotFoundError(f"Build GenAID first: missing {api} or {cli}")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        bridge = Path(__file__).with_name("genaid-api.mjs")
        request = json.dumps({"api": api.as_uri(), "script": script, "files": list(files), "options": options or {}})
        process = await asyncio.create_subprocess_exec(
            self.node,
            str(bridge),
            cwd=str(self.cwd) if self.cwd is not None else None,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            async with asyncio.timeout(self.timeout_seconds):
                stdout, stderr = await process.communicate(request.encode("utf-8"))
        except (TimeoutError, asyncio.CancelledError):
            if process.returncode is None:
                process.kill()
            await process.communicate()
            raise
        if process.returncode:
            detail = stderr.decode("utf-8", errors="replace")[-4000:]
            raise RuntimeError(f"GenAID exited with code {process.returncode}: {detail}")
        frames = [
            line.removeprefix("SWE_SWARM_RESULT:")
            for line in stdout.decode("utf-8").splitlines()
            if line.startswith("SWE_SWARM_RESULT:")
        ]
        if len(frames) != 1:
            raise RuntimeError("GenAID returned an invalid response frame")
        result = json.loads(frames[0])
        if not isinstance(result, dict) or result.get("error") or result.get("status") in {"error", "cancelled"}:
            raise RuntimeError(
                f"GenAID run failed: {result.get('statusText', 'invalid response') if isinstance(result, dict) else 'invalid response'}"
            )
        return result


@dataclass(frozen=True, slots=True)
class GenAIDConfig(ModelConfig):
    """Text-only AG2 model adapter; GenAID resolves the selected provider/model.

    AG2 function calling and structured responses are deliberately rejected;
    GenAID scripts can use their own tools. Use a native AG2 provider config
    for workflows that need AG2-native tool calling.
    """

    runner: GenAIDRunner
    model: str

    @property
    def provider(self) -> ModelProvider:
        # GenAID can route to multiple providers; do not mislabel it as one.
        raise NotImplementedError

    def copy(self) -> Self:
        return replace(self)

    def create(self) -> "GenAIDClient":
        return GenAIDClient(self.runner, self.model)


@dataclass(frozen=True, slots=True)
class GenAIDClient:
    runner: GenAIDRunner
    model: str

    async def __call__(
        self, messages: Sequence[BaseEvent], context: ConversationContext, **kwargs: Any
    ) -> ModelResponse:
        if kwargs.get("tools") or kwargs.get("response_schema"):
            raise ValueError("GenAIDConfig supports text responses; use a native AG2 config for AG2 tools/schemas")
        prompt = json.dumps({
            "instructions": list(context.prompt),
            "messages": [message.to_dict() for message in messages],
        })
        script = Path(__file__).with_name("prompt.genai.mjs")
        result = await self.runner.run_script(str(script), options={"model": self.model, "vars": {"request": prompt}})
        text = result.get("text")
        if not isinstance(text, str):
            raise RuntimeError("GenAID response has no text")
        message = ModelMessage(text)
        await context.send(message)
        return ModelResponse(message)
