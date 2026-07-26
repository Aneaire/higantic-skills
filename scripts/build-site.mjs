#!/usr/bin/env node

import { createHash } from "node:crypto";
import { lstat, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import {
  MAX_MANIFEST_BYTES,
  MAX_REFERENCE_BYTES,
  PUBLIC_ORIGIN,
  parseJsonWithDuplicateCheck,
  validateReference,
  validateSourceManifest,
} from "./live-reference-schema.mjs";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const DEFAULT_SITE_DIR = path.join(ROOT, "site");
const DEFAULT_DIST_DIR = path.join(ROOT, "dist");

function fail(message) {
  throw new Error(message);
}

export function assertBoundedSize(bytes, maximum, label) {
  if (bytes.length > maximum) fail(`${label} exceeds ${maximum} bytes`);
}

async function assertRegularFileWithoutSymlinks(base, relativePath, label) {
  const baseStat = await lstat(base).catch((error) => {
    fail(`${label} base is missing: ${error.message}`);
  });
  if (baseStat.isSymbolicLink() || !baseStat.isDirectory()) fail(`${label} base must be a real directory, not a symlink`);
  let current = base;
  for (const segment of relativePath.split("/")) {
    current = path.join(current, segment);
    const stat = await lstat(current).catch((error) => {
      fail(`${label} is missing: ${error.message}`);
    });
    if (stat.isSymbolicLink()) fail(`${label} must not contain symlinks`);
  }
  const stat = await lstat(current);
  if (!stat.isFile()) fail(`${label} must be a regular file`);
  return current;
}

async function loadSources(siteDir) {
  const sourceManifestPath = await assertRegularFileWithoutSymlinks(siteDir, "v1/manifest.source.json", "source manifest");
  const sourceManifestBytes = await readFile(sourceManifestPath);
  assertBoundedSize(sourceManifestBytes, MAX_MANIFEST_BYTES, "source manifest");
  const manifest = validateSourceManifest(parseJsonWithDuplicateCheck(sourceManifestBytes, "source manifest"));

  const references = [];
  for (const entry of manifest.references) {
    const sourcePath = await assertRegularFileWithoutSymlinks(path.join(siteDir, "v1"), entry.path, `reference ${entry.slug}`);
    const bytes = await readFile(sourcePath);
    assertBoundedSize(bytes, MAX_REFERENCE_BYTES, `source reference ${entry.slug}`);
    const data = validateReference(parseJsonWithDuplicateCheck(bytes, `source reference ${entry.slug}`), entry.slug, `source reference ${entry.slug}`);
    references.push({ ...entry, sourcePath, bytes, data });
  }
  return { manifest, sourceManifestBytes, references };
}

async function prepareDist(distDir) {
  const existing = await lstat(distDir).catch((error) => {
    if (error.code === "ENOENT") return null;
    throw error;
  });
  if (existing?.isSymbolicLink()) fail("dist must not be a symlink");
  await rm(distDir, { recursive: true, force: true });
  await mkdir(path.join(distDir, "v1", "references"), { recursive: true });
}

export async function buildSite({ siteDir = DEFAULT_SITE_DIR, distDir = DEFAULT_DIST_DIR } = {}) {
  const source = await loadSources(siteDir);
  const indexPath = await assertRegularFileWithoutSymlinks(siteDir, "index.html", "site index");
  const generatedReferences = source.references.map((reference) => ({
    slug: reference.slug,
    referenceUrl: `${PUBLIC_ORIGIN}/v1/references/${reference.slug}.json`,
    sha256: createHash("sha256").update(reference.bytes).digest("hex"),
    minimumInstalledVersion: reference.minimumInstalledVersion,
  }));
  const generatedManifest = {
    schemaVersion: source.manifest.schemaVersion,
    updatedAt: source.manifest.updatedAt,
    references: generatedReferences,
  };
  const generatedManifestBytes = Buffer.from(`${JSON.stringify(generatedManifest, null, 2)}\n`, "utf8");
  assertBoundedSize(generatedManifestBytes, MAX_MANIFEST_BYTES, "generated manifest");

  await prepareDist(distDir);
  await writeFile(path.join(distDir, "index.html"), await readFile(indexPath));
  for (const reference of source.references) {
    assertBoundedSize(reference.bytes, MAX_REFERENCE_BYTES, `generated reference ${reference.slug}`);
    const destination = path.join(distDir, "v1", "references", `${reference.slug}.json`);
    await writeFile(destination, reference.bytes);
  }
  await writeFile(path.join(distDir, "v1", "manifest.json"), generatedManifestBytes);
}

if (process.argv[1] && pathToFileURL(path.resolve(process.argv[1])).href === import.meta.url) {
  buildSite().catch((error) => {
    console.error(`Build failed: ${error.message}`);
    process.exitCode = 1;
  });
}
