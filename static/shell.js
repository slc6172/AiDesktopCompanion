// Pure layout/hit-testing logic for the desktop-pet shell (spec Part 9, ticket 34). No DOM, no
// Electron, no timers: the page and Electron's main process both load this one file (same
// dual-export pattern as player.js / vad.js / clipswitch.js), so a rule lives in exactly one place.

const SCALE_MIN = 0.5;
const SCALE_MAX = 1.5;
const SCALE_STEP = 0.1;

const round2 = (n) => Math.round(n * 100) / 100;

function clampScale(scale) {
  if (typeof scale !== "number" || !Number.isFinite(scale)) return 1;
  return round2(Math.min(SCALE_MAX, Math.max(SCALE_MIN, scale)));
}

const CHAR_H = 640; // character area height at 100% (9:16 at 360 wide)

// Largest scale at which the character is still no taller than the work area, in whole steps.
function maxScaleForWorkArea(workAreaHeight) {
  if (typeof workAreaHeight !== "number" || !Number.isFinite(workAreaHeight)) return SCALE_MAX;
  return clampScale(Math.floor((workAreaHeight / CHAR_H) * 10 + 1e-9) / 10);
}

function stepScale(scale, direction, workAreaHeight) {
  const next = clampScale(round2(clampScale(scale) + direction * SCALE_STEP));
  return Math.min(next, maxScaleForWorkArea(workAreaHeight));
}

const CHAR_W = 360;
const TOOLBAR_W = 48;
const PANEL_W = 340;
const MIN_WINDOW_H = 560; // keeps the chat panel usable when the character is scaled right down
const PANEL_MAX_H = 640;

// Window geometry for a scale. The character and toolbar are bottom-aligned inside the window;
// the panel column is always reserved (transparent while collapsed), so opening it never resizes
// the window.
function computeLayout(scale) {
  const s = clampScale(scale);
  const charW = Math.round(CHAR_W * s);
  const charH = Math.round(CHAR_H * s);
  const winH = Math.max(charH, MIN_WINDOW_H);
  return {
    scale: s, charW, charH, toolbarW: TOOLBAR_W, panelW: PANEL_W,
    winW: charW + TOOLBAR_W + PANEL_W, winH, panelH: Math.min(winH, PANEL_MAX_H),
    charTop: winH - charH,
  };
}

const EDGE_MARGIN = 16;

// The part of the window that must stay reachable: character + toolbar column, bottom-aligned.
// (The panel column is allowed to hang off the screen while it is collapsed.)
function keptVisibleRect(pos, layout) {
  return { x: pos.x, y: pos.y + layout.charTop, w: layout.charW + layout.toolbarW, h: layout.charH };
}

function fitsInside(rect, area) {
  return rect.x >= area.x && rect.y >= area.y &&
    rect.x + rect.w <= area.x + area.width && rect.y + rect.h <= area.y + area.height;
}

function defaultPosition(primary, layout) {
  const x = primary.x + primary.width - (layout.charW + layout.toolbarW) - EDGE_MARGIN;
  const y = primary.y + primary.height - layout.winH - EDGE_MARGIN;
  return { x, y: Math.max(primary.y, y) };
}

// `saved` is whatever was read back from window-state.json; `workAreas[0]` is the primary display.
function validateBounds(saved, workAreas, layout) {
  const ok = saved && Number.isFinite(saved.x) && Number.isFinite(saved.y);
  if (ok) {
    const pos = { x: saved.x, y: saved.y };
    if (workAreas.some((area) => fitsInside(keptVisibleRect(pos, layout), area))) return pos;
  }
  return defaultPosition(workAreas[0], layout);
}

// After the panel slides open: if the window now runs past the right edge of its work area,
// move it left until it fits — but never so far left that the window's own left edge leaves the
// work area. `bounds` is {x, y, width, height}; the y never changes.
function placePanelOpen(bounds, workArea) {
  const overflow = bounds.x + bounds.width - (workArea.x + workArea.width);
  if (overflow <= 0) return { x: bounds.x, y: bounds.y };
  return { x: Math.max(workArea.x, bounds.x - overflow), y: bounds.y };
}

const HIT_RATIO_MIN = 0.2;
const HIT_RATIO_MAX = 1;

const inRect = (p, r) => p.x >= r.x && p.x < r.x + r.w && p.y >= r.y && p.y < r.y + r.h;

// The single place that decides "does this point take the mouse, or fall through to the desktop?".
// regions = { character: rect, toolbar: [rect, ...] (visible buttons only), panel: rect }, all in
// window coordinates. Swapping in a per-pixel alpha test later only means changing this function.
function hitTest(point, regions, { passthrough, panelOpen, ratio }) {
  if (!passthrough) {
    const r = Math.min(HIT_RATIO_MAX, Math.max(HIT_RATIO_MIN, Number.isFinite(ratio) ? ratio : 0.6));
    const c = regions.character;
    const w = c.w * r;
    if (inRect(point, { x: c.x + (c.w - w) / 2, y: c.y, w, h: c.h })) return true;
  }
  if ((regions.toolbar || []).some((rect) => inRect(point, rect))) return true;
  return !!panelOpen && !!regions.panel && inRect(point, regions.panel);
}

const initialUnread = () => ({ count: 0, panelOpen: false });

// Unread badge on the gear icon: only messages that arrive while the panel is collapsed count,
// opening the panel reads them all, and the history loaded at start-up was never "new".
function nextUnread(state, event) {
  switch (event.type) {
    case "message":
      if (event.history || state.panelOpen) return state;
      return { ...state, count: state.count + 1 };
    case "panel_opened":
      return { count: 0, panelOpen: true };
    case "panel_closed":
      return { ...state, panelOpen: false };
    default:
      return state;
  }
}

const overlap = (rect, area) =>
  Math.max(0, Math.min(rect.x + rect.w, area.x + area.width) - Math.max(rect.x, area.x)) *
  Math.max(0, Math.min(rect.y + rect.h, area.y + area.height) - Math.max(rect.y, area.y));

const containsPoint = (area, p) =>
  p.x >= area.x && p.x < area.x + area.width && p.y >= area.y && p.y < area.y + area.height;

// Where a dragged window may actually go: the character + toolbar must end up fully inside one
// work area (the panel column may hang off). The work area is the one under `pointer` when given
// (the user is steering with it), else the one the character overlaps most. `pos` is the window's
// top-left; the result is too.
function clampPosition(pos, workAreas, layout, pointer) {
  let area = pointer && workAreas.find((a) => containsPoint(a, pointer));
  if (!area) {
    const kept = keptVisibleRect(pos, layout);
    area = workAreas.reduce((best, a) => (overlap(kept, a) > overlap(kept, best) ? a : best), workAreas[0]);
  }
  const keptW = layout.charW + layout.toolbarW;
  // keep the top/left edge in view if the area is too small to hold everything
  const maxX = Math.max(area.x, area.x + area.width - keptW);
  const minY = area.y - layout.charTop;
  const maxY = Math.max(minY, area.y + area.height - layout.winH);
  return {
    x: Math.min(maxX, Math.max(area.x, pos.x)),
    y: Math.min(maxY, Math.max(minY, pos.y)),
  };
}

const EXIT_ARM_MS = 3000;

const initialExit = () => ({ phase: "idle", armedAt: null });

// The exit button's two-step confirmation. event = { type: "press" | "tick" | "fold", now }; `now` is
// supplied by the caller (the function reads no clock). Returns { state, effect } where effect is
// "arm" (show the confirm look), "quit" (really quit), "disarm" (back to normal) or "none".
function nextExitState(state, event) {
  const idle = initialExit();
  if (event.type === "press") {
    if (state.phase === "armed" && event.now - state.armedAt < EXIT_ARM_MS) return { state: idle, effect: "quit" };
    return { state: { phase: "armed", armedAt: event.now }, effect: "arm" };
  }
  if (state.phase !== "armed") return { state, effect: "none" };
  if (event.type === "fold") return { state: idle, effect: "disarm" };
  if (event.type === "tick" && event.now - state.armedAt >= EXIT_ARM_MS) return { state: idle, effect: "disarm" };
  return { state, effect: "none" };
}

const api = { clampPosition, nextUnread, initialUnread, hitTest, placePanelOpen, validateBounds, defaultPosition, computeLayout, clampScale, stepScale, maxScaleForWorkArea, SCALE_MIN, SCALE_MAX, SCALE_STEP, EXIT_ARM_MS, initialExit, nextExitState };
if (typeof module !== "undefined") module.exports = api;
else globalThis.CompanionShell = api;
