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
from typing import TYPE_CHECKING

from browser_use.dom.views import EnhancedDOMTreeNode

if TYPE_CHECKING:
    from selenium.webdriver.remote.webdriver import WebDriver

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
        Click an element, automatically handling iframe context.
        
        Args:
            element_node: The DOM element to click
            selector_map: Optional selector map for index-based lookup
            
        Returns:
            Dict with click result
        """
        from selenium.webdriver.common.by import By
        from selenium.webdriver.common.action_chains import ActionChains
        
        # Check if the element is within an iframe
        is_in_iframe, iframe_selector = self._is_element_in_iframe(element_node)
        xpath = element_node.attributes.get('xpath') or self._generate_xpath(element_node)
        
        if is_in_iframe and iframe_selector:
            self.logger.debug(f'Clicking element in iframe: {iframe_selector}')
            try:
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
        Type text into an element or the active element, automatically handling iframe context.
        
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
            # Determine platform/browser to use correct modifier keys
            caps = self.driver.capabilities
            browser_name = caps.get('browserName', '').lower()
            platform_name = (caps.get('platformName') or caps.get('platform', '') or '').lower()
            
            is_mac = any(x in platform_name for x in ('mac', 'darwin', 'os x'))
            is_safari = 'safari' in browser_name
            
            # Use COMMAND for Mac/Safari, CONTROL otherwise for shortcuts like Select All
            modifier = Keys.COMMAND if (is_mac or is_safari) else Keys.CONTROL

            # Check if the element is within an iframe
            if element_node:
                is_in_iframe, iframe_selector = self._is_element_in_iframe(element_node)
                if is_in_iframe and iframe_selector:
                    self.logger.debug(f'Typing in iframe: {iframe_selector}')
                    xpath = element_node.attributes.get('xpath') or self._generate_xpath(element_node)
                    
                    # Type in iframe (works for both same-origin and cross-origin via Selenium)
                    success = await self.iframe_handler.type_in_frame(
                        iframe_selector,
                        xpath,
                        text,
                        clear_first=clear_first,
                        by=By.XPATH,
                    )
                    
                    return {
                        'success': success,
                        'iframe': iframe_selector,
                        'text_length': len(text),
                        'method': 'same-origin-switch',
                    }

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
            
            # Use ActionChains for Safari as it's often more reliable for focus and typing
            from selenium.webdriver.common.action_chains import ActionChains
            
            if clear_first:
                if is_safari:
                    # Explicit focus for Safari
                    await asyncio.get_event_loop().run_in_executor(None, lambda: element.click())
                    
                # Try built-in clear first
                await asyncio.get_event_loop().run_in_executor(None, lambda: element.clear())
                
                # Verify clear
                val_after_clear = await asyncio.get_event_loop().run_in_executor(None, lambda: element.get_attribute('value'))
                if val_after_clear:
                    # Fallback to select-all trick
                    def do_shortcut_clear():
                        actions = ActionChains(self.driver)
                        actions.move_to_element(element).click()
                        actions.key_down(modifier).send_keys('a').key_up(modifier).send_keys(Keys.BACK_SPACE)
                        actions.perform()
                    await asyncio.get_event_loop().run_in_executor(None, do_shortcut_clear)
                
            # Type text using ActionChains for better reliability on Safari/macOS
            def do_final_type():
                actions = ActionChains(self.driver)
                actions.move_to_element(element).click()
                actions.send_keys(text)
                actions.perform()
            
            await asyncio.get_event_loop().run_in_executor(None, do_final_type)

            # Verification
            val_after_type = await asyncio.get_event_loop().run_in_executor(None, lambda: element.get_attribute('value'))
            
            # If still empty, try one last time with direct send_keys (sometimes ActionChains fails where direct works, and vice versa)
            if not val_after_type and text:
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

    async def send_keys(self, keys: str) -> dict:
        """
        Send special keys to the active element.
        
        Args:
            keys: The keys to send (e.g. "Enter", "Tab", "Control+a")
            
        Returns:
            Dict with result
        """
        from selenium.webdriver.common.keys import Keys
        from selenium.common.exceptions import StaleElementReferenceException
        
        self.logger.debug(f'Sending keys: {keys}')
        
        # Map common key names to Selenium Keys
        key_map = {
            'Enter': Keys.ENTER,
            'Return': Keys.RETURN,
            'Tab': Keys.TAB,
            'Space': Keys.SPACE,
            'Backspace': Keys.BACK_SPACE,
            'Delete': Keys.DELETE,
            'Escape': Keys.ESCAPE,
            'ArrowUp': Keys.UP,
            'ArrowDown': Keys.DOWN,
            'ArrowLeft': Keys.LEFT,
            'ArrowRight': Keys.RIGHT,
            'PageUp': Keys.PAGE_UP,
            'PageDown': Keys.PAGE_DOWN,
            'Home': Keys.HOME,
            'End': Keys.END,
            'Insert': Keys.INSERT,
            'F1': Keys.F1,
            'F2': Keys.F2,
            'F3': Keys.F3,
            'F4': Keys.F4,
            'F5': Keys.F5,
            'F6': Keys.F6,
            'F7': Keys.F7,
            'F8': Keys.F8,
            'F9': Keys.F9,
            'F10': Keys.F10,
            'F11': Keys.F11,
            'F12': Keys.F12,
        }
        
        max_retries = 3
        for attempt in range(max_retries):
            try:
                self.logger.debug(f'Attempt {attempt + 1}/{max_retries}: Sending keys')
                
                # Handle combinations like "Control+a"
                if '+' in keys:
                    parts = keys.split('+')
                    # This is a simplified implementation for common shortcuts
                    # For complex combinations, we might need more logic
                    
                    # Get the active element
                    element = await asyncio.get_event_loop().run_in_executor(
                        None, lambda: self.driver.switch_to.active_element
                    )
                    self.logger.debug(f'Got active element')
                    
                    # Construct the key sequence
                    key_sequence = []
                    for part in parts:
                        part_lower = part.lower()
                        if part_lower in ('control', 'ctrl'):
                            key_sequence.append(Keys.CONTROL)
                        elif part_lower in ('alt', 'option'):
                            key_sequence.append(Keys.ALT)
                        elif part_lower in ('shift',):
                            key_sequence.append(Keys.SHIFT)
                        elif part_lower in ('meta', 'command', 'cmd'):
                            key_sequence.append(Keys.META)
                        elif part in key_map:
                            key_sequence.append(key_map[part])
                        else:
                            key_sequence.append(part)
                    
                    # Send keys together (chord) is tricky with just send_keys list
                    # For now, just send them sequentially which works for modifiers usually
                    # Or better, use the string concatenation for modifiers
                    
                    # Actually, Selenium's send_keys handles modifiers if passed as args
                    # But we need to know if it's a chord or sequence.
                    # Let's assume standard modifier+key behavior
                    
                    await asyncio.get_event_loop().run_in_executor(
                        None, lambda: element.send_keys(*key_sequence)
                    )
                else:
                    # Single key
                    selenium_key = key_map.get(keys, keys)
                    
                    # Get the active element
                    element = await asyncio.get_event_loop().run_in_executor(
                        None, lambda: self.driver.switch_to.active_element
                    )
                    self.logger.debug(f'Got active element')
                    
                    await asyncio.get_event_loop().run_in_executor(
                        None, lambda: element.send_keys(selenium_key)
                    )
                
                self.logger.debug('Send keys successful')
                return {
                    'success': True,
                    'keys': keys,
                }
            except StaleElementReferenceException as e:
                self.logger.warning(f'StaleElementReferenceException on attempt {attempt + 1}/{max_retries}: {e}')
                if attempt < max_retries - 1:
                    self.logger.info(f'Retrying send_keys after stale element...')
                    await asyncio.sleep(0.1)
                    continue
                else:
                    self.logger.error(f'Send keys failed after {max_retries} attempts: {e}')
                    raise
            except Exception as e:
                self.logger.error(f'Send keys failed on attempt {attempt + 1}/{max_retries}: {e}')
                raise
        
        # Fallback return to satisfy type checker, though loop should always return or raise
        return {'success': False, 'error': 'Failed after retries'}

    async def scroll(
        self,
        direction: str = 'down',
        amount: int = 300,
        element_node: EnhancedDOMTreeNode | None = None,
    ) -> dict:
        """
        Scroll the page or an element, automatically handling iframe context.
        
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
            # Check if element is in iframe
            if element_node:
                is_in_iframe, iframe_selector = self._is_element_in_iframe(element_node)
                xpath = element_node.attributes.get('xpath') or self._generate_xpath(element_node)
                
                if is_in_iframe and iframe_selector:
                    self.logger.debug(f'Scrolling in iframe: {iframe_selector}')
                    script = f'''
                        var element = document.evaluate('{xpath}', document, null, 
                            XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
                        if (element) {{
                            element.scrollBy({scroll_x}, {scroll_y});
                            return true;
                        }}
                        return false;
                    '''
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

    # ==================== Helper Methods ====================

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
