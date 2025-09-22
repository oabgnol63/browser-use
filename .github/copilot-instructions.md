# Browser-Use AI Agent Copilot Instructions

This file provides essential guidance for AI coding agents working with Browser-Use, an async Python library that enables AI agents to autonomously control web browsers using LLMs and Chrome DevTools Protocol (CDP).

## Core Architecture

Browser-Use follows an **event-driven architecture** with clear service boundaries:

### Key Components & Data Flow

- **Agent** (`browser_use/agent/service.py`): Main orchestrator that runs LLM-driven action loops, manages browser sessions, and processes tasks
- **BrowserSession** (`browser_use/browser/session.py`): Manages browser lifecycle, CDP connections, and coordinates watchdog services via `bubus` event bus
- **DomService** (`browser_use/dom/service.py`): Extracts and processes DOM content, handles element highlighting, and generates accessibility trees
- **Tools** (`browser_use/tools/service.py`): Action registry that maps LLM decisions to browser operations (click, type, scroll, etc.)

### Event-Driven Browser Management

BrowserSession uses a `bubus` event bus to coordinate **watchdog services** in a reactive pattern:

#### Bubus Event Bus Architecture
- **FIFO processing**: Events queued synchronously, processed async with guaranteed order
- **Parallel handlers**: Multiple watchdogs can react to same event simultaneously
- **Parent-child tracking**: Child events automatically linked to parent handlers via context vars
- **Timeout management**: Per-event timeouts with deadlock detection (15s warning, configurable per event)
- **Event history**: Maintains queryable history with memory management (default 50 events)

#### Parallel Handler Execution Model
```python
# Default: parallel_handlers=False (serial execution)
# Handlers for same event run sequentially, waiting for each to complete
# Different events can still run concurrently across the event bus

class EventBus:
    parallel_handlers: bool = False  # Serial by default
    
    async def _execute_handlers(self, event, handlers):
        if self.parallel_handlers:
            # Create tasks for all handlers, run in parallel
            handler_tasks = {}
            for handler_id, handler in handlers.items():
                task = asyncio.create_task(self.execute_handler(event, handler))
                handler_tasks[handler_id] = (task, handler)
            # Wait for ALL handlers to complete
            for task, handler in handler_tasks.values():
                await task
        else:
            # Serial execution: wait for each handler before starting next
            for handler_id, handler in handlers.items():
                await self.execute_handler(event, handler)
```

#### Core Watchdog Services
```python
# Watchdog pattern: inherit BaseWatchdog, declare LISTENS_TO/EMITS
class DOMWatchdog(BaseWatchdog):
    LISTENS_TO = [TabCreatedEvent, BrowserStateRequestEvent]
    EMITS = [BrowserErrorEvent]
    
    async def on_BrowserStateRequestEvent(self, event: BrowserStateRequestEvent) -> BrowserStateSummary:
        # React to event, return result
```

**Key Watchdogs**:
- **DOMWatchdog**: DOM snapshots, accessibility trees, element highlighting
- **DownloadsWatchdog**: PDF auto-download, file management with CDP events
- **PopupsWatchdog**: JavaScript dialogs, alerts, confirms via CDP
- **SecurityWatchdog**: Domain restrictions, content security policies
- **AboutBlankWatchdog**: Empty page redirects and navigation errors
- **ScreenshotWatchdog**: Page screenshots with viewport management
- **PermissionsWatchdog**: Browser permission requests (camera, location, etc.)

#### Event Timeout Hierarchies
```python
# Event-specific timeouts (configurable via environment variables)
NavigateToUrlEvent: 30.0s    # Parent navigation timeout
├── TabCreatedEvent: 10.0s   # Child tab creation timeout  
├── DOMSnapshot: 30.0s       # Child DOM building timeout
└── ScreenshotEvent: 8.0s    # Child screenshot timeout

BrowserStateRequestEvent: 30.0s  # Coordinates multiple child operations
├── DOM processing: inherits parent timeout
├── Screenshot capture: 8.0s (independent timeout)
└── Recent events: inherits parent timeout

# Timeout inheritance: child events inherit parent timeout unless specified
# Timeout override: TIMEOUT_EventName environment variable overrides defaults
```

#### Concrete Event Flow Examples
```python
# Example 1: Agent Navigation Request
agent_navigate = browser_session.event_bus.dispatch(
    NavigateToUrlEvent(url="https://example.com")
)

# Multiple watchdogs react IN PARALLEL to NavigateToUrlEvent:
# 1. SecurityWatchdog validates domain (blocks if restricted)
# 2. DOMWatchdog prepares for new DOM state
# 3. DownloadsWatchdog monitors for potential file downloads
# 4. AboutBlankWatchdog handles redirects

# Example 2: DOM State Request (triggers complex parallel workflow)
dom_request = browser_session.event_bus.dispatch(
    BrowserStateRequestEvent(include_dom=True, include_screenshot=True)
)

# Coordinated parallel execution:
# 1. DOMWatchdog.on_BrowserStateRequestEvent() starts DOM building
# 2. ScreenshotWatchdog.on_ScreenshotEvent() captures screenshot  
# 3. Both run concurrently, each with independent timeouts
# 4. BrowserStateRequestEvent completes when BOTH children complete

await dom_request  # Waits for all parallel handlers to complete
result = await dom_request.event_result()  # Gets the BrowserStateSummary
```

#### Event Flow Pattern
```python
# 1. Agent/Tools trigger high-level events
event = browser_session.event_bus.dispatch(NavigateToUrlEvent(url="https://example.com"))

# 2. Multiple watchdogs react simultaneously  
# - SecurityWatchdog validates domain
# - DOMWatchdog prepares for new DOM
# - ScreenshotWatchdog clears old screenshot

# 3. Await completion with full result context
completed_event = await event
navigation_result = completed_event.event_result()  # First handler result
```

### CDP Integration Pattern

Uses `cdp-use` for typed CDP protocol access with **automatic message handling**:

#### CDP Client Architecture
- **Typed interfaces**: Auto-generated CDP domain APIs with full typing
- **Session management**: Multiple targets/frames via sessionId parameter
- **Event registration**: `cdp_client.register.Domain.eventName(callback)` pattern
- **WebSocket abstraction**: Connection pooling, reconnection, and cleanup

#### Critical CDP Patterns
```python
# Session-aware CDP calls (most common)
await cdp_client.send.DOMSnapshot.enable(session_id=session_id)
await cdp_client.send.Page.navigate(params={'url': url}, session_id=session_id)

# Target management for tabs/iframes
result = await cdp_client.send.Target.attachToTarget(
    params=AttachToTargetParameters(targetId=target_id, flatten=True)
)

# Event handlers (NOT cdp_client.on() - use register!)
cdp_client.register.Browser.downloadWillBegin(self._handle_download)
cdp_client.register.Page.loadEventFired(self._handle_page_load)

# Multi-session coordination
for session_id in active_sessions:
    await cdp_client.send.Runtime.evaluate(
        params={'expression': 'document.title'}, 
        session_id=session_id
    )
```

#### CDP Message Flow
1. **Outgoing**: `🌎 ← #123: Page.navigate({"url": "..."})`
2. **Event**: `📡 → Page.loadEventFired (session: abc123)`
3. **Response**: `✅ → #123: {"frameId": "..."}`
4. **Watchdog reaction**: Event triggers multiple handlers via bubus

## Development Commands & Workflows

**Always use `uv` instead of `pip`** for dependency management:

```bash
# Setup
uv venv --python 3.11
source .venv/bin/activate  # or .venv\Scripts\activate on Windows
uv sync

# Testing - CI tests are the main test suite
uv run pytest --numprocesses auto tests/ci
uv run pytest -vxs tests/ci/test_specific_test.py  # single test

# Quality checks
uv run pyright                    # type checking
uv run ruff check --fix          # linting
uv run ruff format               # formatting
uv run pre-commit run --all-files # pre-commit hooks
```

**MCP Server Mode** for Claude Desktop integration:
```bash
uvx browser-use[cli] --mcp
```

## Critical Code Patterns

### Service Pattern
Each major component follows `service.py` + `views.py` structure:
- **service.py**: Main business logic and async operations
- **views.py**: Pydantic models and data structures
- **events.py**: Event definitions for the event bus

### Pydantic Configuration Standard
```python
# Required for all models
model_config = ConfigDict(
    extra='forbid', 
    validate_by_name=True, 
    validate_by_alias=True
)

# Use runtime validation extensively
from uuid_extensions import uuid7str
id: str = Field(default_factory=uuid7str)
```

### Error Handling Pattern
```python
# Always use BrowserError for user-facing errors
from browser_use.browser.views import BrowserError

raise BrowserError(
    long_term_memory="Context for LLM about what failed",
    short_term_memory="Immediate error details"
)
```

### Testing Requirements
- **Never mock real objects** - only mock LLM responses via `conftest.py` fixtures
- **Use `pytest-httpserver`** for all web content - never use real URLs like `google.com`
- **Move passing tests to `tests/ci/`** - this directory runs on every commit
- Tests use **async/await without `@pytest.mark.asyncio`** decorators (handled automatically)

## Configuration & Environment

### Browser Profile System
`browser_use/browser/profile.py` handles all browser launch arguments:
- Auto-detects display size via `detect_display_configuration()`
- Manages extensions (uBlock Origin, cookie handlers) with whitelisting
- Proxy support and security settings configuration

### Environment Variables
Key environment variables (see `browser_use/config.py`):
```bash
BROWSER_USE_LOGGING_LEVEL=debug    # Logging control
ANONYMIZED_TELEMETRY=false         # Telemetry opt-out
BROWSER_USE_CLOUD_SYNC=true        # Cloud synchronization
SKIP_LLM_API_KEY_VERIFICATION=true # For testing
```

## LLM Integration Patterns

### Multi-Provider Support
Located in `browser_use/llm/` with standardized interface via `BaseChatModel`:
- OpenAI, Anthropic, Google, Groq, Ollama support
- Structured output via Pydantic models
- Token cost tracking in `browser_use/tokens/service.py`

### System Prompts
Agent behavior controlled by markdown files in `browser_use/agent/`:
- `system_prompt.md`: Standard reasoning mode
- `system_prompt_no_thinking.md`: Direct action mode  
- `system_prompt_flash.md`: Optimized for fast models

## Integration Points

### MCP (Model Context Protocol)
Supports both modes via `browser_use/mcp/client.py`:
1. **As MCP Server**: Exposes browser tools to Claude Desktop
2. **With MCP Clients**: Agents connect to external MCP servers (filesystem, GitHub, etc.)

### Cloud Browser Integration
`browser_use/browser/cloud.py` handles remote browser instances:
- Authentication and session management
- Fallback to local browser on cloud failures
- CDPurl resolution for remote connections

## File Organization Conventions

- **Tabs for indentation** (not spaces) in all Python code
- **Modern Python 3.12+ typing**: Use `str | None` instead of `Optional[str]`, `list[str]` instead of `List[str]`
- **Logging methods**: Prefix console logging with `_log_...` (e.g., `_log_pretty_path()`) to separate from business logic
- **Runtime assertions**: Use at function start/end to enforce constraints

## Common Development Gotchas

1. **Model Names**: Use exact model names like `gpt-4o` - don't substitute with `gpt-4`
2. **Async Context**: All main operations are async - use proper async context managers
3. **DOM Processing**: Iframe handling has configurable limits via `BrowserProfile.max_iframes` and `BrowserProfile.max_iframe_depth`
4. **Extension Management**: Extensions are cached in `~/.config/browseruse/extensions` - don't recreate unnecessarily
5. **Event Bus Patterns**:
   - Use `bubus.EventBus` for component communication, not direct method calls
   - Events are FIFO processed but handlers run **serially by default** (`parallel_handlers=False`)
   - Always `await event` after `dispatch(event)` to get results
   - Child events auto-link to parent via context vars (`_current_event_context`)
6. **CDP Session Confusion**: 
   - `session_id` parameter required for tab/frame-specific operations
   - Use `cdp_client.register.Domain.Event()` not `cdp_client.on()`
   - Browser-level operations (Target, Browser domains) don't need session_id
7. **Watchdog Dependencies**: DOM state builds require successful navigation, screenshots need DOM completion
8. **Timeout Hierarchies**:
   - Parent events define timeout scope for child events
   - Child events inherit parent timeout unless explicitly overridden
   - Environment variables like `TIMEOUT_NavigateToUrlEvent=45.0` override defaults
   - Deadlock detection triggers warnings after 15s of handler execution
9. **Handler Execution Order**:
   - Multiple watchdogs for same event execute serially (unless `parallel_handlers=True`)
   - Event queue processes events in FIFO order
   - Context variables automatically track parent-child event relationships
10. **Memory Management**:
    - Event history limited to 50 events by default (`max_history_size`)
    - Completed events auto-cleaned to prevent memory leaks
    - WeakSet references prevent watchdog memory leaks

This architecture enables robust browser automation while maintaining clear separation of concerns and testability.