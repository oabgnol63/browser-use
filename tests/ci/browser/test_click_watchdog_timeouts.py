import time
from unittest.mock import AsyncMock, patch

import pytest

from browser_use.browser.events import ClickCoordinateEvent
from browser_use.browser.session import BrowserSession
from browser_use.browser.watchdogs.default_action_watchdog import DefaultActionWatchdog


class _NoopDownloadsWatchdog:
	def register_download_callbacks(self, on_start=None, on_progress=None, on_complete=None) -> None:
		return None

	def unregister_download_callbacks(self, on_start=None, on_progress=None, on_complete=None) -> None:
		return None


@pytest.mark.asyncio
async def test_click_coordinate_waits_no_longer_than_event_budget():
	session = BrowserSession(headless=True)
	session.agent_focus_target_id = 'target-1'
	session._downloads_watchdog = _NoopDownloadsWatchdog()
	watchdog = DefaultActionWatchdog(event_bus=session.event_bus, browser_session=session)

	async def fake_click_on_coordinate(self, coordinate_x: int, coordinate_y: int, force: bool = False, human_like: bool = True):
		return {'click_x': coordinate_x, 'click_y': coordinate_y}

	with patch.object(BrowserSession, 'get_dom_element_at_coordinates', new=AsyncMock(return_value=None)):
		with patch.object(DefaultActionWatchdog, '_click_on_coordinate', new=fake_click_on_coordinate):
			start = time.perf_counter()
			result = await watchdog.on_ClickCoordinateEvent(
				ClickCoordinateEvent(coordinate_x=10, coordinate_y=20, event_timeout=0.2)
			)
			elapsed = time.perf_counter() - start

	assert result == {'click_x': 10, 'click_y': 20}
	assert elapsed < 0.45


def test_click_coordinate_event_default_timeout_matches_download_wait_budget():
	event = ClickCoordinateEvent(coordinate_x=10, coordinate_y=20)
	assert event.event_timeout == 45.0
