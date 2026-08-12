export const MAX_MANIFEST_BYTES = 64 * 1024;
export const MAX_REFERENCE_BYTES = 64 * 1024;
export const PUBLIC_ORIGIN = "https://skills.higantic.com";
export const MANIFEST_URL = `${PUBLIC_ORIGIN}/v1/manifest.json`;

export const CAPABILITY_IDS = Object.freeze([
  "html-pages",
  "html-artifacts",
  "html-revisions",
  "managed-assets",
  "private-artifact-urls",
  "stable-public-visibility",
  "capability-shares",
]);
export const COMMAND_IDS = Object.freeze([
  "pages.list",
  "pages.create",
  "assets.list",
  "assets.show",
  "assets.upload",
  "assets.delete",
  "assets.targets",
  "assets.make_public",
  "assets.make_private",
  "artifacts.list",
  "artifacts.create",
  "artifacts.lookup",
  "artifacts.upsert",
  "artifacts.get",
  "artifacts.update",
  "artifacts.delete",
  "revisions.list",
  "revisions.get",
  "revisions.append",
  "revisions.restore",
  "visibility.get",
  "visibility.set",
  "shares.list",
  "shares.create",
  "shares.revoke",
  "shares.rotate",
  "url.get",
]);
export const SCOPE_IDS = Object.freeze([
  "html_artifacts:read",
  "html_artifacts:write",
  "html_artifacts:share",
  "html_assets:read",
  "html_assets:write",
  "html_assets:share",
  "html_pages:create",
]);
export const FEATURE_KEYS = Object.freeze([
  "staticHtmlOnly",
  "optimisticConcurrencyRequired",
  "managedAssetReferencesRequired",
  "stablePublicVisibilitySupported",
  "capabilitySharingSupported",
  "capabilityUrlRecoverable",
  "htmlPageDeletionSupported",
  "remoteAssetImportSupported",
]);
export const LIMIT_KEYS = Object.freeze([
  "artifactSourceBytes",
  "assetUploadBytes",
  "revisionsPerArtifact",
  "requestsPerMinutePerKey",
  "writesPerMinutePerKey",
]);
const EXCALIDRAW_CAPABILITY_IDS = Object.freeze([
  "canvas-pages",
  "canvas-scenes",
  "canvas-sharing",
  "semantic-flowcharts",
]);
const EXCALIDRAW_COMMAND_IDS = Object.freeze([
  "pages.list",
  "pages.create",
  "scenes.list",
  "scenes.get",
  "scenes.create",
  "scenes.replace",
  "scenes.delete",
  "visibility.get",
  "visibility.set",
]);
const EXCALIDRAW_SCOPE_IDS = Object.freeze([
  "excalidraw:read",
  "excalidraw:write",
  "excalidraw:share",
  "excalidraw_pages:create",
]);
const EXCALIDRAW_FEATURE_KEYS = Object.freeze([
  "semanticLayoutSupported",
  "optimisticConcurrencyRequired",
  "rawSceneSupported",
  "canvasPageDeletionSupported",
]);
const EXCALIDRAW_LIMIT_KEYS = Object.freeze([
  "sceneSourceBytes",
  "nodesPerFlowchart",
  "edgesPerFlowchart",
  "requestsPerMinutePerKey",
  "writesPerMinutePerKey",
]);

const SLUG_PATTERN = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
const SEMVER_PATTERN = /^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$/;
const SHA256_PATTERN = /^[a-f0-9]{64}$/;
const TIMESTAMP_PATTERN = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/;

function fail(label, message) {
  throw new Error(`${label}: ${message}`);
}

export function parseJsonWithDuplicateCheck(bytes, label) {
  let text;
  try {
    text = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
  } catch (error) {
    fail(label, `not valid UTF-8 (${error.message})`);
  }
  let index = 0;

  function whitespace() {
    while (index < text.length && /[\x20\t\r\n]/.test(text[index])) index += 1;
  }

  function string() {
    const start = index;
    index += 1;
    while (index < text.length) {
      const code = text.charCodeAt(index);
      if (code < 0x20) fail(label, "control character in JSON string");
      if (text[index] === '"') {
        index += 1;
        try {
          return JSON.parse(text.slice(start, index));
        } catch (error) {
          fail(label, `invalid JSON string (${error.message})`);
        }
      }
      if (text[index] === "\\") {
        index += 1;
        if (index >= text.length || !/["\\/bfnrtu]/.test(text[index])) fail(label, "invalid JSON escape");
        if (text[index] === "u") {
          if (!/^[0-9a-fA-F]{4}$/.test(text.slice(index + 1, index + 5))) fail(label, "invalid Unicode escape");
          index += 4;
        }
      }
      index += 1;
    }
    fail(label, "unterminated JSON string");
  }

  function number() {
    const match = text.slice(index).match(/^-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?/);
    if (!match) fail(label, "invalid JSON number");
    index += match[0].length;
    const value = Number(match[0]);
    if (!Number.isFinite(value)) fail(label, "non-finite JSON number");
    return value;
  }

  function array() {
    const result = [];
    index += 1;
    whitespace();
    if (text[index] === "]") {
      index += 1;
      return result;
    }
    while (true) {
      result.push(value());
      whitespace();
      if (text[index] === "]") {
        index += 1;
        return result;
      }
      if (text[index] !== ",") fail(label, "expected comma in array");
      index += 1;
      whitespace();
    }
  }

  function object() {
    const result = {};
    const keys = new Set();
    index += 1;
    whitespace();
    if (text[index] === "}") {
      index += 1;
      return result;
    }
    while (true) {
      if (text[index] !== '"') fail(label, "object key must be a string");
      const key = string();
      if (keys.has(key)) fail(label, `duplicate key ${JSON.stringify(key)}`);
      keys.add(key);
      whitespace();
      if (text[index] !== ":") fail(label, "expected colon after object key");
      index += 1;
      whitespace();
      result[key] = value();
      whitespace();
      if (text[index] === "}") {
        index += 1;
        return result;
      }
      if (text[index] !== ",") fail(label, "expected comma in object");
      index += 1;
      whitespace();
    }
  }

  function value() {
    whitespace();
    const character = text[index];
    if (character === '"') return string();
    if (character === "{") return object();
    if (character === "[") return array();
    if (text.startsWith("true", index)) {
      index += 4;
      return true;
    }
    if (text.startsWith("false", index)) {
      index += 5;
      return false;
    }
    if (text.startsWith("null", index)) {
      index += 4;
      return null;
    }
    if (character === "-" || /\d/.test(character || "")) return number();
    fail(label, "invalid JSON value");
  }

  const result = value();
  whitespace();
  if (index !== text.length) fail(label, "trailing data after JSON value");
  return result;
}

function exactObject(value, keys, label) {
  if (!value || typeof value !== "object" || Array.isArray(value)) fail(label, "must be an object");
  const actual = Object.keys(value).sort();
  const expected = [...keys].sort();
  if (actual.length !== expected.length || actual.some((key, i) => key !== expected[i])) {
    fail(label, `must contain exactly ${expected.join(", ")}`);
  }
}

function asciiString(value, pattern, label) {
  if (typeof value !== "string" || !/^[\x20-\x7e]+$/.test(value) || (pattern && !pattern.test(value))) {
    fail(label, "must be a constrained ASCII string");
  }
  return value;
}

function timestamp(value, label) {
  asciiString(value, TIMESTAMP_PATTERN, label);
  const parsed = new Date(value);
  if (Number.isNaN(parsed.valueOf()) || parsed.toISOString() !== value.replace("Z", ".000Z")) fail(label, "must be a real UTC timestamp");
}

function identifierArray(value, allowlist, label) {
  if (!Array.isArray(value)) fail(label, "must be an array");
  const allowed = new Set(allowlist);
  const seen = new Set();
  for (const identifier of value) {
    asciiString(identifier, /^[a-z0-9_.:-]+$/, label);
    if (!allowed.has(identifier)) fail(label, `unknown identifier ${JSON.stringify(identifier)}`);
    if (seen.has(identifier)) fail(label, `duplicate identifier ${JSON.stringify(identifier)}`);
    seen.add(identifier);
  }
}

export function validateReference(reference, expectedSlug, label = "reference") {
  exactObject(reference, ["schemaVersion", "slug", "updatedAt", "supportedCapabilities", "supportedCommands", "scopes", "features", "limits"], label);
  if (reference.schemaVersion !== 1) fail(label, "schemaVersion must be 1");
  asciiString(reference.slug, SLUG_PATTERN, `${label}.slug`);
  if (reference.slug !== expectedSlug) fail(label, "slug does not match the manifest entry");
  timestamp(reference.updatedAt, `${label}.updatedAt`);
  const isExcalidraw = expectedSlug === "higantic-excalidraw";
  const capabilityIds = isExcalidraw ? EXCALIDRAW_CAPABILITY_IDS : CAPABILITY_IDS;
  const commandIds = isExcalidraw ? EXCALIDRAW_COMMAND_IDS : COMMAND_IDS;
  const scopeIds = isExcalidraw ? EXCALIDRAW_SCOPE_IDS : SCOPE_IDS;
  const featureKeys = isExcalidraw ? EXCALIDRAW_FEATURE_KEYS : FEATURE_KEYS;
  const limitKeys = isExcalidraw ? EXCALIDRAW_LIMIT_KEYS : LIMIT_KEYS;
  identifierArray(reference.supportedCapabilities, capabilityIds, `${label}.supportedCapabilities`);
  identifierArray(reference.supportedCommands, commandIds, `${label}.supportedCommands`);
  identifierArray(reference.scopes, scopeIds, `${label}.scopes`);
  exactObject(reference.features, featureKeys, `${label}.features`);
  for (const key of featureKeys) {
    if (typeof reference.features[key] !== "boolean") fail(`${label}.features.${key}`, "must be boolean");
  }
  exactObject(reference.limits, limitKeys, `${label}.limits`);
  for (const key of limitKeys) {
    const value = reference.limits[key];
    if (!Number.isSafeInteger(value) || value < 0) fail(`${label}.limits.${key}`, "must be a nonnegative safe integer");
  }
  return reference;
}

export function validateSourceManifest(manifest) {
  const label = "source manifest";
  exactObject(manifest, ["schemaVersion", "updatedAt", "references"], label);
  if (manifest.schemaVersion !== 1) fail(label, "schemaVersion must be 1");
  timestamp(manifest.updatedAt, `${label}.updatedAt`);
  if (!Array.isArray(manifest.references) || manifest.references.length === 0) fail(label, "references must be a non-empty array");
  const seen = new Set();
  for (const [index, reference] of manifest.references.entries()) {
    const entryLabel = `${label}.references[${index}]`;
    exactObject(reference, ["slug", "path", "minimumInstalledVersion"], entryLabel);
    asciiString(reference.slug, SLUG_PATTERN, `${entryLabel}.slug`);
    if (seen.has(reference.slug)) fail(entryLabel, "slug must be unique");
    seen.add(reference.slug);
    asciiString(reference.path, /^references\/[a-z0-9]+(?:-[a-z0-9]+)*\.json$/, `${entryLabel}.path`);
    if (reference.path !== `references/${reference.slug}.json`) fail(entryLabel, "path must match slug");
    asciiString(reference.minimumInstalledVersion, SEMVER_PATTERN, `${entryLabel}.minimumInstalledVersion`);
  }
  return manifest;
}

export function validateGeneratedManifest(manifest) {
  const label = "generated manifest";
  exactObject(manifest, ["schemaVersion", "updatedAt", "references"], label);
  if (manifest.schemaVersion !== 1) fail(label, "schemaVersion must be 1");
  timestamp(manifest.updatedAt, `${label}.updatedAt`);
  if (!Array.isArray(manifest.references) || manifest.references.length === 0) fail(label, "references must be a non-empty array");
  const seen = new Set();
  for (const [index, reference] of manifest.references.entries()) {
    const entryLabel = `${label}.references[${index}]`;
    exactObject(reference, ["slug", "referenceUrl", "sha256", "minimumInstalledVersion"], entryLabel);
    asciiString(reference.slug, SLUG_PATTERN, `${entryLabel}.slug`);
    if (seen.has(reference.slug)) fail(entryLabel, "slug must be unique");
    seen.add(reference.slug);
    const expectedUrl = `${PUBLIC_ORIGIN}/v1/references/${reference.slug}.json`;
    asciiString(reference.referenceUrl, null, `${entryLabel}.referenceUrl`);
    if (reference.referenceUrl !== expectedUrl) fail(entryLabel, "referenceUrl must use the exact branded path");
    asciiString(reference.sha256, SHA256_PATTERN, `${entryLabel}.sha256`);
    asciiString(reference.minimumInstalledVersion, SEMVER_PATTERN, `${entryLabel}.minimumInstalledVersion`);
  }
  return manifest;
}
