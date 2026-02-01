"""
Selenium-based browser session for Firefox and Safari browsers.

This module provides a SeleniumSession class that wraps Selenium WebDriver
and integrates the DOM and action services for use with browser-use agents.

Enhanced iframe support:
- Same-origin iframes: Full DOM extraction and element interaction
- Cross-origin iframes: Coordinate-based interaction and metadata
- Automatic iframe context management
"""

import asyncio
import logging
from typing import TYPE_CHECKING, Any, Literal

from browser_use.selenium.dom_service import SeleniumDomService
from browser_use.selenium.action_service import SeleniumActionService
from browser_use.selenium.iframe_handler import SeleniumIframeHandler, IframeInfo
from browser_use.selenium.saucelabs import (
    create_saucelabs_session,
    connect_to_saucelabs_session,
    get_saucelabs_credentials,
)
from browser_use.dom.views import EnhancedDOMTreeNode, SerializedDOMState

if TYPE_CHECKING:
    from selenium.webdriver.remote.webdriver import WebDriver


class SeleniumSession:
    """
    Browser session using Selenium WebDriver for Firefox and Safari support.
    
    This class provides an interface compatible with the browser-use agent,
    allowing Firefox and Safari browsers to be controlled via Selenium/WebDriver.
    
    Usage:
        # Start new SauceLabs Firefox session
        session = await SeleniumSession.new_saucelabs_session(browser='firefox')
        
        # Or connect to existing session
        session = await SeleniumSession.connect_to_saucelabs(session_id='your-session-id')
        
        # Use with agent
        await session.navigate('https://example.com')
        dom = await session.get_dom_state()
        
        # Access iframes
        iframes = await session.get_all_iframes()
        await session.click_in_iframe('iframe#login', 'button#submit')
    """

    def __init__(
        self,
        driver: 'WebDriver',
        logger: logging.Logger | None = None,
        skip_processing_iframes: bool = False,
    ):
        """
        Initialize a SeleniumSession with an existing WebDriver.
        
        Args:
            driver: Selenium WebDriver instance
            logger: Optional logger
            skip_processing_iframes: Skip iframe discovery and DOM extraction from iframes,
                returning only the main page DOM
        """
        self.driver = driver
        self.logger = logger or logging.getLogger(__name__)
        self.skip_processing_iframes = skip_processing_iframes
        
        # Initialize services
        self.dom_service = SeleniumDomService(
            driver,
            logger=self.logger,
            skip_processing_iframes=skip_processing_iframes,
        )
        self.action_service = SeleniumActionService(driver, logger=self.logger)
        
        # Initialize shared iframe handler (used by both services)
        self.iframe_handler = SeleniumIframeHandler(driver, logger=self.logger)
        
        # State tracking
        self._selector_map: dict[int, EnhancedDOMTreeNode] = {}
        self._cached_dom_state: SerializedDOMState | None = None
        self._iframe_info_cache: dict[str, IframeInfo] = {}

    @classmethod
    async def new_saucelabs_session(
        cls,
        browser: Literal['firefox', 'safari'] = 'firefox',
        browser_version: str = 'latest',
        platform: str = 'Windows 10',
        test_name: str = 'browser-use-session',
        region: str = 'us-west',
        username: str | None = None,
        access_key: str | None = None,
        stealth: bool = True,
        logger: logging.Logger | None = None,
    ) -> 'SeleniumSession':
        """
        Create a new SauceLabs browser session.

        Args:
            browser: Browser type ('firefox' or 'safari')
            browser_version: Browser version
            platform: Operating system
            test_name: Name for the session
            region: SauceLabs region
            username: SauceLabs username (or use SAUCE_USERNAME env)
            access_key: SauceLabs access key (or use SAUCE_ACCESS_KEY env)
            stealth: Apply stealth preferences to avoid CAPTCHA/detection (default: True)
            logger: Optional logger

        Returns:
            SeleniumSession connected to new SauceLabs browser
        """
        _logger = logger or logging.getLogger(__name__)
        _logger.info(f'Creating new SauceLabs {browser} session (stealth={stealth})...')

        # Create driver in thread pool to avoid blocking
        driver = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: create_saucelabs_session(
                browser=browser,
                browser_version=browser_version,
                platform=platform,
                test_name=test_name,
                region=region,
                username=username,
                access_key=access_key,
                stealth=stealth,
            )
        )

        _logger.info(f'SauceLabs session created: {driver.session_id}')
        return cls(driver, logger=_logger)

    @classmethod
    async def connect_to_saucelabs(
        cls,
        session_id: str,
        region: str = 'us-west',
        username: str | None = None,
        access_key: str | None = None,
        logger: logging.Logger | None = None,
    ) -> 'SeleniumSession':
        """
        Connect to an existing SauceLabs session.
        
        Args:
            session_id: The SauceLabs session ID to connect to
            region: SauceLabs region
            username: SauceLabs username (or use SAUCE_USERNAME env)
            access_key: SauceLabs access key (or use SAUCE_ACCESS_KEY env)
            logger: Optional logger
            
        Returns:
            SeleniumSession connected to existing SauceLabs browser
        """
        _logger = logger or logging.getLogger(__name__)
        _logger.info(f'Connecting to SauceLabs session: {session_id}...')
        
        driver = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: connect_to_saucelabs_session(
                session_id=session_id,
                region=region,
                username=username,
                access_key=access_key,
            )
        )
        
        _logger.info('Connected to SauceLabs session')
        return cls(driver, logger=_logger)

    @classmethod
    async def new_local_session(
        cls,
        browser: Literal['firefox', 'safari', 'chrome'] = 'firefox',
        headless: bool = False,
        logger: logging.Logger | None = None,
    ) -> 'SeleniumSession':
        """
        Create a new local browser session.
        
        Args:
            browser: Browser type ('firefox', 'safari', or 'chrome')
            headless: Whether to run in headless mode
            logger: Optional logger
            
        Returns:
            SeleniumSession connected to local browser
        """
        from selenium import webdriver
        
        _logger = logger or logging.getLogger(__name__)
        _logger.info(f'Creating local {browser} session (headless={headless})...')
        
        def create_driver():
            if browser == 'firefox':
                options = cls._make_firefox_options(headless=headless, stealth=True)
                return webdriver.Firefox(options=options)
            elif browser == 'chrome':
                options = webdriver.ChromeOptions()
                if headless:
                    options.add_argument('--headless=new')
                return webdriver.Chrome(options=options)
            elif browser == 'safari':
                # Safari doesn't support headless mode
                return webdriver.Safari()
            else:
                raise ValueError(f'Unsupported browser: {browser}')
        
        driver = await asyncio.get_event_loop().run_in_executor(None, create_driver)
        
        _logger.info(f'Local {browser} session created')
        return cls(driver, logger=_logger)

    @classmethod
    async def from_local_driver(
        cls,
        driver: 'WebDriver',
        logger: logging.Logger | None = None,
    ) -> 'SeleniumSession':
        """
        Create a SeleniumSession from an existing local WebDriver.
        
        Args:
            driver: Existing Selenium WebDriver
            logger: Optional logger
            
        Returns:
            SeleniumSession wrapping the driver
        """
        return cls(driver, logger=logger)

    # ==================== DOM Methods ====================

    async def get_dom_state(
        self,
        highlight_elements: bool = True,
        use_cache: bool = False,
        include_iframes: bool = True,
        skip_processing_iframes: bool = False,
    ) -> tuple[SerializedDOMState, dict[int, EnhancedDOMTreeNode]]:
        """
        Get the current DOM state, optionally including iframe content.
        
        Args:
            highlight_elements: Whether to highlight interactive elements
            use_cache: Whether to return cached state if available
            include_iframes: Whether to include elements from iframes (default True)
            skip_processing_iframes: Skip iframe discovery and DOM extraction from iframes,
                returning only the main page DOM. Overrides include_iframes when True.
            
        Returns:
            Tuple of (serialized_dom_state, selector_map)
        """
        if use_cache and self._cached_dom_state:
            return self._cached_dom_state, self._selector_map
        
        # Use instance-level setting as default if not explicitly provided
        effective_skip_iframes = skip_processing_iframes or self.skip_processing_iframes
        
        if include_iframes and not effective_skip_iframes:
            # Use iframe-aware extraction that merges all iframe content
            main_root, merged_selector_map, iframe_info = await self.dom_service.get_merged_dom_with_iframes(
                highlight_elements=highlight_elements,
                max_iframes=5,
                skip_processing_iframes=effective_skip_iframes,
            )
            
            # Update iframe info cache
            self._iframe_info_cache = iframe_info
            
            # Create serialized state - serialize the main root for the DOM text representation
            from browser_use.dom.serializer.serializer import DOMTreeSerializer
            serializer = DOMTreeSerializer(
                main_root,
                paint_order_filtering=self.dom_service.paint_order_filtering,
                force_contiguous_indices=False,
            )
            serialized_state, _ = serializer.serialize_accessible_elements()
            
            # Override the selector map with our merged map (includes iframe elements)
            serialized_state.selector_map = merged_selector_map
            
            # Update internal node mapping for correct serialization output
            serialized_state._node_to_selector_index = {id(node): idx for idx, node in merged_selector_map.items()}
            
            selector_map = merged_selector_map
            
            self.logger.debug(f'DOM state with iframes: {len(selector_map)} interactive elements')
        else:
            # Get main page only (or when skipping iframes is requested)
            serialized_state, _, selector_map, timing = await self.dom_service.get_serialized_dom_tree(
                highlight_elements=highlight_elements,
                previous_cached_state=self._cached_dom_state,
                skip_processing_iframes=effective_skip_iframes,
            )
        
        # Update selector map and cache
        self._selector_map = selector_map
        self._cached_dom_state = serialized_state
        
        self.logger.debug(f'DOM state captured: {len(self._selector_map)} interactive elements')
        return serialized_state, self._selector_map

    def get_element_by_index(self, index: int) -> EnhancedDOMTreeNode | None:
        """Get an element from the cached selector map by index."""
        return self._selector_map.get(index)

    # ==================== Action Methods ====================

    async def navigate(self, url: str) -> dict:
        """Navigate to a URL."""
        return await self.action_service.navigate(url)

    async def click(self, index: int) -> dict:
        """Click an element by its index in the selector map."""
        element = self.get_element_by_index(index)
        if not element:
            raise ValueError(f'Element with index {index} not found in selector map')
        return await self.action_service.click_element(element, self._selector_map)

    async def click_element(self, element: EnhancedDOMTreeNode) -> dict:
        """Click a specific element."""
        return await self.action_service.click_element(element, self._selector_map)

    async def click_coordinates(self, x: int, y: int) -> dict:
        """Click at specific coordinates."""
        return await self.action_service.click_coordinates(x, y)

    async def type_text(self, text: str, index: int | None = None) -> dict:
        """Type text into an element or the active element."""
        element = self.get_element_by_index(index) if index is not None else None
        return await self.action_service.type_text(element, text)

    async def scroll(
        self,
        direction: str = 'down',
        amount: int = 300,
        index: int | None = None,
    ) -> dict:
        """Scroll the page or a specific element."""
        element = self.get_element_by_index(index) if index is not None else None
        return await self.action_service.scroll(direction, amount, element)

    async def take_screenshot(self) -> bytes:
        """Take a screenshot of the current page."""
        return await self.action_service.take_screenshot()

    async def get_page_info(self) -> dict:
        """Get current page information."""
        return await self.action_service.get_page_info()

    # ==================== Iframe Methods ====================

    async def get_all_iframes(
        self,
        include_nested: bool = True,
        max_depth: int = 5,
    ) -> list[IframeInfo]:
        """
        Get information about all iframes on the page.
        
        Args:
            include_nested: Whether to include nested iframes
            max_depth: Maximum nesting depth to traverse
            
        Returns:
            List of IframeInfo objects with iframe metadata
        """
        iframes = await self.iframe_handler.get_all_iframes(
            include_nested=include_nested,
            max_depth=max_depth,
        )
        
        # Update cache
        self._iframe_info_cache = {
            iframe.selector: iframe for iframe in iframes
        }
        
        return iframes

    async def get_iframe_dom(
        self,
        iframe_selector: str,
        highlight_elements: bool = True,
    ) -> tuple[EnhancedDOMTreeNode | None, dict[int, EnhancedDOMTreeNode]]:
        """
        Get the DOM tree for a specific iframe.
        
        Only works for same-origin iframes. For cross-origin iframes,
        returns (None, {}).
        
        Args:
            iframe_selector: CSS selector or XPath for the iframe
            highlight_elements: Whether to highlight interactive elements
            
        Returns:
            Tuple of (root_node, selector_map)
        """
        return await self.dom_service.get_iframe_dom_tree(
            iframe_selector,
            highlight_elements=highlight_elements,
        )

    async def get_dom_state_with_iframes(
        self,
        highlight_elements: bool = True,
        max_iframes: int = 5,
    ) -> tuple[SerializedDOMState, dict[int, EnhancedDOMTreeNode], dict[str, IframeInfo]]:
        """
        Get DOM state including elements from same-origin iframes.
        
        This provides a unified view of the main page and iframe content,
        with merged selector maps for seamless interaction.
        
        Args:
            highlight_elements: Whether to highlight interactive elements
            max_iframes: Maximum number of iframes to process
            
        Returns:
            Tuple of (serialized_dom_state, merged_selector_map, iframe_info_map)
        """
        main_root, merged_map, iframe_info = await self.dom_service.get_merged_dom_with_iframes(
            highlight_elements=highlight_elements,
            max_iframes=max_iframes,
        )
        
        # Update selector map with merged content
        self._selector_map = merged_map
        self._iframe_info_cache = iframe_info
        
        # Create serialized state for LLM
        from browser_use.dom.serializer.serializer import DOMTreeSerializer
        serialized_state, _ = DOMTreeSerializer(
            main_root,
            self._cached_dom_state,
            paint_order_filtering=self.dom_service.paint_order_filtering,
        ).serialize_accessible_elements()
        
        serialized_state.selector_map = merged_map
        self._cached_dom_state = serialized_state
        
        return serialized_state, merged_map, iframe_info

    async def click_in_iframe(
        self,
        iframe_selector: str,
        element_selector: str,
    ) -> bool:
        """
        Click an element within a specific iframe.
        
        For same-origin iframes, switches context and clicks.
        For cross-origin iframes, uses coordinate-based clicking.
        
        Args:
            iframe_selector: CSS selector or XPath for the iframe
            element_selector: CSS selector for the element to click
            
        Returns:
            True if click was successful
        """
        return await self.iframe_handler.click_in_frame(
            iframe_selector,
            element_selector,
        )

    async def type_in_iframe(
        self,
        iframe_selector: str,
        element_selector: str,
        text: str,
        clear_first: bool = True,
    ) -> bool:
        """
        Type text into an element within a specific iframe.
        
        Args:
            iframe_selector: CSS selector or XPath for the iframe
            element_selector: CSS selector for the input element
            text: Text to type
            clear_first: Whether to clear the field first
            
        Returns:
            True if typing was successful
        """
        return await self.iframe_handler.type_in_frame(
            iframe_selector,
            element_selector,
            text,
            clear_first=clear_first,
        )

    async def click_cross_origin_iframe(
        self,
        iframe_selector: str,
        x_offset: int = 0,
        y_offset: int = 0,
    ) -> bool:
        """
        Click within a cross-origin iframe using coordinates.
        
        Useful for OAuth popups, login buttons, etc.
        
        Args:
            iframe_selector: CSS selector for the iframe
            x_offset: X offset from iframe's top-left corner
            y_offset: Y offset from iframe's top-left corner
            
        Returns:
            True if click was performed
        """
        return await self.iframe_handler.click_cross_origin_iframe(
            iframe_selector,
            x_offset=x_offset,
            y_offset=y_offset,
        )


    async def execute_in_iframe(
        self,
        iframe_selector: str,
        script: str,
        *args,
    ) -> Any:
        """
        Execute JavaScript within an iframe (same-origin only).
        
        Args:
            iframe_selector: CSS selector for the iframe
            script: JavaScript code to execute
            *args: Arguments to pass to the script
            
        Returns:
            Result of the script execution
        """
        return await self.iframe_handler.execute_in_frame(
            iframe_selector,
            script,
            *args,
        )

    def is_element_in_iframe(self, element: EnhancedDOMTreeNode) -> tuple[bool, str | None]:
        """
        Check if an element is from an iframe.
        
        Args:
            element: The DOM element to check
            
        Returns:
            Tuple of (is_in_iframe, iframe_selector)
        """
        return self.action_service._is_element_in_iframe(element)

    # ==================== Browser Configuration ====================

    @staticmethod
    def _make_firefox_options(headless: bool = False, stealth: bool = True):
        """
        Create Firefox options with stealth configuration to avoid detection.

        Args:
            headless: Whether to run in headless mode
            stealth: Whether to apply stealth preferences to avoid CAPTCHA/detection

        Returns:
            Configured FirefoxOptions
        """
        from selenium import webdriver

        options = webdriver.FirefoxOptions()
        if headless:
            options.add_argument('--headless')

        # Suppress notifications and first-run dialogs
        options.set_preference('dom.webnotifications.enabled', False)
        options.set_preference('toolkit.telemetry.reportingpolicy.firstRun', False)
        options.set_preference('browser.shell.checkDefaultBrowser', False)
        options.set_preference('browser.startup.homepage_override.mstone', 'ignore')

        if stealth:
            # Hide WebDriver detection
            options.set_preference('dom.webdriver.enabled', False)
            options.set_preference('useAutomationExtension', False)

            # Disable navigator.webdriver flag
            options.set_preference('marionette.actors.enabled', True)

            # General privacy settings (avoid fingerprinting detection)
            options.set_preference('privacy.trackingprotection.enabled', False)
            options.set_preference('network.http.sendRefererHeader', 2)
            options.set_preference('general.useragent.override', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0')

            # Disable telemetry that might flag automation
            options.set_preference('toolkit.telemetry.enabled', False)
            options.set_preference('datareporting.healthreport.uploadEnabled', False)
            options.set_preference('datareporting.policy.dataSubmissionEnabled', False)

            # Media/WebRTC settings
            options.set_preference('media.peerconnection.enabled', False)
            options.set_preference('media.navigator.enabled', False)

            # Geolocation
            options.set_preference('geo.enabled', False)

        # Disable DRM/Widevine CDM download popup ("Firefox is installing components...")
        options.set_preference('media.eme.enabled', False)
        options.set_preference('media.gmp-manager.updateEnabled', False)
        options.set_preference('media.gmp-widevinecdm.enabled', False)
        options.set_preference('media.gmp-widevinecdm.visible', False)
        options.set_preference('media.gmp-gmpopenh264.enabled', False)

        return options

    @staticmethod
    def _make_firefox_capabilities(stealth: bool = True) -> dict:
        """
        Create Firefox capabilities for SauceLabs with stealth settings.

        Args:
            stealth: Whether to apply stealth preferences

        Returns:
            Capabilities dict for SauceLabs
        """
        caps = {
            'browserName': 'firefox',
            'moz:firefoxOptions': {
                'prefs': {
                    'dom.webdriver.enabled': False,
                    'useAutomationExtension': False,
                    'security.webdriver_user_requires_override': True,
                    'privacy.resistFingerprinting': stealth,
                }
            }
        }
        return caps

    # ==================== Session Management ====================

    @property
    def session_id(self) -> str | None:
        """Get the WebDriver session ID."""
        return self.driver.session_id

    @property
    def current_url(self) -> str:
        """Get the current URL."""
        return self.driver.current_url

    @property
    def title(self) -> str:
        """Get the current page title."""
        return self.driver.title

    async def close(self):
        """Close the browser session."""
        self.logger.info('Closing Selenium session')
        await asyncio.get_event_loop().run_in_executor(
            None, self.driver.quit
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        await self.close()
