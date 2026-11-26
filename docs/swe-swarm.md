# Swe-swarm framework

The `ag2.extensions.swe_swarm` extension adds the swe-swarm team model to the
Python AG2 runtime. It reads existing `copilot_swarm/config/swarm-config.json`
team presets and supports architect, developer, tester, reviewer, devops,
product, and coordinator roles. Custom roles require an explicit prompt.

## Workflows

- Sequential: each specialist sees prior findings.
- Parallel: specialists work independently under one concurrency bound.
- Group: bounded round-robin rounds with accumulated findings.
- Hierarchical: first agent plans, workers run in parallel, first agent synthesizes.

Hierarchical orchestration is explicit; it does not pretend that the model
selected or delegated tasks. Each phase uses a fresh AG2 Agent with explicit
context. Results contain run IDs, UTC timestamps, role/phase labels, and text;
`SwarmResult.save()` writes a JSON transcript atomically. Invalid teams and failed
agents fail the run. Successful partial transcripts are not manufactured.

## Python usage

```python
import asyncio
from ag2.extensions.swe_swarm import GenAIDConfig, GenAIDRunner, SwarmFramework, load_preset

spec = load_preset('../copilot_swarm/config/swarm-config.json',
                   'development-team', 'Plan a change and its verification.')
runner = GenAIDRunner('../genaid', cwd='../copilot_swarm')
configs = {agent.name: GenAIDConfig(runner, 'echo') for agent in spec.agents}
result = asyncio.run(SwarmFramework(configs).run(spec))
print(result.to_dict())
```

`echo` exercises GenAID without an external model. For actual inference, use a
configured GenAID provider/model. Authentication stays in GenAID's environment;
no credentials are written into presets or transcripts by the extension.
Transcripts contain task/response content and should be stored appropriately.
Python callers can supply any native AG2 ModelConfig per agent instead.

## Installation on swe-swarm

```powershell
cd C:\Users\darbot\github_repos\ag2ai
uv venv --python 3.12 A:\.swe-swarm\environments\ag2ai-framework
uv pip install --python A:\.swe-swarm\environments\ag2ai-framework\Scripts\python.exe -e . pytest pytest-asyncio pytest-timeout
```

The companion checkout is `darbotlabs/genaid` version 1.135.0. It needs the
`fix/swe-swarm-performance-timer` branch (commit `f475028`) because the original
`measure()` implementation returns void where trace writers call a completion
callback. That defect prevents script execution. Build the CLI/API on Windows:

```powershell
cd C:\Users\darbot\github_repos\genaid
npx --yes yarn@1.22.22 install --frozen-lockfile --ignore-scripts
node node_modules/esbuild/install.js
node node_modules/tsx/node_modules/esbuild/install.js
$env:ComSpec='C:\Program Files\Git\bin\bash.exe'
$env:PATH='C:\Program Files\Git\usr\bin;'+$env:PATH
cd packages/core
node bundleprompts.js
cd ../cli
node build.mjs
node ../../node_modules/esbuild/bin/esbuild src/api.ts --outfile=built/api.mjs --platform=node --format=esm
node built/genaid.cjs --version
```

These commands build the text execution path. GenAID's optional media/browser
packages need their separate setup when those features are used. Bundling also
regenerates upstream documentation and debug categories; review those generated
changes separately from application code.

## Node and PowerShell boundary

`python -m ag2.extensions.swe_swarm` reads one JSON request from stdin and writes
one JSON response to stdout. The active Node adapter lives in
`copilot_swarm/autogen2-integration`. It has no npm framework dependency.

```json
{
  "workflow": {
    "task": "Review a small change",
    "mode": "sequential",
    "agents": [{"name": "reviewer", "role": "reviewer"}],
    "timeout_seconds": 300
  },
  "genaid_checkout": "C:/Users/darbot/github_repos/genaid",
  "model": "echo"
}
```

Optional `scripts` are trusted GenAID stages with `id`, `files`, and `options`;
they run first and their results enter workflow context. `output_directory`
persists a transcript. `smoke: true` uses deterministic AG2 TestConfig replies
and rejects script stages. The overall deadline includes script stages.

GenAID API calls use JSON stdin and argument arrays, not shell interpolation.
Timeouts and Python cancellation terminate and reap the owned Node process.
The GenAID model adapter is text-only: it rejects AG2 tools and structured-output
schemas. For AG2-native function calling use a native AG2 provider configuration;
GenAID scripts retain GenAID's own tool system. No model calls are made during
unit tests. The real integration smoke uses GenAID's local echo model.

## Validation

Focused tests cover real AG2 sequential/group/parallel/hierarchical execution,
context propagation, presets, failures, persistence, subprocess JSON boundaries,
timeouts, cancellation and the GenAID model adapter. Node tests exercise the real
Python entry point. A separate real-GenAID echo run verifies three agents across
Node -> Python AG2 -> GenAID -> Python -> Node.

The entire upstream optional-provider suite is not required by this extension;
its dependencies and live-provider credentials are separate from these checks.
