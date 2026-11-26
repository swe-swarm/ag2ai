# SPDX-License-Identifier: Apache-2.0
import asyncio
import json
import shutil

import pytest

from ag2.extensions.swe_swarm import AgentSpec, GenAIDConfig, GenAIDRunner, SwarmFramework, WorkflowSpec, load_preset
from ag2.testing import TestConfig, TrackingConfig


def workflow(mode="sequential", **kwargs):
    return WorkflowSpec(
        task="Review a change",
        agents=[AgentSpec(name="architect", role="architect"), AgentSpec(name="tester", role="tester")],
        mode=mode,
        **kwargs,
    )


@pytest.mark.asyncio
async def test_sequential_passes_evidence_and_persists_transcript(tmp_path):
    second = TrackingConfig(TestConfig("Test plan"))
    result = await SwarmFramework({"architect": TestConfig("Architecture evidence"), "tester": second}).run(workflow())
    assert [m.content for m in result.messages] == ["Architecture evidence", "Test plan"]
    assert "Architecture evidence" in json.dumps([message.to_dict() for message in second.calls[0].messages])
    assert json.loads(result.save(tmp_path).read_text())["run_id"] == result.run_id


@pytest.mark.asyncio
@pytest.mark.parametrize("mode,count", [("parallel", 2), ("group", 4), ("hierarchical", 3)])
async def test_modes_use_real_ag2_agents(mode, count):
    result = await SwarmFramework({"architect": TestConfig("design"), "tester": TestConfig("tests")}).run(
        workflow(mode, rounds=2)
    )
    assert len(result.messages) == count
    if mode == "hierarchical":
        assert [m.phase for m in result.messages] == ["plan", "work", "synthesis"]


@pytest.mark.asyncio
async def test_invalid_team_fails_before_model_calls():
    config = TrackingConfig(TestConfig("unused"))
    framework = SwarmFramework({"architect": config})
    with pytest.raises(ValueError, match="Missing model"):
        await framework.run(workflow())
    duplicate = WorkflowSpec(task="test", agents=[AgentSpec(name="architect"), AgentSpec(name="architect")])
    with pytest.raises(ValueError, match="unique"):
        await framework.run(duplicate)
    assert not config.calls


@pytest.mark.asyncio
async def test_agent_failure_is_not_a_successful_transcript():
    with pytest.RaisesGroup(RuntimeError):
        await SwarmFramework({
            "architect": TestConfig(RuntimeError("model failed")),
            "tester": TestConfig("tests"),
        }).run(workflow("parallel"))


def test_existing_swarm_presets(tmp_path):
    config = tmp_path / "swarm.json"
    config.write_text(
        json.dumps({"roles": {"maxConcurrent": 3, "presets": {"review-team": ["developer", "reviewer", "tester"]}}})
    )
    spec = load_preset(config, "review-team", "Review")
    assert [agent.name for agent in spec.agents] == ["developer", "reviewer", "tester"]
    assert spec.max_concurrent == 3


@pytest.fixture
def node_checkout(tmp_path):
    if not shutil.which("node"):
        pytest.skip("Node is required for subprocess contract tests")
    built = tmp_path / "packages" / "cli" / "built"
    built.mkdir(parents=True)
    (built / "genaid.cjs").write_text("// subprocess fixture, not the GenAID runtime")
    (built / "api.mjs").write_text(
        'export async function run(script, files, options) { if (script === "sleep") await new Promise(r => setTimeout(r, 30000)); if (script === "fail") throw new Error("script failed"); return { text: JSON.stringify({script, files, options}) }; }'
    )
    return tmp_path


@pytest.mark.asyncio
async def test_genaid_subprocess_preserves_json_arguments(node_checkout):
    runner = GenAIDRunner(node_checkout)
    result = await runner.run_script("file with spaces.genai.mjs", ["a;echo not-a-command"], {"vars": {"quote": 'a"b'}})
    assert json.loads(result["text"]) == {
        "script": "file with spaces.genai.mjs",
        "files": ["a;echo not-a-command"],
        "options": {"vars": {"quote": 'a"b'}},
    }


@pytest.mark.asyncio
async def test_genaid_timeout_failure_and_cancellation(node_checkout):
    with pytest.raises(TimeoutError):
        await GenAIDRunner(node_checkout, timeout_seconds=0.1).run_script("sleep")
    with pytest.raises(RuntimeError, match="script failed"):
        await GenAIDRunner(node_checkout).run_script("fail")
    task = asyncio.create_task(GenAIDRunner(node_checkout).run_script("sleep"))
    await asyncio.sleep(0.1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_missing_genaid_build_is_actionable(tmp_path):
    with pytest.raises(FileNotFoundError, match="Build GenAID first"):
        await GenAIDRunner(tmp_path).run_script("example")


def test_genaid_config_can_be_copied(node_checkout):
    config = GenAIDConfig(GenAIDRunner(node_checkout), "echo")
    assert config.copy().model == "echo"


@pytest.mark.asyncio
async def test_genaid_adapter_runs_inside_ag2(node_checkout):
    framework = SwarmFramework({
        name: GenAIDConfig(GenAIDRunner(node_checkout), "echo") for name in ("architect", "tester")
    })
    result = await framework.run(workflow())
    assert len(result.messages) == 2
    assert "Review a change" in result.messages[0].content
