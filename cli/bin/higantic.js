#!/usr/bin/env node

import { delimiter, dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";

const MINIMUM_PYTHON = [3, 9];
const VERSION_CHECK = [
  "import sys",
  `raise SystemExit(0 if sys.version_info >= (${MINIMUM_PYTHON.join(", ")}) else 1)`,
].join("; ");

function pythonCandidates() {
  return process.platform === "win32"
    ? [
        { command: "py", prefix: ["-3"] },
        { command: "python", prefix: [] },
        { command: "python3", prefix: [] },
      ]
    : [
        { command: "python3", prefix: [] },
        { command: "python", prefix: [] },
      ];
}

function findPython() {
  for (const candidate of pythonCandidates()) {
    const checked = spawnSync(
      candidate.command,
      [...candidate.prefix, "-c", VERSION_CHECK],
      { stdio: "ignore" },
    );
    if (!checked.error && checked.status === 0) return candidate;
  }
  return null;
}

const python = findPython();
if (!python) {
  console.error(
    "HiGantic CLI requires Python 3.9 or newer. Install Python, then run this command again.",
  );
  process.exit(1);
}

const packageRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const existingPythonPath = process.env.PYTHONPATH;
const environment = {
  ...process.env,
  PYTHONPATH: existingPythonPath
    ? `${packageRoot}${delimiter}${existingPythonPath}`
    : packageRoot,
};
const result = spawnSync(
  python.command,
  [...python.prefix, "-m", "higantic_cli", ...process.argv.slice(2)],
  { env: environment, stdio: "inherit" },
);

if (result.error) {
  console.error(`Could not start HiGantic CLI: ${result.error.message}`);
  process.exit(1);
}
if (result.signal) {
  process.kill(process.pid, result.signal);
}
process.exit(result.status ?? 1);
