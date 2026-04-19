"""
Appium-specific action service for mobile web sessions.

Inherits from SeleniumActionService and overrides only the primitives that
diverge on mobile web (touch vs. synthetic pointer, no hover, no keyboard
shortcut clears, JS-based coordinate click). Everything else — navigate,
type_text fallbacks, send_keys, scroll, screenshots, xpath generation,
iframe handling — is the Selenium implementation unchanged.
"""

import asyncio
import random

from selenium.webdriver.common.actions import interaction
from selenium.webdriver.common.actions.action_builder import ActionBuilder
from selenium.webdriver.common.actions.pointer_input import PointerInput
from selenium.webdriver.common.by import By

from browser_use.dom.views import EnhancedDOMTreeNode
from browser_use.selenium.action_service import SeleniumActionService


class AppiumActionService(SeleniumActionService):
    """Mobile-web action service tuned for Appium-backed sessions."""

    async def _run_driver_call(self, func, timeout: float | None = None):
        """Run a blocking WebDriver call with a bounded async wait."""
        return await asyncio.wait_for(asyncio.get_event_loop().run_in_executor(None, func), timeout=timeout)

    async def hover_element(
        self,
        element_node: EnhancedDOMTreeNode,
        selector_map: dict[int, EnhancedDOMTreeNode] | None = None,
    ) -> dict:
        """Mobile web has no real hover; treat it as a no-op success."""
        self.logger.debug('Ignoring hover request in Appium mobile-web session')
        return {'success': True, 'method': 'noop', 'action': 'hover'}

    async def click_element(
        self,
        element_node: EnhancedDOMTreeNode,
        selector_map: dict[int, EnhancedDOMTreeNode] | None = None,
    ) -> dict:
        """
        Click an element using mobile-first fallbacks.

        Desktop-style pointer trajectories are avoided here — Appium web sessions
        are more reliable with direct element clicks and JS fallbacks than with
        synthetic desktop pointer actions.
        """
        is_in_iframe, iframe_selector = self._is_element_in_iframe(element_node)
        xpath = element_node.attributes.get('xpath') or self._generate_xpath(element_node)

        if is_in_iframe and iframe_selector:
            self.logger.debug(f'Clicking element in iframe: {iframe_selector}')
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

        element, method = await self._find_element_robust(element_node)
        href = element_node.attributes.get('href')

        await self._run_driver_call(
            lambda: self.driver.execute_script(
                "arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});", element
            ),
            timeout=8.0,
        )
        await asyncio.sleep(random.uniform(0.3, 0.6))

        try:
            await self._run_driver_call(lambda: element.click(), timeout=10.0)
        except Exception as click_error:
            self.logger.warning(f'Mobile click failed: {click_error}. Falling back to JS click or location.href')
            if element_node.node_name.lower() == 'a' and href:
                await self._run_driver_call(
                    lambda: self.driver.execute_script('window.location.href = arguments[0].href || arguments[1];', element, href),
                    timeout=8.0,
                )
            else:
                await self._run_driver_call(
                    lambda: self.driver.execute_script('arguments[0].click();', element),
                    timeout=8.0,
                )

        self.logger.debug(f'Mobile click successful using {method}')
        return {
            'success': True,
            'xpath': xpath,
            'method': f'appium-{method}',
            'tag_name': element_node.node_name,
        }

    async def click_coordinates(self, x: int, y: int) -> dict:
        """Click at specific coordinates using pure JavaScript.

        Using JS avoids complicated pointer action chains which are flaky on
        Appium Web Views.
        """
        self.logger.debug(f'Clicking at coordinates: ({x}, {y})')

        script = f"""
            var element = document.elementFromPoint({x}, {y});
            if (element) {{
                element.click();
                return true;
            }}
            return false;
        """
        result = await self._run_driver_call(lambda: self.driver.execute_script(script), timeout=5.0)

        if not result:
            self.logger.warning(f'No element found at coordinates ({x}, {y}) to click')

        return {
            'success': bool(result),
            'x': x,
            'y': y,
            'method': 'js-click',
        }

    async def drag_and_drop(self, start_x: int, start_y: int, end_x: int, end_y: int) -> dict:
        """Touch-pointer drag with longer press and slower movement than swipe."""
        self.logger.debug(f'Dragging from ({start_x}, {start_y}) to ({end_x}, {end_y})')

        def do_drag():
            actions = ActionBuilder(self.driver, mouse=PointerInput(interaction.POINTER_TOUCH, 'touch'))
            actions.pointer_action.move_to_location(start_x, start_y)
            actions.pointer_action.pointer_down()
            actions.pointer_action.pause(0.35)

            steps = 8
            for step in range(1, steps + 1):
                x = int(start_x + (end_x - start_x) * (step / steps))
                y = int(start_y + (end_y - start_y) * (step / steps))
                actions.pointer_action.move_to_location(x, y)
                actions.pointer_action.pause(0.04)

            actions.pointer_action.pause(0.1)
            actions.pointer_action.pointer_up()
            actions.perform()

        await self._run_driver_call(do_drag, timeout=10.0)
        return {
            'success': True,
            'start_x': start_x,
            'start_y': start_y,
            'end_x': end_x,
            'end_y': end_y,
            'method': 'w3c-touch-drag',
        }

    async def swipe_coordinate(self, start_x: int, start_y: int, end_x: int, end_y: int) -> dict:
        """W3C touch swipe gesture — mobile-specific, has no desktop equivalent."""
        self.logger.debug(f'Swiping from ({start_x}, {start_y}) to ({end_x}, {end_y})')

        def do_swipe():
            actions = ActionBuilder(self.driver, mouse=PointerInput(interaction.POINTER_TOUCH, 'touch'))
            actions.pointer_action.move_to_location(start_x, start_y)
            actions.pointer_action.pointer_down()
            actions.pointer_action.pause(0.1)
            actions.pointer_action.move_to_location(end_x, end_y)
            actions.pointer_action.pointer_up()
            actions.perform()

        await self._run_driver_call(do_swipe, timeout=10.0)
        return {
            'success': True,
            'start_x': start_x,
            'start_y': start_y,
            'end_x': end_x,
            'end_y': end_y,
            'method': 'w3c-touch-swipe',
        }

    async def type_text(
        self,
        element_node: EnhancedDOMTreeNode | None,
        text: str,
        clear_first: bool = True,
    ) -> dict:
        """Mobile-friendly typing: direct element.send_keys, no ActionChains or CTRL+A shortcuts."""
        self.logger.debug(f'Typing text: {text[:20]}...' if len(text) > 20 else f'Typing text: {text}')

        if element_node:
            is_in_iframe, iframe_selector = self._is_element_in_iframe(element_node)
            if is_in_iframe and iframe_selector:
                self.logger.debug(f'Typing in iframe: {iframe_selector}')
                xpath = element_node.attributes.get('xpath') or self._generate_xpath(element_node)
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

        if element_node:
            xpath = element_node.attributes.get('xpath') or self._generate_xpath(element_node)
            element = await self._run_driver_call(lambda: self.driver.find_element(By.XPATH, xpath))
        else:
            element = await self._run_driver_call(lambda: self.driver.switch_to.active_element)

        if clear_first:
            try:
                await self._run_driver_call(lambda: element.clear())
                val_after_clear = await self._run_driver_call(lambda: element.get_attribute('value'))
                if val_after_clear:
                    await self._run_driver_call(
                        lambda: self.driver.execute_script("arguments[0].value = '';", element)
                    )
            except Exception as clear_err:
                self.logger.debug(f'Clear failed, attempting to type anyway: {clear_err}')

        await self._run_driver_call(lambda: element.send_keys(text))

        val_after_type = await self._run_driver_call(lambda: element.get_attribute('value'))
        if not val_after_type and text:
            await self._run_driver_call(
                lambda: self.driver.execute_script("arguments[0].value += arguments[1];", element, text)
            )

        self.logger.debug('Type successful')
        return {
            'success': True,
            'text_length': len(text),
        }
