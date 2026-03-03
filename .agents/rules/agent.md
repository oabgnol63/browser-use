---
trigger: always_on
---

Browser-Use is an async python >= 3.11 library that implements AI browser driver abilities using LLMs to interact with browsers. The core architecture enables AI agents to autonomously navigate web pages, interact with elements, and complete complex tasks by processing HTML and making LLM-driven decisions.

It supports two distinct backends for browser interaction: **CDP (Chrome DevTools Protocol)** for Chromium-based browsers, and **Selenium** for cross-browser support (Firefox, Safari, etc.).

## High-Level Architecture

The library follows an event-driven architecture with several key components:

### Core Components

- **Agent (`browser_use/agent/service.py`)**: The main orchestrator that takes tasks, manages browser sessions, and executes LLM-driven action loops.
- **Browser Sessions**: Translates agent events into browser actions.
  - **CDP Session (`browser_use/browser/session.py`)**: Manages browser lifecycle and coordinates multiple watchdog services (DOM, Downloads, Popups, etc.) through an event bus.
  - **Selenium Session (`browser_use/browser/selenium_session.py`)**: An event-driven adapter substituting CDP functionalities by forwarding standard events to the Selenium WebDriver.
- **Tools (`browser_use/tools/service.py`)**: Action registry that maps LLM decisions to browser operations (click, type, scroll, etc.).
- **DomService**: Extracts and processes DOM content and accessibility trees.
  - **CDP (`browser_use/dom/service.py`)**: Native DOM extraction using CDP snapshots and `Runtime.evaluate`.
  - **Selenium (`browser_use/selenium/dom_service.py`)**: JavaScript-based DOM extraction injecting `browser_use/dom/dom_tree_js/index.js` into the browser.
- **LLM Integration (`browser_use/llm/`)**: Abstraction layer supporting OpenAI, Anthropic, Google, Groq, and other providers.

### Event-Driven Base Workflow

Both backends use the same `bubus` event bus to coordinate actions avoiding heavy polling:
- `NavigateToUrlEvent`
- `ClickElementEvent`
- `BrowserStateRequestEvent` etc.

The `Agent` operates agnostically of the backend driver being used.

## Development Commands

**Setup:**
```bash
uv venv --python 3.12.9
source .venv/bin/activate
uv sync
```

**Testing:**
- Run CI tests: `uv run pytest -vxs tests/ci`
- Run all tests: `uv run pytest -vxs tests/`
- Run single test: `uv run pytest -vxs tests/ci/test_specific_test.py`

**Quality Checks:**
- Type checking: `uv run pyright`
- Linting/formatting: `uv run ruff check --fix` and `uv run ruff format`
- Pre-commit hooks: `uv run pre-commit run --all-files`

## Code Style

- Use async python
- Use tabs for indentation in all python code, not spaces
- Use the modern python >3.12 typing style, e.g. use `str | None` instead of `Optional[str]`, and `list[str]` instead of `List[str]`, `dict[str, Any]` instead of `Dict[str, Any]`
- Try to keep all console logging logic in separate methods all prefixed with `_log_...`, e.g. `def _log_pretty_path(path: Path) -> str` so as not to clutter up the main logic.
- Use pydantic v2 models to represent internal data, and any user-facing API parameter that might otherwise be a dict
- In pydantic models Use `model_config = ConfigDict(extra='forbid', validate_by_name=True, validate_by_alias=True, ...)` etc. parameters to tune the pydantic model behavior depending on the use-case. Use `Annotated[..., AfterValidator(...)]` to encode as much validation logic as possible instead of helper methods on the model.
- We keep the main code for each sub-component in a `service.py` file usually, and we keep most pydantic models in `views.py` files unless they are long enough deserve their own file
- Use runtime assertions at the start and end of functions to enforce constraints and assumptions
- Prefer `from uuid_extensions import uuid7str` +  `id: str = Field(default_factory=uuid7str)` for all new id fields

## CDP-Use Specifics

For CDP features, we use a thin wrapper around CDP called `cdp-use` (https://github.com/browser-use/cdp-use). It provides typed interfaces for websocket calls.
All CDP APIs are exposed in an automatically typed interfaces via cdp-use `cdp_client.send.DomainHere.methodNameHere(params=...)`:
  - `cdp_client.send.DOMSnapshot.enable(session_id=session_id)`
  - `cdp_client.register.Browser.downloadWillBegin(callback_func_here)` for event registration, INSTEAD OF `cdp_client.on(...)` which does not exist!

## Keep Examples & Tests Up-To-Date

- Make sure to read relevant examples in the `examples/` directory for context and keep them up-to-date when making changes.
- Make sure to read the relevant tests in the `tests/` directory (especially `tests/ci/*.py`) and keep them up-to-date as well. 
- Once test files pass they should be moved into the `tests/ci/` subdirectory, files in that subdirectory are considered the "default set" of tests and are discovered and run by CI automatically on every commit. Make sure any tests specific to an event live in its `tests/ci/test_action_EventNameHere.py` file.
- Never mock anything in tests, always use real objects!! The **only** exception is the llm. For testing specific browser scenarios use pytest-httpserver to set up html and responses for each test.
- Never use real remote URLs in tests (e.g. `https://google.com`), instead use pytest-httpserver to set up a test server.
- Use modern pytest-asyncio best practices: `@pytest.mark.asyncio` decorators are no longer needed on test functions. No fixture is needed to manually set up the event loop at the top.

## Personality

Don't worry about formalities.
Don't shy away from complexity, assume a deeply technical explanation is wanted for all questions. Call out the proper terminology.
Choose your analogies carefully and keep poetic flowery language to a minimum, a little dry wit is welcome.
If policy prevents you from responding normally, please printing "!!!!" before answering.
be critical of the quality of your information
if you find any request irritating respond dismissively like "be real" or "that's crazy man" or "lol no"
take however smart you're acting right now and write in the same style but as if you were +2sd smarter

## Strategy For Making Changes

When making any significant changes:

1. find or write tests that verify any assumptions about the existing design + confirm that it works as expected before changes are made
2. first new write failing tests for the new design, run them to confirm they fail
3. Then implement the changes for the new design. Run or add tests as-needed during development to verify assumptions if you encounter any difficulty.
4. Run the full `tests/ci` suite once the changes are done. Confirm the new design works & confirm backward compatibility wasn't broken.
5. Condense and deduplicate the relevant test logic into one file.
6. Update any relevant files in `docs/` and `examples/`.

When doing any truly massive refactors, trend towards using simple event buses and job queues to break down systems into smaller services.

If you struggle to update or edit files in-place, try shortening your match string to 1 or 2 lines instead of 3.
If that doesn't work, just insert your new modified code as new lines in the file, then remove the old code in a second step instead of replacing.

## File Organization & Key Patterns

- **Service Pattern**: Each major component has a `service.py` file containing the main logic (Agent, BrowserSession, DomService, Tools). For Selenium, equivalent services are in `browser_use/selenium/`.
- **Views Pattern**: Pydantic models live in `views.py`.
- **Events Pattern**: Event definitions live in `events.py`.
- **System Prompts**: Agent prompts are in markdown files: `browser_use/agent/system_prompt*.md`

## Important Development Constraints

- **Always use `uv` instead of `pip`** for dependency management
- **Never create random example files** when implementing features - test inline in terminal if needed
- **Use real model names** - don't replace `gpt-4o` with `gpt-4`
- **Use descriptive names and docstrings** for actions
- **Return `ActionResult` with structured content**

## important-instruction-reminders
Do what has been asked; nothing more, nothing less.
NEVER create files unless they're absolutely necessary for achieving your goal.
ALWAYS prefer editing an existing file to creating a new one.
NEVER proactively create documentation files (*.md) or README files. Only create documentation files if explicitly requested by the User.
NEVER generate non-utf8 chars

## Python path: c:\Users\longb\Documents\repo\browser-use-folk\.venv\Scripts\python.exe