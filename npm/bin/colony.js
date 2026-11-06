#!/usr/bin/env node
// Puffin Colony is a Python tool: this runs it with `uvx puffin-colony`, or with `python3 -m colony` when uv is
// missing and the package is installed. Plain Node, no packages.
"use strict";

const { spawnSync } = require("child_process");

const args = process.argv.slice(2);

function run(command, argv) {
  const result = spawnSync(command, argv, { stdio: "inherit" });
  if (result.error && result.error.code === "ENOENT") return null; // not on PATH: try the next way
  if (result.error) throw result.error;
  if (result.signal) process.kill(process.pid, result.signal);
  return result.status === null ? 1 : result.status;
}

let status = run("uvx", ["puffin-colony", ...args]);
if (status === null) {
  const found = spawnSync("python3", ["-c", "import colony.cli"], { stdio: "ignore" });
  if (!found.error && found.status === 0) status = run("python3", ["-m", "colony", ...args]);
}
if (status === null) {
  console.error("colony: needs uv, install it with `curl -LsSf https://astral.sh/uv/install.sh | sh` " +
                "(see https://docs.astral.sh/uv/) and run this again");
  status = 127;
}
process.exit(status);
