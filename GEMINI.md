# Project Overview

**Browser-Use** is an async Python library (>= 3.11) that implements AI browser driver abilities using LLMs and CDP (Chrome DevTools Protocol). The core architecture enables AI agents to autonomously navigate web pages, interact with elements, and complete complex tasks by processing HTML and making LLM-driven decisions.

## Key Technologies and Architecture
- **Dependency Management:** [`uv`](https://github.com/astral-sh/uv).
- **Core Components:**
  - `Agent`: Orchestrates tasks, manages browser sessions, and executes LLM-driven action loops.
  - `BrowserSession`: Manages browser lifecycle and CDP connections using an event-driven architecture via a `bubus` event bus to coordinate watchdog services (DownloadsWatchdog, PopupsWatchdog, etc.).
  - `Tools`: Action registry mapping LLM decisions to browser operations.
  - `DomService`: Extracts and processes DOM content, handles element highlighting and accessibility tree generation.
- **CDP Integration:** Uses `cdp-use` for typed CDP protocol access.
- **Data Structures:** Uses Pydantic v2 models for all internal action schemas, task inputs/outputs, and tool I/O to ensure robust validation.

## Building and Running

### Setup
```bash
# Complete setup script
./bin/setup.sh

# Or manually:
uv venv --python 3.11
source .venv/bin/activate
uv sync --all-extras --dev
```

### Testing
```bash
# Run CI tests (recommended default)
uv run pytest -vxs tests/ci

# Run all tests
uv run pytest -vxs tests/

# Helper script for core test suite
./bin/test.sh
```

### Quality Checks
```bash
# Type checking
uv run pyright

# Linting and formatting
uv run ruff check --fix
uv run ruff format

# Pre-commit hooks
uv run pre-commit run --all-files

# Helper script for all checks
./bin/lint.sh
```

## Development Conventions

- **Code Style:** Use modern async Python, tabs for indentation, and Python >3.12 typing style (e.g., `str | None` instead of `Optional[str]`, `list[str]` instead of `List[str]`). Never generate special characters that're non-utf8
- **File Organization:** 
  - **Service Pattern:** Main logic for sub-components is kept in `service.py` files.
  - **Views Pattern:** Pydantic models and data structures are kept in `views.py` files.
  - **Events:** Event definitions are in `events.py` files.
- **Pydantic Models:** Use `model_config = ConfigDict(extra='forbid', validate_by_name=True, validate_by_alias=True)` to tune behavior. Encode validation logic using `Annotated[..., AfterValidator(...)]`.
- **Logging:** Keep console logging logic in separate methods prefixed with `_log_` (e.g., `_log_pretty_path`) so as not to clutter the main logic.
- **Testing Practices:** 
  - **NEVER** mock objects in tests—always use real objects. The **only exception** is the LLM (use pytest fixtures in `conftest.py`).
  - **NEVER** use real remote URLs in tests. Use `pytest-httpserver` to set up test servers providing the necessary HTML.
  - Do not use `@pytest.mark.asyncio` on test functions; just write normal async functions for async tests.
- **Error Handling & Constraints:** Use runtime assertions at the start and end of functions to enforce constraints.
- **ID Generation:** Prefer `from uuid_extensions import uuid7str` and `id: str = Field(default_factory=uuid7str)` for all new ID fields.
- **Tools/Actions:** Use descriptive names and docstrings for each action. Prefer returning `ActionResult` with structured content.
- **Examples/Demos:** Do not create random example files when testing new features; use inline terminal testing instead.
