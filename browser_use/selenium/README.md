# Selenium Browser Backend for browser-use

This module provides a Selenium-based backend for `browser-use`, enabling support for Firefox, Safari, and other browsers not natively compatible with CDP (Chrome DevTools Protocol).

## Architecture

The Selenium backend is designed to **maintain the same event-driven architecture** as the core CDP-based system while providing compatibility with non-Chromium browsers. It uses the same **watchdog/bubus event system** for consistency and interoperability.

### Core Components

1. **`SeleniumSession`**: A wrapper around Selenium WebDriver that provides DOM extraction and browser actions.
2. **`SeleniumBrowserSession`**: An **event-driven adapter** that implements the `BrowserSession` interface and translates browser-use events into Selenium operations.
3. **`SeleniumDomService`**: Extracts the DOM tree using JavaScript injection (reusing the same `index.js` as other non-CDP browsers).
4. **`SeleniumActionService`**: Orchestrates browser actions (click, type, scroll, navigate) using WebDriver APIs.

## Event-Driven Integration

Unlike a polling approach, the Selenium backend maintains full compatibility with browser-use's **event-driven architecture**:

### ✅ **Same as CDP (Chromium)**:
- **Event-driven workflow**: Uses the same `bubus` event bus and watchdog system
- **Agent compatibility**: Works with the standard `Agent` class without modification  
- **Event types**: Handles the same `NavigateToUrlEvent`, `ClickElementEvent`, `BrowserStateRequestEvent`, etc.
- **DOM extraction**: Returns the same `SerializedDOMState` and `EnhancedDOMTreeNode` structures
- **Screenshot support**: Provides screenshots in the same base64 format
- **Multi-step tasks**: Supports the same multi-step agent workflows

### ⚠️ **Different from CDP**:
- **No real-time network events**: Cannot monitor network requests in real-time like CDP
- **No iframe isolation**: Limited iframe support compared to CDP's session-per-frame model
- **WebDriver latency**: Each operation requires a network round-trip to the WebDriver server
- **Browser-specific limitations**: Feature support varies by browser (e.g., Safari has fewer debugging capabilities)
- **JavaScript execution**: DOM analysis relies on injected JavaScript rather than native CDP APIs

## Watchdog Integration

The `SeleniumBrowserSession` registers the same event handlers as CDP sessions:

```python
# Same events, different implementation
BaseWatchdog.attach_handler_to_session(self, NavigateToUrlEvent, self.on_NavigateToUrlEvent)
BaseWatchdog.attach_handler_to_session(self, ClickElementEvent, self.on_ClickElementEvent)
BaseWatchdog.attach_handler_to_session(self, BrowserStateRequestEvent, self.on_BrowserStateRequestEvent)
```

This ensures that **all existing browser-use tools and workflows work unchanged** with Selenium browsers.

## Key Features

- **Cross-Browser Support**: Works with Firefox, Safari, and Chrome via Selenium WebDriver.
- **SauceLabs Integration**: Support for connecting to remote sessions on SauceLabs for cloud testing.
- **Local Browser Support**: Easily launch local browser instances for testing.
- **Event-Driven Design**: Full compatibility with browser-use's watchdog/bubus architecture.
- **Drop-in Replacement**: Use with existing `Agent` class without code changes.

## Usage

### Standard Agent with Selenium Backend

```python
from browser_use.selenium import SeleniumSession
from browser_use.browser.selenium_session import SeleniumBrowserSession
from browser_use.agent.service import Agent
from browser_use import ChatOpenAI

async def main():
    # Create Selenium session
    selenium_session = await SeleniumSession.new_local_session(browser='firefox')
    
    # Wrap in event-driven browser session
    browser_session = SeleniumBrowserSession(selenium_session=selenium_session)
    await browser_session.start()  # Initialize event handlers
    
    # Use with standard Agent - no changes needed!
    agent = Agent(
        task="Find the latest news on Hacker News",
        llm=ChatOpenAI(model="gpt-4"),
        browser_session=browser_session  # Drop-in replacement
    )
    
    result = await agent.run()
    print(result)
    
    await selenium_session.close()
```

### SauceLabs Cloud Testing

```python
from browser_use.selenium import SeleniumSession

# Connect to an existing SauceLabs session
session = await SeleniumSession.connect_to_saucelabs(
    session_id="your-session-id",
    username="SAUCE_USERNAME",
    access_key="SAUCE_ACCESS_KEY",
    region="us-west-1"
)
```

## Event Flow Comparison

### CDP (Chromium) Flow:
```
Agent → Event Bus → DOMWatchdog → CDP Client → Chrome DevTools → Browser
```

### Selenium Flow:
```
Agent → Event Bus → SeleniumBrowserSession → Selenium WebDriver → Browser
```

Both use the **same event types and data structures**, ensuring seamless interoperability.

## Limitations

- **No Real-Time Network Monitoring**: Cannot track network requests/responses in real-time like CDP.
- **Limited Multi-Tab Support**: Basic tab switching compared to CDP's advanced target management.
- **WebDriver Overhead**: Higher latency due to WebDriver protocol vs direct CDP connection.
- **Browser-Specific Features**: Some advanced debugging features may not be available across all browsers.
