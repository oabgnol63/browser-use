import asyncio
import base64
import time
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from PIL import Image

from browser_use.browser.events import ScreenshotEvent
from browser_use.browser.session import BrowserSession
from browser_use.browser.watchdogs.screenshot_watchdog import ScreenshotWatchdog


def _png_b64(width: int = 4, height: int = 3) -> str:
	buffer = BytesIO()
	Image.new('RGB', (width, height), (12, 34, 56)).save(buffer, format='PNG')
	return base64.b64encode(buffer.getvalue()).decode('utf-8')


def _build_fake_cdp_session(capture_screenshot: AsyncMock) -> SimpleNamespace:
	return SimpleNamespace(
		session_id='session-1',
		cdp_client=SimpleNamespace(
			send=SimpleNamespace(
				Page=SimpleNamespace(captureScreenshot=capture_screenshot),
			)
		),
	)


@pytest.mark.asyncio
async def test_screenshot_watchdog_dom_mode_falls_back_to_latest_page_target():
	session = BrowserSession(headless=True)
	session.agent_focus_target_id = 'focused-target'
	watchdog = ScreenshotWatchdog(event_bus=session.event_bus, browser_session=session)
	capture_screenshot = AsyncMock(return_value={'data': _png_b64()})
	fake_cdp_session = _build_fake_cdp_session(capture_screenshot)
	page_targets = [
		SimpleNamespace(target_id='page-1', target_type='page'),
		SimpleNamespace(target_id='page-2', target_type='page'),
	]

	with patch.object(BrowserSession, 'get_focused_target', return_value=None):
		with patch.object(BrowserSession, 'get_page_targets', return_value=page_targets):
			with patch.object(BrowserSession, 'get_or_create_cdp_session', new=AsyncMock(return_value=fake_cdp_session)) as get_cdp:
				with patch.object(BrowserSession, 'remove_highlights', new=AsyncMock(return_value=None)):
					result = await watchdog.on_ScreenshotEvent(ScreenshotEvent())

	assert result == capture_screenshot.return_value['data']
	assert get_cdp.await_args.args[0] == 'page-2'
	assert session._actual_screenshot_size == (4, 3)


@pytest.mark.asyncio
async def test_screenshot_watchdog_vision_only_pins_capture_to_focused_page():
	session = BrowserSession(headless=True)
	session.agent_focus_target_id = 'focused-page'
	session._use_native_computer_use = True
	object.__setattr__(session, 'session_manager', SimpleNamespace(ensure_valid_focus=AsyncMock(return_value=True)))

	watchdog = ScreenshotWatchdog(event_bus=session.event_bus, browser_session=session)
	capture_screenshot = AsyncMock(return_value={'data': _png_b64()})
	fake_cdp_session = _build_fake_cdp_session(capture_screenshot)

	with patch.object(BrowserSession, 'get_focused_target', return_value=SimpleNamespace(target_id='focused-page', target_type='page')):
		with patch.object(BrowserSession, 'get_page_targets', return_value=[SimpleNamespace(target_id='new-tab', target_type='page')]) as get_page_targets:
			with patch.object(BrowserSession, 'get_or_create_cdp_session', new=AsyncMock(return_value=fake_cdp_session)) as get_cdp:
				with patch.object(BrowserSession, 'remove_highlights', new=AsyncMock(return_value=None)):
					await watchdog.on_ScreenshotEvent(ScreenshotEvent(event_timeout=0.2))

	assert session.session_manager.ensure_valid_focus.await_count == 1
	assert get_page_targets.call_count == 0
	assert get_cdp.await_args.args[0] == 'focused-page'


@pytest.mark.asyncio
async def test_screenshot_watchdog_vision_only_capture_honors_event_timeout():
	session = BrowserSession(headless=True)
	session.agent_focus_target_id = 'focused-page'
	session._use_native_computer_use = True
	object.__setattr__(session, 'session_manager', SimpleNamespace(ensure_valid_focus=AsyncMock(return_value=True)))

	async def slow_capture(*args, **kwargs):
		await asyncio.sleep(0.2)
		return {'data': _png_b64()}

	watchdog = ScreenshotWatchdog(event_bus=session.event_bus, browser_session=session)
	fake_cdp_session = _build_fake_cdp_session(AsyncMock(side_effect=slow_capture))

	with patch.object(BrowserSession, 'get_focused_target', return_value=SimpleNamespace(target_id='focused-page', target_type='page')):
		with patch.object(BrowserSession, 'get_or_create_cdp_session', new=AsyncMock(return_value=fake_cdp_session)):
			with patch.object(BrowserSession, 'remove_highlights', new=AsyncMock(return_value=None)):
				start = time.perf_counter()
				with pytest.raises(TimeoutError):
					await watchdog.on_ScreenshotEvent(ScreenshotEvent(event_timeout=0.05))
				elapsed = time.perf_counter() - start

	assert elapsed < 0.15
