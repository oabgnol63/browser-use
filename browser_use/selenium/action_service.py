"""
Selenium-based action service for Firefox and Safari browsers.

This service provides browser action handlers using Selenium WebDriver,
replacing the CDP-based DefaultActionWatchdog for non-Chromium browsers.
"""

import asyncio
import logging
import time
from typing import TYPE_CHECKING

from browser_use.dom.views import EnhancedDOMTreeNode

if TYPE_CHECKING:
    from selenium.webdriver.remote.webdriver import WebDriver
    from selenium.webdriver.remote.webelement import WebElement


class SeleniumActionService:
    """
    Action service for Firefox and Safari browsers using Selenium WebDriver.
    
    Provides click, type, scroll, and navigation actions using standard WebDriver
    APIs instead of CDP.
    """

    def __init__(
        self,
        driver: 'WebDriver',
        logger: logging.Logger | None = None,
    ):
        self.driver = driver
        self.logger = logger or logging.getLogger(__name__)

    async def navigate(self, url: str, wait_until_loaded: bool = True) -> dict:
        """
        Navigate to a URL.
        
        Args:
            url: The URL to navigate to
            wait_until_loaded: Whether to wait for page load
            
        Returns:
            Dict with navigation result
        """
        start_time = time.time()
        self.logger.info(f'Navigating to: {url}')
        
        try:
            # Run in thread pool to avoid blocking
            await asyncio.get_event_loop().run_in_executor(
                None, self.driver.get, url
            )
            
            if wait_until_loaded:
                # Wait for document ready state
                await self._wait_for_page_load()
            
            elapsed = time.time() - start_time
            self.logger.debug(f'Navigation completed in {elapsed:.2f}s')
            
            return {
                'success': True,
                'url': self.driver.current_url,
                'title': self.driver.title,
                'elapsed_ms': elapsed * 1000,
            }
        except Exception as e:
            self.logger.error(f'Navigation failed: {e}')
            raise

    async def click_element(
        self,
        element_node: EnhancedDOMTreeNode,
        selector_map: dict[int, EnhancedDOMTreeNode] | None = None,
    ) -> dict:
        """
        Click an element using its xpath from the DOM tree.
        
        Args:
            element_node: The DOM element to click
            selector_map: Optional selector map for index-based lookup
            
        Returns:
            Dict with click result
        """
        from selenium.webdriver.common.by import By
        from selenium.webdriver.common.action_chains import ActionChains
        
        xpath = element_node.attributes.get('xpath') or self._generate_xpath(element_node)
        self.logger.debug(f'Clicking element with xpath: {xpath}')
        
        try:
            # Find element by xpath
            element = await asyncio.get_event_loop().run_in_executor(
                None, lambda: self.driver.find_element(By.XPATH, xpath)
            )
            
            # Scroll element into view
            await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self.driver.execute_script(
                    "arguments[0].scrollIntoView({block: 'center'});", element
                )
            )
            
            # Small delay for scroll to complete
            await asyncio.sleep(0.1)
            
            # Click using ActionChains for better reliability
            def do_click():
                actions = ActionChains(self.driver)
                actions.move_to_element(element).click().perform()
            
            await asyncio.get_event_loop().run_in_executor(None, do_click)
            
            self.logger.debug('Click successful')
            return {
                'success': True,
                'xpath': xpath,
                'tag_name': element_node.node_name,
            }
        except Exception as e:
            self.logger.error(f'Click failed: {e}')
            raise

    async def click_coordinates(self, x: int, y: int) -> dict:
        """
        Click at specific coordinates.
        
        Args:
            x: X coordinate
            y: Y coordinate
            
        Returns:
            Dict with click result
        """
        from selenium.webdriver.common.action_chains import ActionChains
        
        self.logger.debug(f'Clicking at coordinates: ({x}, {y})')
        
        try:
            def do_click():
                actions = ActionChains(self.driver)
                # Move to body element first, then offset
                body = self.driver.find_element("tag name", "body")
                actions.move_to_element_with_offset(body, x, y).click().perform()
            
            await asyncio.get_event_loop().run_in_executor(None, do_click)
            
            return {
                'success': True,
                'x': x,
                'y': y,
            }
        except Exception as e:
            self.logger.error(f'Coordinate click failed: {e}')
            raise

    async def type_text(
        self,
        element_node: EnhancedDOMTreeNode | None,
        text: str,
        clear_first: bool = True,
    ) -> dict:
        """
        Type text into an element or the active element.
        
        Args:
            element_node: The DOM element to type into (None for active element)
            text: The text to type
            clear_first: Whether to clear the field first
            
        Returns:
            Dict with type result
        """
        from selenium.webdriver.common.by import By
        from selenium.webdriver.common.keys import Keys
        
        self.logger.debug(f'Typing text: {text[:20]}...' if len(text) > 20 else f'Typing text: {text}')
        
        try:
            element = None
            
            if element_node:
                xpath = element_node.attributes.get('xpath') or self._generate_xpath(element_node)
                element = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: self.driver.find_element(By.XPATH, xpath)
                )
            else:
                # Use active element
                element = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: self.driver.switch_to.active_element
                )
            
            if clear_first:
                await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: element.send_keys(Keys.CONTROL + 'a')
                )
                await asyncio.sleep(0.05)
            
            await asyncio.get_event_loop().run_in_executor(
                None, lambda: element.send_keys(text)
            )
            
            self.logger.debug('Type successful')
            return {
                'success': True,
                'text_length': len(text),
            }
        except Exception as e:
            self.logger.error(f'Type failed: {e}')
            raise

    async def scroll(
        self,
        direction: str = 'down',
        amount: int = 300,
        element_node: EnhancedDOMTreeNode | None = None,
    ) -> dict:
        """
        Scroll the page or an element.
        
        Args:
            direction: 'up', 'down', 'left', or 'right'
            amount: Number of pixels to scroll
            element_node: Optional specific element to scroll
            
        Returns:
            Dict with scroll result
        """
        self.logger.debug(f'Scrolling {direction} by {amount}px')
        
        scroll_x = 0
        scroll_y = 0
        
        if direction == 'down':
            scroll_y = amount
        elif direction == 'up':
            scroll_y = -amount
        elif direction == 'right':
            scroll_x = amount
        elif direction == 'left':
            scroll_x = -amount
        
        try:
            if element_node:
                xpath = element_node.attributes.get('xpath') or self._generate_xpath(element_node)
                script = f"""
                    var element = document.evaluate('{xpath}', document, null, 
                        XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
                    if (element) {{
                        element.scrollBy({scroll_x}, {scroll_y});
                        return true;
                    }}
                    return false;
                """
            else:
                script = f"window.scrollBy({scroll_x}, {scroll_y}); return true;"
            
            result = await asyncio.get_event_loop().run_in_executor(
                None, lambda: self.driver.execute_script(script)
            )
            
            return {
                'success': result,
                'direction': direction,
                'amount': amount,
            }
        except Exception as e:
            self.logger.error(f'Scroll failed: {e}')
            raise

    async def take_screenshot(self) -> bytes:
        """
        Take a screenshot of the current page.
        
        Returns:
            PNG screenshot as bytes
        """
        self.logger.debug('Taking screenshot')
        
        try:
            screenshot = await asyncio.get_event_loop().run_in_executor(
                None, self.driver.get_screenshot_as_png
            )
            return screenshot
        except Exception as e:
            self.logger.error(f'Screenshot failed: {e}')
            raise

    async def get_page_info(self) -> dict:
        """
        Get current page information.
        
        Returns:
            Dict with URL, title, and viewport info
        """
        try:
            info = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: {
                    'url': self.driver.current_url,
                    'title': self.driver.title,
                    'viewport': self.driver.execute_script(
                        'return {width: window.innerWidth, height: window.innerHeight}'
                    ),
                }
            )
            return info
        except Exception as e:
            self.logger.error(f'Get page info failed: {e}')
            raise

    async def _wait_for_page_load(self, timeout: float = 30.0):
        """Wait for the page to finish loading."""
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            ready_state = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self.driver.execute_script('return document.readyState')
            )
            
            if ready_state == 'complete':
                return
            
            await asyncio.sleep(0.1)
        
        self.logger.warning(f'Page load timeout after {timeout}s')

    def _generate_xpath(self, element_node: EnhancedDOMTreeNode) -> str:
        """Generate an XPath for an element from its attributes."""
        attrs = element_node.attributes
        tag = element_node.node_name.lower()
        
        # Try ID first
        if 'id' in attrs and attrs['id']:
            return f'//*[@id="{attrs["id"]}"]'
        
        # Try existing xpath attribute
        if 'xpath' in attrs:
            return attrs['xpath']
        
        # Build xpath from attributes
        predicates = []
        
        if 'class' in attrs and attrs['class']:
            # Use contains for class matching
            predicates.append(f'contains(@class, "{attrs["class"].split()[0]}")')
        
        if 'name' in attrs:
            predicates.append(f'@name="{attrs["name"]}"')
        
        if 'type' in attrs:
            predicates.append(f'@type="{attrs["type"]}"')
        
        if predicates:
            return f'//{tag}[{" and ".join(predicates)}]'
        
        return f'//{tag}'
