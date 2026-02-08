"""
Selenium-based action service for Firefox and Safari browsers.

This service provides browser action handlers using Selenium WebDriver,
replacing the CDP-based DefaultActionWatchdog for non-Chromium browsers.

Enhanced iframe support:
- Full element interaction in ANY iframe (including cross-origin)
- Selenium WebDriver bypasses browser Same-Origin Policy at automation level
- Automatic frame context switching with element detection
"""

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any

from browser_use.dom.views import EnhancedDOMTreeNode

if TYPE_CHECKING:
    from selenium.webdriver.remote.webdriver import WebDriver
    from selenium.webdriver.remote.webelement import WebElement

from browser_use.selenium.iframe_handler import SeleniumIframeHandler


class SeleniumActionService:
    """
    Action service for Firefox and Safari browsers using Selenium WebDriver.
    
    Provides click, type, scroll, and navigation actions using standard WebDriver
    APIs instead of CDP. Supports full interaction with ALL iframes including
    cross-origin frames.
    """

    def __init__(
        self,
        driver: 'WebDriver',
        logger: logging.Logger | None = None,
    ):
        self.driver = driver
        self.logger = logger or logging.getLogger(__name__)
        
        # Initialize iframe handler for frame context management
        self.iframe_handler = SeleniumIframeHandler(driver, logger=self.logger)

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
        """Generate an XPath for an element from its attributes or DOM structure.
        
        Priority order:
        1. Use ID if available (unique identifier)
        2. Use existing xpath attribute if available (from JS extraction in non-compact mode)
        3. Use the node's xpath property (hierarchical path with sibling positions)
        4. Fall back to attribute-based xpath for edge cases
        """
        attrs = element_node.attributes
        tag = element_node.node_name.lower()
        
        # Try ID first - IDs should be unique on a page
        if 'id' in attrs and attrs['id']:
            return f'//*[@id="{attrs["id"]}"]'
        
        # Try existing xpath attribute (from JavaScript DOM extraction in non-compact mode)
        if 'xpath' in attrs:
            return attrs['xpath']
        
        # Use the node's hierarchical xpath property - this generates a unique path
        # like "/html/body/div[1]/section[2]/a[1]" based on DOM structure
        if element_node.parent_node:
            hierarchical_xpath = element_node.xpath
            if hierarchical_xpath:
                # Prepend '//' to make it an absolute xpath from document root
                return f'//{hierarchical_xpath}'
        
        # Fallback: build xpath from unique attributes (data-testid, name, etc.)
        predicates = []
        
        # Prefer unique identifiers first
        if 'data-testid' in attrs:
            return f'//{tag}[@data-testid="{attrs["data-testid"]}"]'
            
        if 'name' in attrs:
            predicates.append(f'@name="{attrs["name"]}"')
        
        if 'type' in attrs:
            predicates.append(f'@type="{attrs["type"]}"')
            
        if 'role' in attrs:
            predicates.append(f'@role="{attrs["role"]}"')
        
        # Only use class as last resort since it often matches multiple elements
        if not predicates and 'class' in attrs and attrs['class']:
            classes = attrs['class'].split()
            if classes:
                predicates.append(f'contains(@class, "{classes[0]}")')
        
        if predicates:
            return f'//{tag}[{" and ".join(predicates)}]'
        
        return f'//{tag}'

    # ==================== Iframe-Specific Actions ====================

    async def click_element_in_iframe(
        self,
        iframe_selector: str,
        element_node: EnhancedDOMTreeNode,
    ) -> dict:
        """
        Click an element within a specific iframe (including cross-origin).
        
        Selenium WebDriver can interact with ALL iframes regardless of origin
        because it operates at the browser automation level, bypassing the
        Same-Origin Policy.
        
        Args:
            iframe_selector: CSS selector or XPath for the iframe
            element_node: The DOM element to click within the iframe
            
        Returns:
            Dict with click result
        """
        from selenium.webdriver.common.by import By
        
        self.logger.debug(f'Clicking element in iframe: {iframe_selector}')
        
        # Get element selector - use xpath if available, otherwise generate it
        xpath = element_node.attributes.get('xpath') or self._generate_xpath(element_node)
        
        try:
            # Switch to iframe and click - works for ALL iframes including cross-origin
            success = await self.iframe_handler.click_in_frame(
                iframe_selector,
                xpath,
                by=By.XPATH,
            )
            
            is_cross_origin = element_node.attributes.get('data-iframe-type') == 'cross-origin'
            
            return {
                'success': success,
                'iframe': iframe_selector,
                'xpath': xpath,
                'method': 'frame-switch',
                'cross_origin': is_cross_origin,
            }
            
        except Exception as e:
            self.logger.error(f'Failed to click in iframe: {e}')
            raise

    async def type_text_in_iframe(
        self,
        iframe_selector: str,
        element_node: EnhancedDOMTreeNode | None,
        text: str,
        clear_first: bool = True,
    ) -> dict:
        """
        Type text into an element within a specific iframe (including cross-origin).
        
        Selenium WebDriver can interact with ALL iframes regardless of origin.
        
        Args:
            iframe_selector: CSS selector or XPath for the iframe
            element_node: The DOM element to type into (or None for active element)
            text: The text to type
            clear_first: Whether to clear the field first
            
        Returns:
            Dict with type result
        """
        from selenium.webdriver.common.by import By
        
        self.logger.debug(f'Typing in iframe: {iframe_selector}')
        
        # Type in iframe (works for both same-origin and cross-origin via Selenium)
        if element_node:
            xpath = element_node.attributes.get('xpath') or self._generate_xpath(element_node)
            
            success = await self.iframe_handler.type_in_frame(
                iframe_selector,
                xpath,
                text,
                clear_first=clear_first,
                by=By.XPATH,
            )
        else:
            # Type to active element in iframe
            success = await self.iframe_handler.execute_in_frame(
                iframe_selector,
                f'''
                var activeEl = document.activeElement;
                if (activeEl) {{
                    if ({str(clear_first).lower()}) {{
                        activeEl.value = '';
                    }}
                    activeEl.value += arguments[0];
                    return true;
                }}
                return false;
                ''',
                text,
            )
        
        return {
            'success': success,
            'iframe': iframe_selector,
            'text_length': len(text),
            'method': 'same-origin-switch',
        }

    async def scroll_in_iframe(
        self,
        iframe_selector: str,
        direction: str = 'down',
        amount: int = 300,
        element_node: EnhancedDOMTreeNode | None = None,
    ) -> dict:
        """
        Scroll within a specific iframe.
        
        Args:
            iframe_selector: CSS selector or XPath for the iframe
            direction: 'up', 'down', 'left', or 'right'
            amount: Number of pixels to scroll
            element_node: Optional specific element to scroll within iframe
            
        Returns:
            Dict with scroll result
        """
        self.logger.debug(f'Scrolling in iframe: {iframe_selector}')
        
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
        
        if element_node:
            xpath = element_node.attributes.get('xpath') or self._generate_xpath(element_node)
            script = f'''
                var element = document.evaluate('{xpath}', document, null, 
                    XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
                if (element) {{
                    element.scrollBy({scroll_x}, {scroll_y});
                    return true;
                }}
                return false;
            '''
        else:
            script = f'window.scrollBy({scroll_x}, {scroll_y}); return true;'
        
        result = await self.iframe_handler.execute_in_frame(
            iframe_selector,
            script,
        )
        
        return {
            'success': bool(result),
            'iframe': iframe_selector,
            'direction': direction,
            'amount': amount,
        }

    async def execute_script_in_iframe(
        self,
        iframe_selector: str,
        script: str,
        *args,
    ) -> Any:
        """
        Execute JavaScript within a specific iframe (same-origin only).
        
        Args:
            iframe_selector: CSS selector or XPath for the iframe
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

    def _is_element_in_iframe(self, element_node: EnhancedDOMTreeNode) -> tuple[bool, str | None]:
        """
        Check if an element is from an iframe and return the iframe selector.
        
        Args:
            element_node: The DOM element to check
            
        Returns:
            Tuple of (is_in_iframe, iframe_selector)
        """
        iframe_selector = element_node.attributes.get('data-iframe-selector')
        if iframe_selector:
            return True, iframe_selector
        
        frame_id = getattr(element_node, 'frame_id', None)
        if frame_id and frame_id.startswith('iframe:'):
            return True, frame_id[7:]  # Remove 'iframe:' prefix
        
        return False, None

    async def click_element_auto(
        self,
        element_node: EnhancedDOMTreeNode,
        selector_map: dict[int, EnhancedDOMTreeNode] | None = None,
    ) -> dict:
        """
        Click an element, automatically handling iframe context.
        
        This method checks if the element is within an iframe and
        automatically switches context if needed.
        
        Args:
            element_node: The DOM element to click
            selector_map: Optional selector map for index-based lookup
            
        Returns:
            Dict with click result
        """
        is_in_iframe, iframe_selector = self._is_element_in_iframe(element_node)
        
        if is_in_iframe and iframe_selector:
            return await self.click_element_in_iframe(iframe_selector, element_node)
        else:
            return await self.click_element(element_node, selector_map)

    async def type_text_auto(
        self,
        element_node: EnhancedDOMTreeNode | None,
        text: str,
        clear_first: bool = True,
    ) -> dict:
        """
        Type text into an element, automatically handling iframe context.
        
        Args:
            element_node: The DOM element to type into (or None for active element)
            text: The text to type
            clear_first: Whether to clear the field first
            
        Returns:
            Dict with type result
        """
        if element_node is None:
            return await self.type_text(None, text, clear_first)
        
        is_in_iframe, iframe_selector = self._is_element_in_iframe(element_node)
        
        if is_in_iframe and iframe_selector:
            return await self.type_text_in_iframe(
                iframe_selector,
                element_node,
                text,
                clear_first,
            )
        else:
            return await self.type_text(element_node, text, clear_first)

