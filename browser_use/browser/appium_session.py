from browser_use.browser.events import SwipeCoordinateEvent
from browser_use.browser.selenium_session import SeleniumBrowserSession


class AppiumBrowserSession(SeleniumBrowserSession):
    """Appium-specific browser session adapter for mobile-only event handling."""

    @property
    def coordinate_actions_use_screenshot_space(self) -> bool:
        """Appium touch actions execute in viewport/WebDriver coordinate space."""
        return False

    def map_screenshot_coordinates_to_action_space(self, x: int, y: int) -> tuple[int, int]:
        """Convert screenshot-space coordinates to viewport touch coordinates.

        Appium mobile-web taps execute in viewport CSS pixels, while the
        screenshot shown to the model may be device-scale-factor larger. Map
        screenshot space back into viewport space with a uniform divide, while
        adjusting for any vertical coordinate drift due to top status / address bars.
        Falls back to identity if metadata is missing.
        """
        screenshot_size = self._actual_screenshot_size
        viewport_size = self._original_viewport_size
        if not screenshot_size or not viewport_size:
            return x, y

        screenshot_width, _ = screenshot_size
        viewport_width, _ = viewport_size
        if screenshot_width <= 0 or viewport_width <= 0:
            return x, y

        scale = screenshot_width / viewport_width
        if scale <= 0:
            return x, y

        mapped_x = int(round(x / scale))
        mapped_y = int(round(y / scale))

        self.logger.debug(
            'Mapped Appium screenshot coordinates (%s, %s) -> viewport (%s, %s) using scale=%.4f',
            x,
            y,
            mapped_x,
            mapped_y,
            scale,
        )
        return mapped_x, mapped_y

    def __init__(self, selenium_session, **kwargs) -> None:
        super().__init__(selenium_session=selenium_session, **kwargs)

        from browser_use.browser.watchdog_base import BaseWatchdog

        swipe_coordinate = getattr(self._selenium_session.action_service, 'swipe_coordinate', None)
        if callable(swipe_coordinate):
            BaseWatchdog.attach_handler_to_session(self, SwipeCoordinateEvent, self.on_SwipeCoordinateEvent)

    async def on_SwipeCoordinateEvent(self, event: SwipeCoordinateEvent) -> dict:
        swipe_coordinate = getattr(self._selenium_session.action_service, 'swipe_coordinate', None)
        if callable(swipe_coordinate):
            return await swipe_coordinate(
                event.start_x, event.start_y, event.end_x, event.end_y
            )

        self.logger.warning('swipe_coordinate is not implemented in the current action service.')
        return {'success': False, 'error': 'Not implemented'}
