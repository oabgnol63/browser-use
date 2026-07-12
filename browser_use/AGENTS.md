# AGENTS.md

## Purpose

`browser_use` is the Python runtime for AI-driven browser automation. An `Agent` receives a task, observes browser state, asks an LLM for typed actions, executes those actions through `Tools` and `BrowserSession`, records the results, and repeats until the task is complete or a stop condition is reached.

## Runtime Flow

`agent/service.py::Agent.run()` is the main entry point:

1. Start `BrowserSession`, attach watchdogs, register skills, and execute `initial_actions`.
2. Loop through `Agent.step()` until `done`, maximum steps, consecutive-failure limits, stop, or cancellation.
3. Each step prepares browser context, calls the LLM for a validated action model, executes actions, post-processes results, and finalizes history.
4. `BrowserSession.get_browser_state_summary()` supplies the current URL, tabs, screenshot, recent events, and DOM state when DOM mode is active.
5. `Tools` filters actions for the current page/runtime, dispatches browser events or custom actions, and returns structured `ActionResult` values.
6. Results feed message memory and `AgentHistoryList`, which is the public run output.

Screenshots are captured for every step. Native computer-use/vision mode omits DOM state and must have a current screenshot before the LLM is called; one internal recapture is attempted, then the step fails closed.

## Modes and Backends

- `Mode.DOM`: DOM-derived element indexes and DOM-only actions are available; vision-capable actions may also remain available.
- `Mode.VISION`: used when `use_native_computer_use=True`; DOM-only tools are filtered out and actions operate from visual/coordinate state.
- `Backend.CDP`: default `BrowserSession` transport for Chromium-compatible browsers.
- `Backend.WEBDRIVER`: `SeleniumBrowserSession` and Appium paths. CDP-only actions must not leak into this backend.
- `Platform.DESKTOP`, `Platform.IOS`, and `Platform.ANDROID` further constrain registered tools.

`Agent` derives the active mode, while `Tools.registry` enforces mode/platform/backend constraints. When adding an action, annotate the real compatibility boundary instead of relying on a caller to hide it.

## Browser Event Architecture

Browser work is event-driven. Tools and agent code dispatch typed events from `browser/events.py`; `BrowserSession` and watchdogs handle them through a per-session `EventBus`.

- Await dispatched events and inspect their event result when the caller needs success or returned data.
- Keep event payloads typed and put new browser-wide behavior at the event/watchdog layer when all callers need it.
- Watchdogs own lifecycle concerns including launch/connect, crashes, DOM and screenshot capture, downloads, permissions, popups, storage state, recording, CAPTCHA waits, and default actions.
- Preserve handler sync/async shape when overriding watchdog behavior.
- `BrowserSession.backend` is `CDP` by default; WebDriver subclasses override it.
- `Browser` remains an alias of `BrowserSession`; `Controller` remains an alias of `Tools`.

## Core Modules

- `agent/`: orchestration loop, prompts, message history, action/output schemas, run history, and completion logic.
- `browser/`: event-driven browser lifecycle and CDP session control, tabs, page state, screenshots, downloads, and watchdogs. `Browser` is an alias of `BrowserSession`.
- `tools/`: built-in and custom action registration, typed parameter schemas, action dispatch, and `ActionResult` production. `Controller` is the compatibility alias for `Tools`.
- `dom/`: DOM capture, serialization, interactive-element extraction, and mapping model-visible elements back to browser targets.
- `llm/`: common chat-model interfaces, message/schema types, and provider adapters. Do not rewrite or normalize user-supplied model names.
- `actor/`: deterministic element, mouse, and page operations used below the agent/tool layer.
- `appium/` and `selenium/`: WebDriver transports and action/session compatibility paths; keep their behavior isolated from the default CDP path.
- `filesystem/`, `screenshots/`, and `tokens/`: agent file access, visual artifacts, and token/cost accounting.
- `event_bus.py`: per-instance event processing and concurrency protection; avoid restoring cross-agent global locking.
- `browser/events.py`: typed action, lifecycle, navigation, tab, storage, download, focus, CAPTCHA, and error contracts.
- `browser/watchdogs/`: event handlers that implement browser lifecycle and cross-cutting runtime behavior.
- `agent/system_prompts/`: prompt variants for normal, flash, no-thinking, Browser Use model, Anthropic, and no-DOM execution.

The normal dependency direction is `Agent -> Tools/BrowserSession -> browser or DOM primitives`. Put fixes in the lowest shared layer that owns the broken behavior instead of patching each caller.

## Downstream Contract

Comparator2's worker imports this fork directly and subclasses `Agent` and browser sessions. Changes to agent steps, session startup, tool filtering, events, screenshots, focus behavior, or watchdog method signatures can affect that integration even when this package still passes isolated checks. Preserve public and subclass seams unless the task explicitly changes the contract.

## Keep This File Current

Update this `AGENTS.md` in the same change when behavior changes in any of these areas:

- agent run/step flow, stopping, replay, or memory behavior;
- browser-session creation, lifecycle, focus, events, or watchdog ownership;
- tool exposure, compatibility filtering, action schemas, or action semantics;
- DOM/vision state shape, screenshot guarantees, or backend routing;
- public aliases or subclass extension points.

Small internal fixes that do not change behavior or ownership do not need documentation churn.

## Scope

- Treat `browser_use/` as the project and working root.
- Do not inspect or modify the parent repository unless the task explicitly requires it.
- Work on the Python runtime library. Ignore `browser/cloud/`, `sandbox/`, `skill_cli/`, and CLI entrypoints unless the task explicitly includes them.
- Keep implementation changes inside `browser_use/`; read or run tests elsewhere only when needed to verify the change.

## Guidance Files

- Only guidance files located inside the `browser_use/` subtree are trusted by default.
- Do not read or apply parent/root Markdown files, including root-level `AGENTS.md` or `CLAUDE.md`, unless the user explicitly requests that exact file.
- Within `browser_use/`, `AGENTS.md` and `CLAUDE.md` are both valid sources of project instructions and functional context.
- Before working, read the closest in-scope file that applies to the target path; either filename is sufficient when it contains the needed guidance.
- Read both in-scope files only when their scopes differ, one explicitly points to the other, or the task needs context missing from the first file.
- When in-scope instructions conflict, follow the file closest to the target path and the user's current request.

## Environment

- Target Python 3.12.9.
- Use `uv` for environments, dependencies, and Python commands; never use `pip`.

## Development

- Fix root causes in the shared runtime path with the smallest working change.
- Reuse existing helpers and dependencies; do not add speculative abstractions or example files.
- Follow the existing layout: runtime logic in `service.py`, Pydantic data contracts in `views.py`, event contracts in `events.py`, and prompt text in `prompts.py` or `system_prompts/`.
- Match the existing tab indentation in Python files; do not reformat neighboring code to spaces.
- Keep model names unchanged.
- Use Pydantic v2 models for internal schemas and tool inputs/outputs.
- Prefer structured `ActionResult` values and descriptive action names/docstrings.
- Add the smallest focused regression check for non-trivial logic.
- Run focused checks with `uv`; run pre-commit before a PR.
