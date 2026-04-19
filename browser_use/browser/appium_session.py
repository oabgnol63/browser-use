from browser_use.browser.events import SwipeCoordinateEvent
from browser_use.browser.selenium_session import SeleniumBrowserSession


class AppiumBrowserSession(SeleniumBrowserSession):
    """Appium-specific browser session adapter for mobile-only event handling."""

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
