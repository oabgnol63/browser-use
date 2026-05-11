from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from browser_use.browser.events import ScrollEvent
from browser_use.browser.session import BrowserSession
from browser_use.browser.watchdogs.default_action_watchdog import DefaultActionWatchdog
from browser_use.browser.views import BrowserError


def _build_fake_cdp_session(runtime_evaluate: AsyncMock) -> SimpleNamespace:
	return SimpleNamespace(
		session_id='session-1',
		cdp_client=SimpleNamespace(
			send=SimpleNamespace(
				Input=SimpleNamespace(
					synthesizeScrollGesture=AsyncMock(return_value=None),
				),
				Runtime=SimpleNamespace(
					evaluate=runtime_evaluate,
				),
			)
		),
	)


@pytest.mark.asyncio
async def test_scroll_gesture_returns_false_when_offsets_do_not_change():
	session = BrowserSession(headless=True)
	session.agent_focus_target_id = 'target-1'
	session._original_viewport_size = (1000, 1000)

	runtime_evaluate = AsyncMock(
		side_effect=[
			{'result': {'value': {'windowX': 0, 'windowY': 0, 'rootTop': 0, 'rootLeft': 0, 'center': None, 'active': None}}},
			{'result': {'value': {'windowX': 0, 'windowY': 0, 'rootTop': 0, 'rootLeft': 0, 'center': None, 'active': None}}},
		]
	)
	fake_cdp_session = _build_fake_cdp_session(runtime_evaluate)
	watchdog = DefaultActionWatchdog(event_bus=session.event_bus, browser_session=session)

	with patch.object(BrowserSession, 'get_or_create_cdp_session', new=AsyncMock(return_value=fake_cdp_session)):
		assert await watchdog._scroll_with_cdp_gesture(500) is False

	assert fake_cdp_session.cdp_client.send.Input.synthesizeScrollGesture.await_count == 1


@pytest.mark.asyncio
async def test_scroll_event_raises_when_gesture_and_js_have_no_effect():
	session = BrowserSession(headless=True)
	session.agent_focus_target_id = 'target-1'
	watchdog = DefaultActionWatchdog(event_bus=session.event_bus, browser_session=session)

	with patch.object(DefaultActionWatchdog, '_scroll_with_cdp_gesture', new=AsyncMock(return_value=False)):
		with patch.object(DefaultActionWatchdog, '_scroll_page_with_js', new=AsyncMock(return_value=False)):
			with pytest.raises(BrowserError, match='no visible effect'):
				await watchdog.on_ScrollEvent(ScrollEvent(direction='down', amount=400))
