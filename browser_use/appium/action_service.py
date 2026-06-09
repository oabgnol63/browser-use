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

    async def _read_element_value(self, element) -> str:
        value = await self._run_driver_call(lambda: element.get_attribute('value'))
        return '' if value is None else str(value)

    async def _set_element_value_with_events(self, element, value: str) -> str:
        script = """
            const element = arguments[0];
            const newValue = arguments[1];
            if (!element) {
                return '';
            }

            const prototypes = [window.HTMLInputElement && HTMLInputElement.prototype, window.HTMLTextAreaElement && HTMLTextAreaElement.prototype]
                .filter(Boolean);
            let setter = null;
            for (const proto of prototypes) {
                const desc = Object.getOwnPropertyDescriptor(proto, 'value');
                if (desc && typeof desc.set === 'function') {
                    setter = desc.set;
                    break;
                }
            }

            if (typeof element.focus === 'function') {
                element.focus();
            }

            if (setter) {
                setter.call(element, newValue);
            } else if ('value' in element) {
                element.value = newValue;
            } else if (element.isContentEditable) {
                element.textContent = newValue;
            }

            element.dispatchEvent(new Event('input', { bubbles: true }));
            element.dispatchEvent(new Event('change', { bubbles: true }));

            if ('value' in element) {
                return element.value || '';
            }
            return element.textContent || '';
        """
        result = await self._run_driver_call(lambda: self.driver.execute_script(script, element, value))
        return '' if result is None else str(result)

    async def _focus_element_for_typing(self, element) -> None:
        try:
            await self._run_driver_call(lambda: element.click())
        except Exception as focus_err:
            self.logger.debug(f'Element click/focus failed before typing, continuing anyway: {focus_err}')
        await asyncio.sleep(0.1)

    async def _clear_element_text(self, element) -> str:
        try:
            await self._run_driver_call(lambda: element.clear())
        except Exception as clear_err:
            self.logger.debug(f'Element.clear() failed, falling back to JS clear: {clear_err}')

        value_after_clear = await self._read_element_value(element)
        if value_after_clear:
            value_after_clear = await self._set_element_value_with_events(element, '')
        await asyncio.sleep(0.1)
        return value_after_clear

    async def _type_text_character_by_character(self, element, text: str) -> str:
        for char in text:
            await self._run_driver_call(lambda ch=char: element.send_keys('\n' if ch == '\n' else ch))
            await asyncio.sleep(0.02)
        return await self._read_element_value(element)

    def _is_special_key_input(self, keys: str) -> bool:
        special_keys = {
            'enter',
            'return',
            'tab',
            'space',
            'backspace',
            'delete',
            'escape',
            'esc',
            'arrowup',
            'arrowdown',
            'arrowleft',
            'arrowright',
            'pageup',
            'pagedown',
            'home',
            'end',
            'insert',
            'f1',
            'f2',
            'f3',
            'f4',
            'f5',
            'f6',
            'f7',
            'f8',
            'f9',
            'f10',
            'f11',
            'f12',
        }
        return '+' in keys or keys.strip().lower() in special_keys

    def _browser_name(self) -> str:
        capabilities = dict(getattr(self.driver, 'capabilities', {}) or {})
        return str(capabilities.get('browserName') or capabilities.get('browser') or '').lower()

    def _platform_name(self) -> str:
        capabilities = dict(getattr(self.driver, 'capabilities', {}) or {})
        return str(capabilities.get('platformName') or capabilities.get('platform') or '').lower()

    def _automation_name(self) -> str:
        capabilities = dict(getattr(self.driver, 'capabilities', {}) or {})
        return str(
            capabilities.get('appium:automationName') or capabilities.get('automationName') or ''
        ).lower()

    def _is_ios_mobile_web(self) -> bool:
        return 'ios' in self._platform_name() or self._automation_name() == 'xcuitest'

    def _is_ios_enter_key(self, keys: str) -> bool:
        return self._is_ios_mobile_web() and keys in {'Enter', 'Return'}

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

    async def click_coordinates(self, x: int, y: int, human_like: bool = True) -> dict:
        """Click at specific coordinates using native touch coordinates first.

        The shared Selenium/Appium contract still accepts ``human_like`` for
        compatibility, but the Appium backend intentionally ignores it.
        If native touch fails, fall back to in-page JS elementFromPoint.
        """
        self.logger.debug(f'Clicking at coordinates: ({x}, {y})')

        def do_tap():
            actions = ActionBuilder(self.driver, mouse=PointerInput(interaction.POINTER_TOUCH, 'touch'))
            actions.pointer_action.move_to_location(x, y)
            actions.pointer_action.pointer_down()
            actions.pointer_action.pause(0.05)
            actions.pointer_action.pointer_up()
            actions.perform()

        try:
            await self._run_driver_call(do_tap, timeout=10.0)
            self.logger.info(f'Appium coordinate click used native touch tap at ({x}, {y})')
            return {
                'success': True,
                'x': x,
                'y': y,
                'method': 'w3c-touch-tap',
            }
        except Exception as tap_error:
            self.logger.warning(f'Native touch tap failed: {tap_error}. Falling back to JS elementFromPoint click.')
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
        else:
            self.logger.info(f'Appium coordinate click used JS elementFromPoint click at ({x}, {y})')

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

        await self._focus_element_for_typing(element)

        if clear_first:
            try:
                val_after_clear = await self._clear_element_text(element)
                if val_after_clear:
                    self.logger.debug(f'Field still had value after initial clear attempt: {val_after_clear!r}')
            except Exception as clear_err:
                self.logger.debug(f'Clear failed, attempting to type anyway: {clear_err}')

        val_after_type = await self._type_text_character_by_character(element, text)

        self.logger.debug('Type successful')
        return {
            'success': True,
            'text_length': len(text),
            'actual_value': val_after_type,
        }

    async def send_keys(self, keys: str) -> dict:
        """Handle iOS Safari Enter/Return with mobile-web submit fallbacks."""
        if not self._is_special_key_input(keys) and not self._is_ios_enter_key(keys):
            self.logger.debug(f'Sending plain text through Appium active-element typing path: {keys}')
            element = await self._run_driver_call(lambda: self.driver.switch_to.active_element)
            await self._focus_element_for_typing(element)
            actual_value = await self._type_text_character_by_character(element, keys)
            return {
                'success': True,
                'keys': keys,
                'actual_value': actual_value,
            }

        if not self._is_ios_enter_key(keys):
            return await super().send_keys(keys)

        self.logger.debug(f'Sending iOS mobile-web special key: {keys}')
        element = await self._run_driver_call(lambda: self.driver.switch_to.active_element)

        before_url = await self._run_driver_call(lambda: self.driver.current_url)
        newline_error = None
        try:
            await self._run_driver_call(lambda: element.send_keys('\n'))
        except Exception as e:
            newline_error = e
            self.logger.debug(f'iOS newline submit failed, falling back to JS submit path: {e}')

        if newline_error is None:
            await asyncio.sleep(0.25)
            after_url = await self._run_driver_call(lambda: self.driver.current_url)
            if before_url != after_url:
                return {
                    'success': True,
                    'keys': keys,
                    'method': 'ios-newline-submit',
                }

        fallback_result = await self._run_driver_call(
            lambda: self.driver.execute_script(
                """
                const element = arguments[0];
                const tagName = (element.tagName || '').toLowerCase();
                const inputType = (element.getAttribute('type') || '').toLowerCase();
                const isMultiline = tagName === 'textarea' || !!element.isContentEditable;
                const eventInit = {
                    key: 'Enter',
                    code: 'Enter',
                    keyCode: 13,
                    which: 13,
                    bubbles: true,
                    cancelable: true,
                };

                const dispatchResult = {
                    keydown: element.dispatchEvent(new KeyboardEvent('keydown', eventInit)),
                    keypress: element.dispatchEvent(new KeyboardEvent('keypress', eventInit)),
                    keyup: element.dispatchEvent(new KeyboardEvent('keyup', eventInit)),
                };

                if (isMultiline) {
                    return {
                        method: 'ios-enter-events',
                        submitted: false,
                        isMultiline: true,
                        dispatchResult,
                    };
                }

                const form = element.form || element.closest('form');
                if (form) {
                    if (typeof form.requestSubmit === 'function') {
                        form.requestSubmit();
                        return {
                            method: 'ios-enter-request-submit',
                            submitted: true,
                            isMultiline: false,
                            dispatchResult,
                        };
                    }

                    if (typeof form.submit === 'function') {
                        form.submit();
                        return {
                            method: 'ios-enter-form-submit',
                            submitted: true,
                            isMultiline: false,
                            dispatchResult,
                        };
                    }
                }

                const containers = [
                    element.closest('[role="search"]'),
                    element.parentElement,
                    document.body,
                ].filter(Boolean);
                const seen = new Set();

                function getLabel(node) {
                    return (
                        node.getAttribute('aria-label') ||
                        node.getAttribute('title') ||
                        node.textContent ||
                        ''
                    ).trim();
                }

                function isVisible(node) {
                    if (!node || !node.getBoundingClientRect) {
                        return false;
                    }
                    const rect = node.getBoundingClientRect();
                    const style = window.getComputedStyle(node);
                    return (
                        rect.width > 0 &&
                        rect.height > 0 &&
                        style.display !== 'none' &&
                        style.visibility !== 'hidden' &&
                        style.pointerEvents !== 'none'
                    );
                }

                function scoreCandidate(node) {
                    if (!isVisible(node) || node === element || node.contains(element)) {
                        return -1;
                    }

                    const label = getLabel(node).toLowerCase();
                    const role = (node.getAttribute('role') || '').toLowerCase();
                    const nodeType = (node.getAttribute('type') || '').toLowerCase();
                    const rect = node.getBoundingClientRect();
                    const inputRect = element.getBoundingClientRect();
                    let score = 0;

                    if (nodeType === 'submit') score += 10;
                    if (role === 'button' || node.tagName.toLowerCase() === 'button') score += 2;
                    if (label.includes('search')) score += 8;
                    if (label.includes('go') || label.includes('submit') || label.includes('done')) score += 4;
                    if (Math.abs((rect.top + rect.height / 2) - (inputRect.top + inputRect.height / 2)) <= 80) score += 3;
                    if (rect.left >= inputRect.right - 20) score += 3;
                    if (node.parentElement === element.parentElement) score += 2;
                    if (tagName === 'input' && (inputType === 'search' || inputType === 'text')) score += 1;

                    return score;
                }

                let bestCandidate = null;
                let bestScore = 0;
                for (const container of containers) {
                    for (const node of container.querySelectorAll('button, input[type="submit"], input[type="button"], [role="button"]')) {
                        if (seen.has(node)) {
                            continue;
                        }
                        seen.add(node);
                        const score = scoreCandidate(node);
                        if (score > bestScore) {
                            bestScore = score;
                            bestCandidate = node;
                        }
                    }
                }

                if (bestCandidate && bestScore > 0) {
                    bestCandidate.click();
                    return {
                        method: 'ios-enter-search-click',
                        submitted: true,
                        isMultiline: false,
                        candidateLabel: getLabel(bestCandidate),
                        bestScore,
                        dispatchResult,
                    };
                }

                return {
                    method: 'ios-enter-events',
                    submitted: false,
                    isMultiline: false,
                    dispatchResult,
                };
                """,
                element,
            ),
            timeout=5.0,
        )

        return {
            'success': True,
            'keys': keys,
            'method': fallback_result.get('method', 'ios-enter-events'),
            'fallback': fallback_result,
        }
