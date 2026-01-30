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
        return await self._selenium_session.click_element(event.node)

    async def on_ClickCoordinateEvent(self, event: ClickCoordinateEvent) -> dict:
        return await self._selenium_session.click_coordinates(event.coordinate_x, event.coordinate_y)

    async def on_TypeTextEvent(self, event: TypeTextEvent) -> dict:
        return await self._selenium_session.action_service.type_text(
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
    ) -> tuple[SerializedDOMState, dict[int, EnhancedDOMTreeNode]]:
        state, selector_map = await self._selenium_session.get_dom_state(
            highlight_elements=highlight_elements,
            use_cache=use_cache
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
        page_info = await self._selenium_session.get_page_info()
        
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
            url=page_info['url'],
            title=page_info['title'],
            target_id=cast(str, self.agent_focus_target_id)
        )

        return BrowserStateSummary(
            dom_state=dom_state,
            url=page_info['url'],
            title=page_info['title'],
            tabs=[tab_info],
            screenshot=screenshot_b64,
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
                self.cdp_client = MockCDPClient()
        
        # Separate domain classes to avoid method name conflicts
        class MockDOMDomain:
            """Mock for CDP DOM domain."""
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
            async def evaluate(self, params=None, session_id=None):
                return {}
            async def callFunctionOn(self, params=None, session_id=None):
                return {}
            async def runIfWaitingForDebugger(self, params=None, session_id=None):
                return {}
        
        class MockPageDomain:
            """Mock for CDP Page domain."""
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
            async def setDeviceMetricsOverride(self, params=None, session_id=None):
                return {}
            async def clearGeolocationOverride(self, params=None, session_id=None):
                return {}
            async def setGeolocationOverride(self, params=None, session_id=None):
                return {}
        
        class MockStorageDomain:
            """Mock for CDP Storage domain."""
            async def getCookies(self, params=None, session_id=None):
                return {'cookies': []}
            async def setCookies(self, params=None, session_id=None):
                return {}
            async def clearCookies(self, params=None, session_id=None):
                return {}
        
        class MockNetworkDomain:
            """Mock for CDP Network domain."""
            async def clearBrowserCookies(self, params=None, session_id=None):
                return {}
            async def network_getCookies(self, params=None, session_id=None):
                return {'cookies': []}
        
        class MockTargetDomain:
            """Mock for CDP Target domain."""
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
            async def fetch_enable(self, params=None, session_id=None):
                return {}
            async def continueWithAuth(self, params=None, session_id=None):
                return {}
            async def continueRequest(self, params=None, session_id=None):
                return {}
        
        class MockDOMStorageDomain:
            """Mock for CDP DOMStorage domain."""
            async def getDOMStorageItems(self, params=None, session_id=None):
                return {'entries': []}
            async def domstorage_enable(self, params=None, session_id=None):
                return {}
            async def domstorage_disable(self, params=None, session_id=None):
                return {}
        
        class MockCDPClient:
            """Mock CDP client that supports .send.DOMAIN.method() pattern."""
            def __init__(self):
                self.send = MockCDPSendProxy(self)
            
            def register(self, event, callback):
                """Stub for event registration - not used with Selenium."""
                pass
        
        class MockCDPSendProxy:
            """Proxy that returns domain objects for .DOM.method() calls."""
            def __init__(self, cdp_client):
                self._cdp_client = cdp_client
            
            @property
            def DOM(self):
                return MockDOMDomain()
            
            @property
            def Runtime(self):
                return MockRuntimeDomain()
            
            @property
            def Page(self):
                return MockPageDomain()
            
            @property
            def Emulation(self):
                return MockEmulationDomain()
            
            @property
            def Storage(self):
                return MockStorageDomain()
            
            @property
            def Network(self):
                return MockNetworkDomain()
            
            @property
            def Target(self):
                return MockTargetDomain()
            
            @property
            def Fetch(self):
                return MockFetchDomain()
            
            @property
            def DOMStorage(self):
                return MockDOMStorageDomain()
            
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
