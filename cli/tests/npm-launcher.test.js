import assert from "node:assert/strict";
import { execFileSync, spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const PACKAGE = JSON.parse(readFileSync(resolve(ROOT, "package.json"), "utf8"));
const PYPROJECT = readFileSync(resolve(ROOT, "pyproject.toml"), "utf8");

test("npm and Python package versions stay synchronized", () => {
  const match = PYPROJECT.match(/^version = "([^"]+)"$/m);
  assert.ok(match, "pyproject version is missing");
  assert.equal(PACKAGE.version, match[1]);
});

test("launcher exposes the packaged CLI", () => {
  const output = execFileSync(
    process.execPath,
    [resolve(ROOT, "bin", "higantic.js"), "--version"],
    { encoding: "utf8" },
  );
  assert.equal(output.trim(), `HiGantic CLI ${PACKAGE.version}`);
});

test("launcher exposes the setup onboarding command", () => {
  const output = execFileSync(
    process.execPath,
    [resolve(ROOT, "bin", "higantic.js"), "setup", "--help"],
    { cwd: ROOT, encoding: "utf8" },
  );
  assert.match(output, /Confirm that the HiGantic CLI is ready/);
  assert.match(output, /--yes/);
});

test("launcher preserves CLI exit codes", () => {
  const result = spawnSync(
    process.execPath,
    [resolve(ROOT, "bin", "higantic.js"), "not-a-command"],
    { encoding: "utf8" },
  );
  assert.equal(result.status, 2);
  assert.match(result.stderr, /Command not recognized/);
});

test("launcher explains the Python requirement", () => {
  const result = spawnSync(
    process.execPath,
    [resolve(ROOT, "bin", "higantic.js"), "--version"],
    { encoding: "utf8", env: { ...process.env, PATH: "" } },
  );
  assert.equal(result.status, 1);
  assert.match(result.stderr, /requires Python 3\.9 or newer/);
});
