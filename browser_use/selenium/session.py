"""
Selenium-based browser session for Firefox and Safari browsers.

This module provides a SeleniumSession class that wraps Selenium WebDriver
and integrates the DOM and action services for use with browser-use agents.
"""

import asyncio
import logging
from typing import TYPE_CHECKING, Literal

from browser_use.selenium.dom_service import SeleniumDomService
from browser_use.selenium.action_service import SeleniumActionService
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
    """

    def __init__(
        self,
        driver: 'WebDriver',
        logger: logging.Logger | None = None,
    ):
        """
        Initialize a SeleniumSession with an existing WebDriver.
        
        Args:
            driver: Selenium WebDriver instance
            logger: Optional logger
        """
        self.driver = driver
        self.logger = logger or logging.getLogger(__name__)
        
        # Initialize services
        self.dom_service = SeleniumDomService(driver, logger=self.logger)
        self.action_service = SeleniumActionService(driver, logger=self.logger)
        
        # State tracking
        self._selector_map: dict[int, EnhancedDOMTreeNode] = {}
        self._cached_dom_state: SerializedDOMState | None = None

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
            logger: Optional logger
            
        Returns:
            SeleniumSession connected to new SauceLabs browser
        """
        _logger = logger or logging.getLogger(__name__)
        _logger.info(f'Creating new SauceLabs {browser} session...')
        
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
                options = webdriver.FirefoxOptions()
                if headless:
                    options.add_argument('--headless')
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
    ) -> tuple[SerializedDOMState, dict[int, EnhancedDOMTreeNode]]:
        """
        Get the current DOM state.
        
        Args:
            highlight_elements: Whether to highlight interactive elements
            use_cache: Whether to return cached state if available
            
        Returns:
            Tuple of (serialized_dom_state, selector_map)
        """
        if use_cache and self._cached_dom_state:
            return self._cached_dom_state, self._selector_map
        
        # Get serialized state AND selector_map in one call to avoid index mismatch
        serialized_state, _, selector_map, timing = await self.dom_service.get_serialized_dom_tree(
            previous_cached_state=self._cached_dom_state,
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

    # ==================== Session Management ====================

    @property
    def session_id(self) -> str:
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
