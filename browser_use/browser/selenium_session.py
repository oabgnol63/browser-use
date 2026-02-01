import asyncio
import logging
from typing import Any, Literal, cast
from uuid_extensions import uuid7str
from pydantic import PrivateAttr

from browser_use.browser.session import BrowserSession
from browser_use.browser.events import (
    BrowserStartEvent,
    NavigateToUrlEvent,
    ClickElementEvent,
    ClickCoordinateEvent,
    TypeTextEvent,
    ScrollEvent,
    BrowserStopEvent,
    GoBackEvent,
    GoForwardEvent,
    RefreshEvent,
    SwitchTabEvent,
    CloseTabEvent,
    BrowserStateRequestEvent,
)
from browser_use.browser.views import BrowserStateSummary, TabInfo
from browser_use.selenium.session import SeleniumSession
from browser_use.dom.views import EnhancedDOMTreeNode, SerializedDOMState

logger = logging.getLogger(__name__)


class SeleniumBrowserSession(BrowserSession):
    """
    Event-driven browser session using Selenium WebDriver.
    
    This class wraps a Selenium session and implements the BrowserSession interface
    so it can be used with the Agent. It bypasses CDP entirely and uses Selenium directly.
    """
    
    _selenium_session: SeleniumSession = PrivateAttr()

    def __init__(self, selenium_session: SeleniumSession, **kwargs):
        # We initialize with a dummy ID if not provided
        kwargs.setdefault('id', str(uuid7str()))
        # CRITICAL: Selenium sessions are local by definition in this context
        kwargs.setdefault('is_local', True)
        super().__init__(**kwargs)
        self._selenium_session = selenium_session
        # Initialize agent_focus_target_id for Selenium (not CDP-based)
        self.agent_focus_target_id = "selenium-page-0"
        self._original_viewport_size = (1280, 720)

    def model_post_init(self, __context) -> None:
        """Register Selenium-specific event handlers."""
        # Initialize connection lock needed by base class or handlers
        self._connection_lock = asyncio.Lock()
        
        from browser_use.browser.watchdog_base import BaseWatchdog
        
        # Register core handlers - override CDP-based ones with Selenium implementations
        BaseWatchdog.attach_handler_to_session(self, BrowserStartEvent, self.on_BrowserStartEvent)
        BaseWatchdog.attach_handler_to_session(self, BrowserStopEvent, self.on_BrowserStopEvent)
        BaseWatchdog.attach_handler_to_session(self, NavigateToUrlEvent, self.on_NavigateToUrlEvent)
        BaseWatchdog.attach_handler_to_session(self, ClickElementEvent, self.on_ClickElementEvent)
        BaseWatchdog.attach_handler_to_session(self, ClickCoordinateEvent, self.on_ClickCoordinateEvent)
        BaseWatchdog.attach_handler_to_session(self, TypeTextEvent, self.on_TypeTextEvent)
        BaseWatchdog.attach_handler_to_session(self, ScrollEvent, self.on_ScrollEvent)
        BaseWatchdog.attach_handler_to_session(self, GoBackEvent, self.on_GoBackEvent)
        BaseWatchdog.attach_handler_to_session(self, GoForwardEvent, self.on_GoForwardEvent)
        BaseWatchdog.attach_handler_to_session(self, RefreshEvent, self.on_RefreshEvent)
        BaseWatchdog.attach_handler_to_session(self, SwitchTabEvent, self.on_SwitchTabEvent)
        BaseWatchdog.attach_handler_to_session(self, CloseTabEvent, self.on_CloseTabEvent)
        BaseWatchdog.attach_handler_to_session(self, BrowserStateRequestEvent, self.on_BrowserStateRequestEvent)

    # ==================== Event Handlers ====================

    async def on_BrowserStartEvent(self, event: BrowserStartEvent) -> dict[str, str]:
        """Handle browser start - initialize Selenium session state."""
        self.logger.debug("SeleniumBrowserSession: Handling BrowserStartEvent")
        # Initialize required state for tools that expect browser to be "connected"
        self.agent_focus_target_id = "selenium-page-0"
        # Return success - Selenium is already running since we created the session externally
        return {"type": "selenium", "session_id": self._selenium_session.session_id}

    async def on_NavigateToUrlEvent(self, event: NavigateToUrlEvent) -> None:
        self.logger.info(f"Selenium navigating to: {event.url}")
        await self._selenium_session.navigate(event.url)

    async def on_ClickElementEvent(self, event: ClickElementEvent) -> dict:
        # Check if element is in an iframe and use auto-handling
        return await self._selenium_session.action_service.click_element_auto(
            event.node, 
            self._cached_selector_map
        )

    async def on_ClickCoordinateEvent(self, event: ClickCoordinateEvent) -> dict:
        return await self._selenium_session.click_coordinates(event.coordinate_x, event.coordinate_y)

    async def on_TypeTextEvent(self, event: TypeTextEvent) -> dict:
        # Check if element is in an iframe and use auto-handling
        return await self._selenium_session.action_service.type_text_auto(
            element_node=event.node, 
            text=event.text, 
            clear_first=event.clear
        )

    async def on_ScrollEvent(self, event: ScrollEvent) -> dict:
        return await self._selenium_session.action_service.scroll(
            direction=event.direction, 
            amount=event.amount, 
            element_node=event.node
        )

    async def on_BrowserStopEvent(self, event: BrowserStopEvent) -> None:
        if event.force:
            await self._selenium_session.close()

    async def on_GoBackEvent(self, event: GoBackEvent) -> None:
        await asyncio.get_event_loop().run_in_executor(None, self._selenium_session.driver.back)

    async def on_GoForwardEvent(self, event: GoForwardEvent) -> None:
        await asyncio.get_event_loop().run_in_executor(None, self._selenium_session.driver.forward)

    async def on_RefreshEvent(self, event: RefreshEvent) -> None:
        await asyncio.get_event_loop().run_in_executor(None, self._selenium_session.driver.refresh)

    async def on_SwitchTabEvent(self, event: SwitchTabEvent) -> str:
        # Limited multi-tab support for now
        self.logger.warning("SeleniumBrowserSession: SwitchTabEvent has limited support")
        return cast(str, self.agent_focus_target_id)

    async def on_CloseTabEvent(self, event: CloseTabEvent) -> None:
        self.logger.warning("SeleniumBrowserSession: CloseTabEvent has limited support")

    async def on_BrowserStateRequestEvent(self, event: BrowserStateRequestEvent) -> BrowserStateSummary:
        """Handle browser state requests by returning the current Selenium state."""
        return await self.get_state()

    # ==================== Override Core Methods ====================

    async def get_dom_state(
        self,
        highlight_elements: bool = True,
        use_cache: bool = False,
        include_iframes: bool = True,
        skip_processing_iframes: bool = False,
    ) -> tuple[SerializedDOMState, dict[int, EnhancedDOMTreeNode]]:
        """
        Get the current DOM state from the Selenium session.
        
        Args:
            highlight_elements: Whether to highlight interactive elements
            use_cache: Whether to return cached state if available
            include_iframes: Whether to include elements from iframes (default True)
            skip_processing_iframes: Skip iframe discovery and DOM extraction from iframes,
                returning only the main page DOM
            
        Returns:
            Tuple of (serialized_dom_state, selector_map)
        """
        state, selector_map = await self._selenium_session.get_dom_state(
            highlight_elements=highlight_elements,
            use_cache=use_cache,
            include_iframes=include_iframes,
            skip_processing_iframes=skip_processing_iframes,
        )
        self._cached_selector_map = selector_map
        return state, selector_map

    async def get_element_by_index(self, index: int) -> EnhancedDOMTreeNode | None:
        return self._selenium_session.get_element_by_index(index)

    async def get_current_page_url(self) -> str:
        return self._selenium_session.current_url

    async def take_screenshot(
        self, 
        path: str | None = None, 
        full_page: bool = False, 
        format: str = 'png', 
        quality: int | None = None, 
        clip: dict | None = None
    ) -> bytes:
        # Selenium basic screenshot doesn't support quality/clip easily without extra work
        screenshot = await self._selenium_session.take_screenshot()
        if path:
            with open(path, 'wb') as f:
                f.write(screenshot)
        return screenshot

    async def get_target_id_from_tab_id(self, tab_id: str) -> str:
        return cast(str, self.agent_focus_target_id)

    async def get_state(self, include_dom: bool = True, include_screenshot: bool = True) -> BrowserStateSummary:
        """Get summarized browser state."""
        from browser_use.browser.views import PageInfo
        
        page_info_dict = await self._selenium_session.get_page_info()
        
        # Get detailed scroll/viewport information from Selenium
        try:
            scroll_info = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self._selenium_session.driver.execute_script('''
                    return {
                        scrollX: window.scrollX || window.pageXOffset || 0,
                        scrollY: window.scrollY || window.pageYOffset || 0,
                        viewportWidth: window.innerWidth,
                        viewportHeight: window.innerHeight,
                        pageWidth: Math.max(
                            document.body.scrollWidth || 0,
                            document.documentElement.scrollWidth || 0
                        ),
                        pageHeight: Math.max(
                            document.body.scrollHeight || 0,
                            document.documentElement.scrollHeight || 0
                        )
                    };
                ''')
            )
            
            # Calculate pixels above/below viewport
            # Convert to int since JavaScript can return float values for scroll positions
            scroll_x = int(scroll_info['scrollX'])
            scroll_y = int(scroll_info['scrollY'])
            viewport_width = int(scroll_info['viewportWidth'])
            viewport_height = int(scroll_info['viewportHeight'])
            page_width = int(scroll_info['pageWidth'])
            page_height = int(scroll_info['pageHeight'])
            
            pixels_above = scroll_y
            pixels_below = max(0, page_height - viewport_height - scroll_y)
            
            page_info = PageInfo(
                viewport_width=viewport_width,
                viewport_height=viewport_height,
                page_width=page_width,
                page_height=page_height,
                scroll_x=scroll_x,
                scroll_y=scroll_y,
                pixels_above=pixels_above,
                pixels_below=pixels_below,
                pixels_left=scroll_x,
                pixels_right=max(0, page_width - viewport_width - scroll_x),
            )
        except Exception as e:
            self.logger.debug(f'Failed to get scroll info: {e}')
            # Fallback to default viewport dimensions
            viewport = page_info_dict.get('viewport') or {}
            page_info = PageInfo(
                viewport_width=viewport.get('width', 1280) if viewport else 1280,
                viewport_height=viewport.get('height', 720) if viewport else 720,
                page_width=viewport.get('width', 1280) if viewport else 1280,
                page_height=viewport.get('height', 720) if viewport else 720,
                scroll_x=0,
                scroll_y=0,
                pixels_above=0,
                pixels_below=0,
                pixels_left=0,
                pixels_right=0,
            )
        
        # We need a dummy DOM state if not included
        if include_dom:
            dom_state, _ = await self.get_dom_state()
        else:
            from browser_use.dom.views import SerializedDOMState
            dom_state = SerializedDOMState(_root=None, selector_map={})

        screenshot_b64 = None
        if include_screenshot:
            import base64
            screenshot_bytes = await self.take_screenshot()
            screenshot_b64 = base64.b64encode(screenshot_bytes).decode('utf-8')

        tab_info = TabInfo(
            url=page_info_dict['url'],
            title=page_info_dict['title'],
            target_id=cast(str, self.agent_focus_target_id)
        )

        return BrowserStateSummary(
            dom_state=dom_state,
            url=page_info_dict['url'],
            title=page_info_dict['title'],
            tabs=[tab_info],
            screenshot=screenshot_b64,
            page_info=page_info,
        )

    # ==================== CDP Client Compatibility ====================
    # These properties/methods are accessed by tools that expect CDP client
    
    @property
    def cdp_client(self):
        """
        Return a mock/stub CDP client for Selenium compatibility.
        
        Tools that check for CDP client existence will now pass.
        Actual Selenium operations bypass CDP entirely.
        """
        # Return self so property checks work, but operations use Selenium
        return self

    async def get_or_create_cdp_session(self, target_id=None, focus=True):
        """
        Return a mock CDP session for Selenium compatibility.
        
        For Selenium, we don't use real CDP sessions. This method exists
        to satisfy tools that check for session existence.
        """
        # Return a mock session-like object
        class MockCDPSession:
            def __init__(self, browser_session):
                self.browser_session = browser_session
                self.session_id = "selenium-session"
                self.target_id = browser_session.agent_focus_target_id
                
                # Create a mock cdp_client that has common methods tools expect
                self.cdp_client = MockCDPClient(browser_session)
        
        # Separate domain classes to avoid method name conflicts
        class MockDOMDomain:
            """Mock for CDP DOM domain."""
            def __init__(self, browser_session):
                self.browser_session = browser_session

            async def getContentQuads(self, params=None, session_id=None):
                return {}
            async def getBoxModel(self, params=None, session_id=None):
                return {}
            async def describeNode(self, params=None, session_id=None):
                return {}
            async def resolveNode(self, params=None, session_id=None):
                return {}
            async def getNodeForLocation(self, params=None, session_id=None):
                return {}
            async def getDocument(self, params=None, session_id=None):
                return {}
            async def querySelector(self, params=None, session_id=None):
                return {}
            async def dom_enable(self, params=None, session_id=None):
                return {}
            async def dom_disable(self, params=None, session_id=None):
                return {}
            async def getFrameOwner(self, params=None, session_id=None):
                return {}
        
        class MockRuntimeDomain:
            """Mock for CDP Runtime domain."""
            def __init__(self, browser_session):
                self.browser_session = browser_session

            async def evaluate(self, params=None, session_id=None):
                expression = params.get('expression') if params else None
                if not expression:
                    return {}
                try:
                    # Run in thread pool as it's a blocking Selenium call
                    result = await asyncio.get_event_loop().run_in_executor(
                        None, lambda: self.browser_session._selenium_session.driver.execute_script(f"return {expression}")
                    )
                    return {'result': {'value': result}}
                except Exception:
                    return {'result': {'value': None}}

            async def callFunctionOn(self, params=None, session_id=None):
                return {}
            async def runIfWaitingForDebugger(self, params=None, session_id=None):
                return {}
            async def releaseObject(self, params=None, session_id=None):
                return {}
        
        class MockPageDomain:
            """Mock for CDP Page domain."""
            def __init__(self, browser_session):
                self.browser_session = browser_session

            async def getLayoutMetrics(self, params=None, session_id=None):
                try:
                    # Fetch real viewport height from selenium if possible
                    info = await self.browser_session._selenium_session.get_page_info()
                    viewport = info.get('viewport', {})
                    width = viewport.get('width', 1280)
                    height = viewport.get('height', 720)
                except Exception:
                    width, height = 1280, 720

                return {
                    'cssVisualViewport': {
                        'clientWidth': width,
                        'clientHeight': height,
                        'pageX': 0,
                        'pageY': 0,
                    },
                    'cssLayoutViewport': {
                        'clientWidth': width,
                        'clientHeight': height,
                        'pageX': 0,
                        'pageY': 0,
                    }
                }

            async def navigate(self, params=None, session_id=None):
                return {}
            async def getFrameTree(self, params=None, session_id=None):
                return {}
            async def captureScreenshot(self, params=None, session_id=None):
                return {}
            async def addScriptToEvaluateOnNewDocument(self, params=None, session_id=None):
                return {'identifier': 'mock-script-id'}
            async def removeScriptToEvaluateOnNewDocument(self, params=None, session_id=None):
                return {}
        
        class MockEmulationDomain:
            """Mock for CDP Emulation domain."""
            def __init__(self, browser_session):
                self.browser_session = browser_session

            async def setDeviceMetricsOverride(self, params=None, session_id=None):
                return {}
            async def clearGeolocationOverride(self, params=None, session_id=None):
                return {}
            async def setGeolocationOverride(self, params=None, session_id=None):
                return {}
        
        class MockStorageDomain:
            """Mock for CDP Storage domain."""
            def __init__(self, browser_session):
                self.browser_session = browser_session

            async def getCookies(self, params=None, session_id=None):
                try:
                    cookies = await asyncio.get_event_loop().run_in_executor(
                        None, lambda: self.browser_session._selenium_session.driver.get_cookies()
                    )
                    return {'cookies': cookies}
                except Exception:
                    return {'cookies': []}

            async def setCookies(self, params=None, session_id=None):
                return {}

            async def clearCookies(self, params=None, session_id=None):
                try:
                    await asyncio.get_event_loop().run_in_executor(
                        None, self.browser_session._selenium_session.driver.delete_all_cookies
                    )
                    return {}
                except Exception:
                    return {}
        
        class MockNetworkDomain:
            """Mock for CDP Network domain."""
            def __init__(self, browser_session):
                self.browser_session = browser_session

            async def clearBrowserCookies(self, params=None, session_id=None):
                try:
                    await asyncio.get_event_loop().run_in_executor(
                        None, self.browser_session._selenium_session.driver.delete_all_cookies
                    )
                    return {}
                except Exception:
                    return {}

            async def network_getCookies(self, params=None, session_id=None):
                try:
                    cookies = await asyncio.get_event_loop().run_in_executor(
                        None, lambda: self.browser_session._selenium_session.driver.get_cookies()
                    )
                    return {'cookies': cookies}
                except Exception:
                    return {'cookies': []}
        
        class MockTargetDomain:
            """Mock for CDP Target domain."""
            def __init__(self, browser_session):
                self.browser_session = browser_session

            async def createTarget(self, params=None, session_id=None):
                return {'targetId': 'mock-target-id'}
            async def closeTarget(self, params=None, session_id=None):
                return {}
            async def activateTarget(self, params=None, session_id=None):
                return {}
            async def setAutoAttach(self, params=None, session_id=None):
                return {}
        
        class MockFetchDomain:
            """Mock for CDP Fetch domain."""
            def __init__(self, browser_session):
                self.browser_session = browser_session

            async def fetch_enable(self, params=None, session_id=None):
                return {}
            async def continueWithAuth(self, params=None, session_id=None):
                return {}
            async def continueRequest(self, params=None, session_id=None):
                return {}
        
        class MockDOMStorageDomain:
            """Mock for CDP DOMStorage domain."""
            def __init__(self, browser_session):
                self.browser_session = browser_session

            async def getDOMStorageItems(self, params=None, session_id=None):
                return {'entries': []}
            async def domstorage_enable(self, params=None, session_id=None):
                return {}
            async def domstorage_disable(self, params=None, session_id=None):
                return {}
        
        class MockCDPClient:
            """Mock CDP client that supports .send.DOMAIN.method() pattern."""
            def __init__(self, browser_session):
                self.send = MockCDPSendProxy(browser_session)
            
            def register(self, event, callback):
                """Stub for event registration - not used with Selenium."""
                pass
        
        class MockCDPSendProxy:
            """Proxy that returns domain objects for .DOM.method() calls."""
            def __init__(self, browser_session):
                self._browser_session = browser_session
            
            @property
            def DOM(self):
                return MockDOMDomain(self._browser_session)
            
            @property
            def Runtime(self):
                return MockRuntimeDomain(self._browser_session)
            
            @property
            def Page(self):
                return MockPageDomain(self._browser_session)
            
            @property
            def Emulation(self):
                return MockEmulationDomain(self._browser_session)
            
            @property
            def Storage(self):
                return MockStorageDomain(self._browser_session)
            
            @property
            def Network(self):
                return MockNetworkDomain(self._browser_session)
            
            @property
            def Target(self):
                return MockTargetDomain(self._browser_session)
            
            @property
            def Fetch(self):
                return MockFetchDomain(self._browser_session)
            
            @property
            def DOMStorage(self):
                return MockDOMStorageDomain(self._browser_session)
            
            @property
            def Overlay(self):
                """Return Overlay domain mock (stub)."""
                class MockOverlayDomain:
                    async def highlightFrame(self, params=None, session_id=None):
                        return {}
                return MockOverlayDomain()
            
            @property
            def Log(self):
                """Return Log domain mock (stub)."""
                class MockLogDomain:
                    async def enable(self, params=None, session_id=None):
                        return {}
                return MockLogDomain()
            
            @property
            def Console(self):
                """Return Console domain mock (stub)."""
                class MockConsoleDomain:
                    async def enable(self, params=None, session_id=None):
                        return {}
                return MockConsoleDomain()
        
        return MockCDPSession(self)
