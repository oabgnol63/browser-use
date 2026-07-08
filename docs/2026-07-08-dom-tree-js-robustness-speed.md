# DOM Tree JS Robustness + Speed Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `browser_use/dom/dom_tree_js/index.js` more robust (fewer wrong/missed interactive elements) and faster, with the output contract unchanged.

**Architecture:** Stop reimplementing CSS stacking in JS; delegate to the browser via `elementsFromPoint` (on the element's own document). Read `getComputedStyle`/`getBoundingClientRect` once per node instead of 4–6×. Reduce the ~30-selector interactivity check to one combined `matches`, the O(n²) overlap dedup to a single O(n·depth) ancestor walk, and the two full-document tree scans to one.

**Tech Stack:** Plain browser JS (IIFE injected via Selenium `execute_script`). Verification via a standalone Python + **Selenium/Firefox** script using the `browser-use-folk/.venv` interpreter — this mirrors the real consumer (`SeleniumDomService` runs `driver.execute_script("return (" + js + ")(arguments[0]);", args)`), so we test the exact injection path and the primary target engine, not Playwright/Chromium which this fallback never runs on. Selenium 4.6+ Selenium Manager auto-fetches geckodriver; only Firefox needs to be installed.

## Global Constraints

- File under change: `browser_use/dom/dom_tree_js/index.js` only. `browser_use/selenium/dom_service.py` MUST NOT change.
- Output contract frozen: return `{ map, rootId, iframeNodes, popupContainers, perfMetrics, compactMode }`; per node keep `tagName, attributes, xpath, isVisible, isInteractive, isTopElement, isInViewport, highlightIndex, shadowRoot, viewport, children, text, ariaLabel, ariaDescription, title, role, isScrollable`.
- Indentation: **tabs** (match the existing file and the `browser-use-folk` repo convention — this repo uses tabs, unlike comparator2).
- **No git commits.** The user opted out. Each task ends by running the verification harness green, not by committing. Do not run `git commit`/`git add` at any step.
- Only intended behavior change: an interactive element visually covered by an unrelated (non-ancestor/non-descendant) element is excluded via real hit-testing instead of the area heuristic. All other fixtures must produce an identical selector map, `popupContainers`, and `iframeNodes` before vs after.
- Not in scope: `computed_styles`, `scrollRects`, dual bounds, richer AX, paint-order emission, shadow-root typing, cross-origin content. (Follow-up "Approach B".)

Spec: `C:\Users\longb\Documents\repo\browser-use-folk\docs\superpowers\specs\2026-07-08-dom-tree-js-robustness-speed-design.md` (kept in sync with this plan, incl. the `ownerDocument` hit-test and the top-document popup guard). This plan (comparator2 docs) is authoritative on any disagreement.

**Environment note (Windows / this repo):** run all commands from the `browser-use-folk` repo root using its venv interpreter directly — do NOT `activate` (PowerShell can't source the bash activate script, and bare `python` resolves to system `C:\Python314\python.exe`, not the venv). Use `C:/Users/longb/Documents/repo/browser-use-folk/.venv/Scripts/python.exe` (works from Bash and PowerShell), or the repo-root-relative `.venv/Scripts/python.exe`. Use `rg` for searches (not `rtk grep`).

---

## File Structure

- Modify: `browser_use/dom/dom_tree_js/index.js` (the refactor)
- Create: `browser_use/dom/dom_tree_js/tests/fixtures/*.html` (static DOM fixtures)
- Create: `browser_use/dom/dom_tree_js/tests/compare_dom_extraction.py` (harness: full-signature old-vs-new diff + behavior asserts + perf check)
- Create (transient): `browser_use/dom/dom_tree_js/index.baseline.js` (a copy of `index.js` at plan start, so the harness can run "old" vs "new"). The harness is **baseline-aware**: if this file is absent it skips the old-vs-new diff and relative-perf check and runs behavior + absolute-perf checks only. It is deleted last (Task 6), after the final gate.

---

## Task 1: Verification harness + fixtures + baseline snapshot

**Files:**
- Create: `browser_use/dom/dom_tree_js/tests/fixtures/nested_link.html`
- Create: `browser_use/dom/dom_tree_js/tests/fixtures/link_button_span.html`
- Create: `browser_use/dom/dom_tree_js/tests/fixtures/covered_button.html`
- Create: `browser_use/dom/dom_tree_js/tests/fixtures/modal_over_page.html`
- Create: `browser_use/dom/dom_tree_js/tests/fixtures/same_origin_iframe.html`
- Create: `browser_use/dom/dom_tree_js/tests/fixtures/large_grid.html`
- Create: `browser_use/dom/dom_tree_js/tests/compare_dom_extraction.py`
- Create: `browser_use/dom/dom_tree_js/index.baseline.js` (copy of current `index.js`)

**Interfaces:**
- Produces: `compare_dom_extraction.py` runnable as `.venv/Scripts/python.exe browser_use/dom/dom_tree_js/tests/compare_dom_extraction.py`. Exits non-zero on any failed assertion; prints per-fixture diffs and a `[PERF]` line. Every later task runs it as its gate.
- `full_sig(result) -> dict` returns `{ "selector": [...], "popups": [...], "iframes": [...] }` — the frozen-contract slices the tasks touch (highlighted node rows, popup containers, iframe nodes).

- [ ] **Step 1: Snapshot the current file as the baseline** (before editing `index.js`)

```bash
cp browser_use/dom/dom_tree_js/index.js browser_use/dom/dom_tree_js/index.baseline.js
```

- [ ] **Step 2: Write the fixtures**

`tests/fixtures/nested_link.html` — one link wrapping a span; expect exactly one interactive (`a`):
```html
<!doctype html><html><body style="margin:0">
  <a href="https://example.com" style="display:inline-block;padding:20px">
    <span>Buy now</span>
  </a>
</body></html>
```

`tests/fixtures/link_button_span.html` — link > button > span (intermediate-button case):
```html
<!doctype html><html><body style="margin:0">
  <a href="https://example.com">
    <button type="button"><span>Sign In</span></button>
  </a>
</body></html>
```

`tests/fixtures/covered_button.html` — a real button fully covered by an opaque higher-z-index overlay (the intended behavior change):
```html
<!doctype html><html><body style="margin:0;position:relative;height:400px">
  <button id="target" type="button"
          style="position:absolute;left:50px;top:50px;width:200px;height:60px">
    Click me
  </button>
  <div id="cover"
       style="position:absolute;left:50px;top:50px;width:200px;height:60px;
              background:#000;z-index:10"></div>
</body></html>
```

`tests/fixtures/modal_over_page.html` — background link plus a fixed modal with its own button (exercises `popupContainers`):
```html
<!doctype html><html><body style="margin:0;height:1200px">
  <a href="https://bg.example.com" style="display:block;padding:30px">Background link</a>
  <div role="dialog" aria-modal="true" class="modal"
       style="position:fixed;left:20px;top:20px;width:300px;height:200px;
              background:#fff;z-index:9999;border:1px solid #ccc">
    <button type="button">Confirm</button>
  </div>
</body></html>
```

`tests/fixtures/same_origin_iframe.html` — a same-origin iframe (via `srcdoc`, which inherits the parent origin so `contentDocument` is reachable even under `file://`) containing a button. Exercises iframe recursion and the `ownerDocument` hit-test fix:
The iframe also contains a high-z-index `role=dialog` so the test proves the
top-document popup guard: `popupContainers` must stay **empty** (the old scan
never saw iframe internals).
```html
<!doctype html><html><body style="margin:0">
  <iframe srcdoc="<!doctype html><body style='margin:0'><button type='button' style='width:200px;height:50px'>Inner btn</button><div role='dialog' aria-modal='true' class='modal' style='position:fixed;left:0;top:60px;width:200px;height:120px;z-index:9999'>x</div></body>"
          style="width:320px;height:260px;border:0"></iframe>
</body></html>
```

`tests/fixtures/large_grid.html` — many buttons, for the perf assertion:
```html
<!doctype html><html><body style="margin:0">
  <div id="root"></div>
  <script>
    const root = document.getElementById('root');
    let html = '';
    for (let i = 0; i < 1500; i++) html += '<button type="button">Btn ' + i + '</button>';
    root.innerHTML = html;
  </script>
</body></html>
```

- [ ] **Step 3: Write the harness**

`tests/compare_dom_extraction.py`:
```python
"""Compare old (index.baseline.js) vs new (index.js) DOM extraction.

Runs through Selenium + Firefox, matching the real consumer
(SeleniumDomService: driver.execute_script("return (" + js + ")(arguments[0]);", args)).
Selenium 4.6+ Selenium Manager auto-fetches geckodriver; Firefox must be installed.

Run with the browser-use-folk venv, from the repo root:
    .venv/Scripts/python.exe browser_use/dom/dom_tree_js/tests/compare_dom_extraction.py

Exits non-zero if any assertion fails. Prints per-fixture diffs and a [PERF] line.
Baseline-aware: if index.baseline.js is absent, the old-vs-new diff and the
relative-perf check are skipped; behavior + absolute-perf checks still run.
"""
import sys
import time
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.firefox.options import Options as FirefoxOptions

HERE = Path(__file__).resolve().parent
JS_DIR = HERE.parent
FIXTURES = HERE / "fixtures"
BASELINE = JS_DIR / "index.baseline.js"

ARGS = {
    "doHighlightElements": False,
    "focusHighlightIndex": -1,
    "viewportExpansion": 0,
    "debugMode": False,
    "maxIframeDepth": 5,
    "maxIframes": 100,
    "includeCrossOriginIframes": True,
    "compactMode": False,
}


def load_js(name: str) -> str:
    return (JS_DIR / name).read_text(encoding="utf-8")


def evaluate(driver, js_source: str, args: dict) -> dict:
    # Exactly how SeleniumDomService injects it.
    return driver.execute_script(f"return ({js_source})(arguments[0]);", args)


def selector_rows(result: dict) -> list[dict]:
    rows = []
    for node in result.get("map", {}).values():
        idx = node.get("highlightIndex")
        if idx is not None and idx >= 0:
            rows.append({
                "index": idx,
                "tagName": node.get("tagName"),
                "xpath": node.get("xpath"),
                "text": (node.get("text") or "").strip(),
            })
    rows.sort(key=lambda r: r["index"])
    return rows


def popup_sig(result: dict) -> list[dict]:
    out = []
    for p in result.get("popupContainers", []) or []:
        out.append({
            "tagName": p.get("tagName"),
            "id": p.get("id"),
            "zIndex": p.get("zIndex"),
        })
    out.sort(key=lambda r: (str(r["tagName"]), str(r["id"]), str(r["zIndex"])))
    return out


def iframe_sig(result: dict) -> list[dict]:
    out = []
    for f in result.get("iframeNodes", []) or []:
        out.append({
            "tagName": f.get("tagName"),
            "iframeContent": f.get("iframeContent"),
        })
    out.sort(key=lambda r: (str(r["tagName"]), str(r["iframeContent"])))
    return out


def full_sig(result: dict) -> dict:
    return {
        "selector": selector_rows(result),
        "popups": popup_sig(result),
        "iframes": iframe_sig(result),
    }


def run(driver, fixture: str, js_name: str) -> dict:
    driver.get((FIXTURES / fixture).as_uri())
    time.sleep(0.1)  # let inline/srcdoc fixture content initialize
    return evaluate(driver, load_js(js_name), ARGS)


def main() -> int:
    failures: list[str] = []
    have_baseline = BASELINE.exists()

    opts = FirefoxOptions()
    opts.add_argument("--headless")
    driver = webdriver.Firefox(options=opts)  # Selenium Manager fetches geckodriver
    driver.set_window_size(1280, 900)
    try:
        # --- Regression: full signature (selector + popups + iframes) must not
        #     change on fixtures with no covering overlap. Only runs vs baseline.
        stable = ["nested_link.html", "link_button_span.html",
                  "same_origin_iframe.html", "modal_over_page.html"]
        if have_baseline:
            for fx in stable:
                old = full_sig(run(driver, fx, "index.baseline.js"))
                new = full_sig(run(driver, fx, "index.js"))
                if old != new:
                    failures.append(f"[REGRESSION] {fx}: contract signature changed\n  old={old}\n  new={new}")
        else:
            print("[INFO] index.baseline.js absent — skipping old-vs-new diff")

        # --- Behavior asserts on the NEW code (absolute correctness).
        nl = selector_rows(run(driver, "nested_link.html", "index.js"))
        if not (len(nl) == 1 and nl[0]["tagName"] == "a"):
            failures.append(f"[BEHAVIOR] nested_link: expected one <a>, got {nl}")

        lbs = selector_rows(run(driver, "link_button_span.html", "index.js"))
        if not any("Sign In" in r["text"] for r in lbs):
            failures.append(f"[BEHAVIOR] link_button_span: 'Sign In' not interactive, got {lbs}")

        cb = selector_rows(run(driver, "covered_button.html", "index.js"))
        if any(r["tagName"] == "button" and "Click me" in r["text"] for r in cb):
            failures.append(f"[BEHAVIOR] covered_button: covered button should be dropped, got {cb}")

        # iframe internals detected (and NOT wrongly dropped by ownerDocument hit-test).
        ifr = run(driver, "same_origin_iframe.html", "index.js")
        if not iframe_sig(ifr):
            failures.append("[BEHAVIOR] same_origin_iframe: no iframeNodes recorded")
        if not any("Inner btn" in r["text"] for r in selector_rows(ifr)):
            failures.append(f"[BEHAVIOR] same_origin_iframe: inner button missing, got {selector_rows(ifr)}")
        if popup_sig(ifr):
            failures.append(f"[BEHAVIOR] same_origin_iframe: iframe-internal popup leaked into popupContainers (top-doc guard), got {popup_sig(ifr)}")

        # popup container detected on the modal fixture.
        modal = run(driver, "modal_over_page.html", "index.js")
        if not popup_sig(modal):
            failures.append(f"[BEHAVIOR] modal_over_page: no popupContainers, got {popup_sig(modal)}")

        # --- Perf on the large grid (median of 3).
        def median_ms(js_name: str) -> float:
            js = load_js(js_name)
            samples = []
            for _ in range(3):
                driver.get((FIXTURES / "large_grid.html").as_uri())
                time.sleep(0.05)
                t0 = time.perf_counter()
                evaluate(driver, js, ARGS)
                samples.append((time.perf_counter() - t0) * 1000)
            samples.sort()
            return samples[1]

        new_ms = median_ms("index.js")
        if have_baseline:
            old_ms = median_ms("index.baseline.js")
            print(f"[PERF] large_grid: old={old_ms:.1f}ms new={new_ms:.1f}ms")
            if new_ms > old_ms * 1.15:
                failures.append(f"[PERF] regression: new {new_ms:.1f}ms > old {old_ms:.1f}ms +15%")
        else:
            print(f"[PERF] large_grid: new={new_ms:.1f}ms (no baseline)")
    finally:
        driver.quit()

    if failures:
        print("\n".join(failures))
        print(f"\nFAILED: {len(failures)} assertion(s)")
        return 1
    print("\nALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the harness to establish the baseline**

```bash
# from the browser-use-folk repo root; venv interpreter directly (no activate)
.venv/Scripts/python.exe browser_use/dom/dom_tree_js/tests/compare_dom_extraction.py
```
At this point `index.js == index.baseline.js`, so the regression diff is trivially equal and the behavior asserts reflect **current** behavior. Expect: the four behavior asserts that describe *current* behavior PASS; `covered_button` may FAIL if today's area heuristic keeps the covered button (that is the RED to be fixed in Task 4). `[PERF]` prints — record `new_ms`.

Requires Firefox installed locally; Selenium Manager (bundled with Selenium 4.6+) fetches geckodriver automatically on first run — no manual driver setup. If Selenium is not in the venv: `.venv/Scripts/python.exe -m pip install selenium`.

- [ ] **Step 5: Gate — harness executes and prints `[PERF]`.** Do not proceed until it runs to completion. (No commit.)

---

## Task 2: Precompute a validated combined interactive selector

**Files:**
- Modify: `browser_use/dom/dom_tree_js/index.js` (after `INTERACTIVE_SELECTORS`, ~line 109)

**Interfaces:**
- Produces: module-scoped `const COMBINED_INTERACTIVE_SELECTOR` (string) — `INTERACTIVE_SELECTORS` joined by `,`, with any token an engine rejects dropped once at startup. Consumed by `isElementInteractive` (Task 3).

- [ ] **Step 1: Add the validated combined selector**

Immediately after the `INTERACTIVE_SELECTORS` array literal:
```javascript
	// Precompute one combined selector so isElementInteractive does a single
	// matches() call instead of ~30. Drop any token a given engine rejects
	// (validated once here, not per node).
	const COMBINED_INTERACTIVE_SELECTOR = (function () {
		const valid = [];
		const probe = document.createElement('div');
		for (const sel of INTERACTIVE_SELECTORS) {
			try {
				probe.matches(sel);
				valid.push(sel);
			} catch (e) {
				// Unsupported selector token on this engine — skip it.
			}
		}
		return valid.join(',');
	})();
```

- [ ] **Step 2: Run the harness**

```bash
.venv/Scripts/python.exe browser_use/dom/dom_tree_js/tests/compare_dom_extraction.py
```
Expected: no regression (constant unused yet). `[PERF]` prints. (No commit.)

---

## Task 3: One style + one rect per node; interactivity fast-path

**Files:**
- Modify: `browser_use/dom/dom_tree_js/index.js` — `isElementVisible` (~128), `isInViewport` (~205), `isElementInteractive` (~223), `processNode` (~575), scrollable check (~682)

**Interfaces:**
- Consumes: `COMBINED_INTERACTIVE_SELECTOR` (Task 2).
- Produces:
  - `isElementVisible(element, style, rect)` — `style`/`rect` optional (fall back to computing).
  - `isInViewport(element, expansion, rect)` — `rect` optional.
  - `isElementInteractive(element, style)` — `style` optional; one `matches(COMBINED_INTERACTIVE_SELECTOR)` call.
  - `processNode` computes `style` and `rect` once, threads them into all four checks.

- [ ] **Step 1: Update `isElementVisible` to accept precomputed style/rect**

```javascript
	function isElementVisible(element, style, rect) {
		if (!element || !element.getBoundingClientRect) return false;

		if (typeof element.checkVisibility === 'function') {
			if (!element.checkVisibility({ opacityProperty: true, visibilityProperty: true })) {
				return false;
			}
		}

		style = style || window.getComputedStyle(element);
		if (style.display === 'none' ||
			style.visibility === 'hidden' ||
			style.visibility === 'collapse' ||
			style.opacity === '0') {
			return false;
		}
```
Keep the ancestor opacity fallback, clip check, offsetParent, and pointer-events blocks. Replace the single `const rect = element.getBoundingClientRect();` (~158) with:
```javascript
		rect = rect || element.getBoundingClientRect();
```
In the clip-check loop, the loop reads `const style = window.getComputedStyle(clipCurr);` for **ancestors** — rename that loop variable to `clipStyle` so it does not shadow the `style` param:
```javascript
			const clipStyle = window.getComputedStyle(clipCurr);
			if (clipStyle.display === 'contents') { clipCurr = clipCurr.parentElement; continue; }
			if (clipStyle.overflow !== 'visible' || clipStyle.overflowX !== 'visible' || clipStyle.overflowY !== 'visible') {
```
The offsetParent block's `const position = style.position;` now reads the param (element's own style) — correct, leave it.

- [ ] **Step 2: Update `isInViewport` to accept a precomputed rect**

```javascript
	function isInViewport(element, expansion = 0, rect) {
		if (!element || !element.getBoundingClientRect) return false;
		rect = rect || element.getBoundingClientRect();
		const viewportHeight = window.innerHeight || document.documentElement.clientHeight;
		const viewportWidth = window.innerWidth || document.documentElement.clientWidth;
		return (
			rect.bottom >= -expansion &&
			rect.top <= viewportHeight + expansion &&
			rect.right >= -expansion &&
			rect.left <= viewportWidth + expansion
		);
	}
```

- [ ] **Step 3: Rewrite `isElementInteractive` (one combined matches + shared style)**

```javascript
	function isElementInteractive(element, style) {
		if (!element || element.nodeType !== Node.ELEMENT_NODE) return false;

		let matchesInteractive = false;
		try {
			matchesInteractive = COMBINED_INTERACTIVE_SELECTOR && element.matches(COMBINED_INTERACTIVE_SELECTOR);
		} catch (e) {
			matchesInteractive = false;
		}

		if (matchesInteractive) {
			if (element.tagName === 'A') {
				const text = (element.textContent || '').trim();
				const ariaLabel = element.getAttribute('aria-label')?.trim();
				const title = element.getAttribute('title')?.trim();
				const hasImage = element.querySelector('img, svg, [role="img"]');
				if (!text && !ariaLabel && !title && !hasImage) {
					return false;
				}
			}
			return true;
		}

		const tagName = element.tagName.toUpperCase();
		if (tagName === 'DIV' || tagName === 'SPAN') {
			style = style || window.getComputedStyle(element);
			if (style.cursor === 'pointer') return true;
		}
		return false;
	}
```

- [ ] **Step 4: Thread style/rect through `processNode`**

After the `SKIP_TAGS` guard, before the checks (~614):
```javascript
		const style = window.getComputedStyle(node);
		const rect = node.getBoundingClientRect();

		const isVisible = isElementVisible(node, style, rect);
		const inViewport = isInViewport(node, viewportExpansion, rect);
		const isInteractive = isElementInteractive(node, style);
		const isTop = isTopElement(node, rect);
```
Delete the later duplicate `const rect = node.getBoundingClientRect();` (~622) — reuse the above. In the scrollable block (~682), remove its `const style = window.getComputedStyle(node);` and reuse `style`. The text-node branch keeps `isElementVisible(node.parentElement)` (no args → helper computes).

- [ ] **Step 5: Run the harness**

```bash
.venv/Scripts/python.exe browser_use/dom/dom_tree_js/tests/compare_dom_extraction.py
```
Expected: no regression; `[PERF]` `new_ms` should already dip below baseline. (No commit.)

---

## Task 4: Replace stacking machinery with `ownerDocument.elementsFromPoint`

**Files:**
- Modify: `browser_use/dom/dom_tree_js/index.js` — replace `isTopElement` (~261); delete `hasOverlappingHigherElement`, `getZIndex`, `getStackingPriority`, `getVisibleSiblings`, `getStackingContext`.

**Interfaces:**
- Consumes: `isTopElement(element, rect)` called from `processNode` (Task 3) and `processIframe` (~847).
- Produces: `isTopElement(element, rect)` using the element's **own** document paint stack (correct for elements inside same-origin iframes, whose `getBoundingClientRect` is own-document-relative). `rectsOverlap` stays until Task 5 removes its last caller.

- [ ] **Step 1: Rewrite `isTopElement`**

```javascript
	/**
	 * Is this element the one the browser would hit at its center point?
	 * Uses the real paint stack instead of hand-rolled z-index math. Hit-tests
	 * against the element's OWN document (element.ownerDocument): inside a
	 * same-origin iframe, getBoundingClientRect() is relative to the iframe's
	 * own viewport, so we must query that document, not the top one. Elements
	 * whose center is outside their document's viewport cannot be hit-tested and
	 * are treated as top (still indexed when viewportExpansion > 0).
	 */
	function isTopElement(element, rect) {
		if (!element || !element.getBoundingClientRect) return false;
		rect = rect || element.getBoundingClientRect();
		if (rect.width === 0 || rect.height === 0) return false;

		const doc = element.ownerDocument || document;
		const view = doc.defaultView || window;
		const centerX = rect.left + rect.width / 2;
		const centerY = rect.top + rect.height / 2;

		if (centerX < 0 || centerY < 0 ||
			centerX > view.innerWidth || centerY > view.innerHeight) {
			return true;  // outside this document's viewport: cannot hit-test
		}

		try {
			const stack = doc.elementsFromPoint(centerX, centerY);
			let top = null;
			for (const el of stack) {
				if (el.id === 'browser-use-highlight-container') continue;
				if (el.classList && el.classList.contains('browser-use-highlight')) continue;
				top = el;
				break;
			}
			if (!top) return false;
			if (top === element) return true;
			if (element.contains(top)) return true;   // hit a descendant
			if (top.contains(element)) return true;    // pointer-events wrapper on top
			return false;
		} catch (e) {
			return false;
		}
	}
```

- [ ] **Step 2: Delete the five now-dead stacking functions**

Remove `hasOverlappingHigherElement`, `getZIndex`, `getStackingPriority`, `getVisibleSiblings`, `getStackingContext`. Keep `rectsOverlap` until Task 5 Step 3 (its last caller is the O(n²) filter).

- [ ] **Step 3: Run the harness**

```bash
.venv/Scripts/python.exe browser_use/dom/dom_tree_js/tests/compare_dom_extraction.py
```
Expected: stable regression diff still equal; `covered_button` behavior check now PASSES; `same_origin_iframe` inner button still detected (ownerDocument fix). `[PERF]` improved/equal. (No commit.)

---

## Task 5: Single-pass O(n·depth) containment dedup

**Files:**
- Modify: `browser_use/dom/dom_tree_js/index.js` — the `filteredInteractive` loop (~1025–1164); delete `rectsOverlap`.

**Interfaces:**
- Consumes: `interactiveElements` (array of `{ nodeId, element, rect, isTop }`).
- Produces: `filteredInteractive` (same shape), built in one upward ancestor walk per element — **no inner scan over `interactiveElements`**. Preserves the link/button target rules and the intermediate-button exception. Drops covered elements via `isTop === false`.

- [ ] **Step 1: Replace the pairwise loop with a single-pass walk**

Replace the entire `filteredInteractive` construction (the `for i / for j` block) AND the two duplicated `if (debugMode)` filtering-results blocks that follow it (they reference the now-removed `filteredOutParents`/`filteredOutOverlaps`) with:
```javascript
		// O(n·depth) dedup. For each interactive element we walk UP to its first
		// interactive ancestor and decide with the existing target/innermost
		// rules. Each nesting level is resolved by its own walk, so no pairwise
		// O(n^2) scan is needed. `drop` collects elements to filter out.
		const interactiveElementSet = new Set(interactiveElements.map(it => it.element));
		const drop = new Set();

		function isTargetEl(el) {
			return el.tagName === 'A' || el.tagName === 'BUTTON' || el.getAttribute('role') === 'button';
		}

		for (const cur of interactiveElements) {
			const curTarget = isTargetEl(cur.element);
			let intermediateButton = false;
			let a = cur.element.parentElement;
			while (a) {
				if (interactiveElementSet.has(a)) {
					const aTarget = isTargetEl(a);
					if (aTarget && curTarget) {
						// Outer target contains an inner target -> keep the inner one.
						drop.add(a);
					} else if (aTarget && !curTarget && !intermediateButton) {
						// Generic descendant of a link/button -> the target is the
						// click point; drop the descendant. (Skip if a button sits
						// between: that nearer button already owns the descendant.)
						drop.add(cur.element);
					}
					break;  // first interactive ancestor decides this element
				}
				if (a.tagName === 'BUTTON' || a.getAttribute('role') === 'button') {
					intermediateButton = true;
				}
				a = a.parentElement;
			}
		}

		const filteredInteractive = interactiveElements.filter(
			it => it.isTop !== false && !drop.has(it.element)
		);

		if (debugMode) {
			console.log(`[Browser-Use DOM] Kept ${filteredInteractive.length}/${interactiveElements.length} interactive elements`);
		}
```

- [ ] **Step 2: Delete `rectsOverlap` and confirm no dead references**

```bash
rg -n "rectsOverlap|hasOverlappingHigherElement|getStackingContext|getStackingPriority|getVisibleSiblings|getZIndex|filteredOutParents|filteredOutOverlaps" browser_use/dom/dom_tree_js/index.js
```
Expected: no matches. Delete any that remain.

- [ ] **Step 3: Run the harness**

```bash
.venv/Scripts/python.exe browser_use/dom/dom_tree_js/tests/compare_dom_extraction.py
```
Expected: ALL behavior + regression checks PASS; `[PERF]` improved (no O(n²) on `large_grid`'s 1500 buttons). (No commit.)

---

## Task 6: Fold popup detection into the main walk

**Files:**
- Modify: `browser_use/dom/dom_tree_js/index.js` — add inline popup collection in `processNode`; delete `processPopupContainers` (~928); fix the main-execution call site (~1004).

**Interfaces:**
- Consumes: per-node `style` and `rect` from Task 3.
- Produces: module-scoped `const popupContainers = []` populated during the walk; `processPopupContainers` removed. Returned `popupContainers` shape unchanged.

- [ ] **Step 1: Add module-scoped popup array + inline collector**

Near the other trackers (~54):
```javascript
	// Popup/overlay containers collected during the main walk (was a separate
	// full-document querySelectorAll scan).
	const popupContainers = [];

	function maybeCollectPopup(element, style, rect) {
		// Top document only: the old processPopupContainers scanned just the top
		// document.querySelectorAll('*'). The main walk recurses into same-origin
		// iframe bodies, so without this guard we would newly report iframe-internal
		// popups and change the frozen popupContainers output.
		if (element.ownerDocument !== document) return;
		const zIndex = parseInt(style.zIndex, 10);
		if (!(zIndex > 9000)) return;
		const position = style.position;
		if (position !== 'fixed' && position !== 'absolute') return;
		if (style.display === 'none' || style.visibility === 'hidden') return;
		if (rect.width <= 50 || rect.height <= 50) return;

		const classes = (element.className || '').toString();
		const id = element.id || '';
		const combined = (classes + ' ' + id).toLowerCase();
		const role = element.getAttribute('role');
		const isLikelyPopup =
			combined.includes('modal') || combined.includes('popup') ||
			combined.includes('dialog') || combined.includes('overlay') ||
			combined.includes('signin') || combined.includes('login') ||
			combined.includes('consent') || combined.includes('cookie') ||
			combined.includes('banner') ||
			role === 'dialog' || role === 'alertdialog' ||
			element.getAttribute('aria-modal') === 'true';

		if (isLikelyPopup) {
			popupContainers.push({ element, rect, zIndex, type: 'popup-container' });
			if (debugMode) {
				console.log(`[Browser-Use DOM] Detected popup container: ${element.tagName}#${id} z-index=${zIndex}`);
			}
		}
	}
```

- [ ] **Step 2: Call the collector from `processNode`**

Right after `style`/`rect` are computed (Task 3 Step 4):
```javascript
		maybeCollectPopup(node, style, rect);
```

- [ ] **Step 3: Remove `processPopupContainers` and its call**

Delete the whole `processPopupContainers` function (~928–988). In the main execution block, replace:
```javascript
		const popupContainers = processPopupContainers();
		if (debugMode && popupContainers.length > 0) {
```
with:
```javascript
		if (debugMode && popupContainers.length > 0) {
```
Ensure no other `const popupContainers` re-declaration remains in the main block (it is now module-scoped).

- [ ] **Step 4: Final gate (baseline present)**

```bash
.venv/Scripts/python.exe browser_use/dom/dom_tree_js/tests/compare_dom_extraction.py
```
Expected: ALL CHECKS PASSED — `modal_over_page` popup signature equals baseline (popup output unchanged), `same_origin_iframe` unchanged, `[PERF]` improved (one fewer full-document scan). (No commit.)

- [ ] **Step 5: Remove the baseline snapshot (cleanup, after the gate passes)**

```bash
rm browser_use/dom/dom_tree_js/index.baseline.js
```
Optional confirmation run — the harness is baseline-aware and still passes (behavior + absolute-perf only):
```bash
.venv/Scripts/python.exe browser_use/dom/dom_tree_js/tests/compare_dom_extraction.py
```
Expected: `[INFO] index.baseline.js absent — skipping old-vs-new diff`, then `ALL CHECKS PASSED`. (No commit — leave all changes in the working tree for review.)

---

## Self-Review notes

- **Spec coverage:** §1 style/rect → Task 3; §2 `elementsFromPoint`/`ownerDocument` → Task 4; §3 fast-path → Tasks 2+3; §4 O(n·depth) dedup → Task 5; §5 popup fold → Task 6; verification → Task 1. All covered.
- **Contract:** no task edits `selenium/dom_service.py`; return shape and node fields unchanged. Harness asserts `selector` + `popupContainers` + `iframeNodes` equality on stable fixtures, closing the earlier gap where Task 6 could silently break popups.
- **Findings addressed:** (1) baseline-aware harness + baseline deleted only after the final gate; (2) `ownerDocument`/`defaultView` hit-test for iframe internals + `same_origin_iframe` fixture; (3) single upward-walk dedup, no inner `interactiveElements` scan → true O(n·depth); (4) absolute spec path, plan co-located with spec in `browser-use-folk`; (5) full-signature (popups + iframes) regression asserts.
- **Round-2 findings addressed:** spec updated to `ownerDocument.elementsFromPoint` + popup guard (no longer stale); `maybeCollectPopup` guarded to `ownerDocument === document` so iframe-internal popups don't leak into `popupContainers`, with a fixture + assert proving it; all commands use the venv interpreter `.venv/Scripts/python.exe` directly (no `activate`, no system `python`); searches use `rg` (not `rtk grep`).
- **Type/name consistency:** `isElementVisible(element, style, rect)`, `isInViewport(element, expansion, rect)`, `isElementInteractive(element, style)`, `isTopElement(element, rect)`, `COMBINED_INTERACTIVE_SELECTOR`, `popupContainers`, `maybeCollectPopup`, `isTargetEl`, `drop`, `interactiveElementSet` used consistently.
- **Ordering caveat:** Task 4 deletes the stacking functions but keeps `rectsOverlap`; Task 5 removes it. Run Tasks 4 and 5 back-to-back.
- **No commits:** every gate is "run harness green"; no `git commit`/`git add` anywhere.
