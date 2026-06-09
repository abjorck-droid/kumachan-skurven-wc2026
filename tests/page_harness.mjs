// Loads the pick-entry page script (site/index.html) into a vm with a stub DOM
// and returns the window.__T test hooks. Node 18+, stdlib only.
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import vm from "node:vm";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");

function stubEl() {
  return {
    addEventListener() {}, style: {}, textContent: "", innerHTML: "",
    classList: { toggle() {}, add() {}, remove() {} },
    disabled: false, dataset: {},
  };
}

export function loadPage() {
  const html = readFileSync(join(ROOT, "site", "index.html"), "utf8");
  const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)];
  const code = scripts[scripts.length - 1][1];

  const els = {};
  const document = {
    querySelector(sel) { return (els[sel] ||= stubEl()); },
    querySelectorAll() { return []; },
    getElementById(id) { return (els["#" + id] ||= stubEl()); },
    addEventListener() {},
  };
  const sandbox = {
    document,
    location: { search: "", hostname: "test.invalid" },
    URLSearchParams, setTimeout, clearTimeout, console,
    CSS: { escape: (s) => s },
    confirm: () => true,
    fetch: () => Promise.reject(new Error("no network in tests")),
  };
  sandbox.window = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(code, sandbox, { filename: "index.html#script" });
  if (!sandbox.window.__T) throw new Error("page did not expose window.__T");
  return { T: sandbox.window.__T, els, sandbox };
}

// 48-team fixture: groups A–L × 4, ids 100+gi*4+i, codes like "AT0".
export function makeTeams() {
  const teams = [];
  "ABCDEFGHIJKL".split("").forEach((g, gi) => {
    for (let i = 0; i < 4; i++)
      teams.push({ id: 100 + gi * 4 + i, code: g + "T" + i, name: "Team " + g + i, group: g });
  });
  return teams;
}

// Complete generating structure: every group ordered T0,T1,T2; thirds = A..H.
export function makeStructure(teams) {
  const go = {};
  "ABCDEFGHIJKL".split("").forEach((g) => {
    go[g] = teams.filter((t) => t.group === g).slice(0, 3).map((t) => String(t.id));
  });
  return { go, thirds: "ABCDEFGH".split("") };
}

let n = 0, failed = 0;
export function check(label, cond) {
  n++;
  if (!cond) { failed++; console.error("  ✗ " + label); }
  else console.log("  ✓ " + label);
}
export function summary(name) {
  console.log(`${name}: ${n - failed}/${n} checks passed`);
  if (failed) process.exit(1);
}
