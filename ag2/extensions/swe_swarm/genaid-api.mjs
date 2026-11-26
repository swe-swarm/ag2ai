// SPDX-License-Identifier: Apache-2.0
// One request per process; no command interpolation or shell execution.
let input = "";
for await (const chunk of process.stdin) input += chunk;
try {
    const request = JSON.parse(input);
    const { run } = await import(request.api);
    const result = await run(request.script, request.files, request.options);
    process.stdout.write("SWE_SWARM_RESULT:" + JSON.stringify(result) + "\n");
} catch (error) {
    process.stderr.write(String(error?.stack || error) + "\n");
    process.exitCode = 1;
}
