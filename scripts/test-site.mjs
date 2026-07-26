#!/usr/bin/env node

import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { lstat, mkdtemp, mkdir, readFile, readdir, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { buildSite } from "./build-site.mjs";
import {
  MAX_MANIFEST_BYTES,
  MAX_REFERENCE_BYTES,
  parseJsonWithDuplicateCheck,
  validateGeneratedManifest,
  validateReference,
} from "./live-reference-schema.mjs";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const DIST = path.join(ROOT, "dist");
const SITE = path.join(ROOT, "site");
const SOURCE_MANIFEST = path.join(SITE, "v1", "manifest.source.json");

function sha256(bytes) {
  return createHash("sha256").update(bytes).digest("hex");
}

async function snapshot(directory, prefix = "") {
  const result = {};
  for (const name of (await readdir(directory)).sort()) {
    const fullPath = path.join(directory, name);
    const relativePath = path.posix.join(prefix, name);
    const stat = await lstat(fullPath);
    assert.equal(stat.isSymbolicLink(), false, `${relativePath} must not be a symlink`);
    if (stat.isDirectory()) Object.assign(result, await snapshot(fullPath, relativePath));
    else {
      assert.equal(stat.isFile(), true, `${relativePath} must be a regular file`);
      result[relativePath] = sha256(await readFile(fullPath));
    }
  }
  return result;
}

async function writeFixtureSite(directory, manifestBytes, referenceBytes) {
  await mkdir(path.join(directory, "v1", "references"), { recursive: true });
  await writeFile(path.join(directory, "index.html"), "<!doctype html><title>Fixture</title>\n");
  await writeFile(path.join(directory, "v1", "manifest.source.json"), manifestBytes);
  await writeFile(path.join(directory, "v1", "references", "higantic-html-artifacts.json"), referenceBytes);
}

const sourceBefore = await readFile(SOURCE_MANIFEST);
await buildSite();
const first = await snapshot(DIST);
await buildSite();
const second = await snapshot(DIST);
assert.deepEqual(second, first, "two builds must produce byte-identical files");
assert.deepEqual(await readFile(SOURCE_MANIFEST), sourceBefore, "the source manifest must not be modified");

const manifestBytes = await readFile(path.join(DIST, "v1", "manifest.json"));
assert.ok(manifestBytes.length <= MAX_MANIFEST_BYTES, "generated manifest must fit the client limit");
const manifest = validateGeneratedManifest(parseJsonWithDuplicateCheck(manifestBytes, "generated manifest"));
const source = JSON.parse(sourceBefore.toString("utf8"));
assert.equal(manifest.updatedAt, source.updatedAt);
assert.equal(manifest.references.length, source.references.length);
for (const reference of manifest.references) {
  const sourceEntry = source.references.find((candidate) => candidate.slug === reference.slug);
  assert.ok(sourceEntry, `generated reference ${reference.slug} must exist in the source manifest`);
  assert.equal(reference.referenceUrl, `https://skills.higantic.com/v1/references/${reference.slug}.json`);
  assert.equal(reference.minimumInstalledVersion, sourceEntry.minimumInstalledVersion);
  const generatedBytes = await readFile(path.join(DIST, "v1", "references", `${reference.slug}.json`));
  assert.ok(generatedBytes.length <= MAX_REFERENCE_BYTES, "generated reference must fit the client limit");
  assert.equal(reference.sha256, sha256(generatedBytes));
  validateReference(parseJsonWithDuplicateCheck(generatedBytes, `reference ${reference.slug}`), reference.slug);
}

const temporaryRoot = await mkdtemp(path.join(os.tmpdir(), "higantic-live-reference-"));
try {
  const validReference = await readFile(path.join(SITE, "v1", "references", "higantic-html-artifacts.json"));
  const oversizedManifestSite = path.join(temporaryRoot, "oversized-manifest-site");
  const oversizedManifest = Buffer.concat([sourceBefore, Buffer.alloc(MAX_MANIFEST_BYTES + 1, 0x20)]);
  await writeFixtureSite(oversizedManifestSite, oversizedManifest, validReference);
  await assert.rejects(
    buildSite({ siteDir: oversizedManifestSite, distDir: path.join(temporaryRoot, "oversized-manifest-dist") }),
    /source manifest exceeds 65536 bytes/,
  );

  const oversizedReferenceSite = path.join(temporaryRoot, "oversized-reference-site");
  const oversizedReference = Buffer.concat([validReference, Buffer.alloc(MAX_REFERENCE_BYTES + 1, 0x20)]);
  await writeFixtureSite(oversizedReferenceSite, sourceBefore, oversizedReference);
  await assert.rejects(
    buildSite({ siteDir: oversizedReferenceSite, distDir: path.join(temporaryRoot, "oversized-reference-dist") }),
    /source reference higantic-html-artifacts exceeds 65536 bytes/,
  );
} finally {
  await rm(temporaryRoot, { recursive: true, force: true });
}

console.log("Site build checks passed.");
