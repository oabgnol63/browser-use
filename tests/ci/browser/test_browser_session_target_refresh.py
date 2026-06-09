from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from browser_use.browser.events import CloseTabEvent
from browser_use.browser.session import BrowserSession, Target
from browser_use.browser.session_manager import SessionManager


def _fake_root_client(target_infos: list[dict]) -> SimpleNamespace:
	return SimpleNamespace(
		send=SimpleNamespace(
			Target=SimpleNamespace(
				getTargets=AsyncMock(return_value={'targetInfos': target_infos}),
			)
		)
	)


@pytest.mark.asyncio
async def test_get_current_page_url_refreshes_stale_focused_target_metadata():
	session = BrowserSession(headless=True)
	session._use_native_computer_use = True
	manager = SessionManager(session)
	object.__setattr__(session, 'session_manager', manager)

	target_id = 'focused-target'
	manager._targets[target_id] = Target(
		target_id=target_id,
		target_type='page',
		url='https://safe.surfcrew.com/https://www.huffpost.com/old',
		title='Old Title',
	)
	session.agent_focus_target_id = target_id
	session._cdp_client_root = _fake_root_client(
		[
			{
				'targetId': target_id,
				'type': 'page',
				'url': 'https://safe.surfcrew.com/https://news.google.com',
				'title': 'Google News',
			}
		]
	)

	current_url = await session.get_current_page_url()
	current_title = await session.get_current_page_title()

	assert current_url == 'https://safe.surfcrew.com/https://news.google.com'
	assert current_title == 'Google News'
	assert manager.get_target(target_id).url == current_url


@pytest.mark.asyncio
async def test_get_tabs_refreshes_cached_tab_metadata_from_live_snapshot():
	session = BrowserSession(headless=True)
	session._use_native_computer_use = True
	manager = SessionManager(session)
	object.__setattr__(session, 'session_manager', manager)

	manager._targets['tab-1'] = Target(
		target_id='tab-1',
		target_type='page',
		url='https://safe.surfcrew.com/https://news.google.com/home',
		title='Google News',
	)
	manager._targets['tab-2'] = Target(
		target_id='tab-2',
		target_type='page',
		url='https://safe.surfcrew.com/https://www.huffpost.com/old',
		title='Old HuffPost',
	)
	session._cdp_client_root = _fake_root_client(
		[
			{
				'targetId': 'tab-1',
				'type': 'page',
				'url': 'https://safe.surfcrew.com/https://news.google.com/home',
				'title': 'Google News',
			},
			{
				'targetId': 'tab-2',
				'type': 'page',
				'url': 'https://safe.surfcrew.com/https://news.google.com',
				'title': 'Google News',
			},
		]
	)

	tabs = await session.get_tabs()

	assert [tab.url for tab in tabs] == [
		'https://safe.surfcrew.com/https://news.google.com/home',
		'https://safe.surfcrew.com/https://news.google.com',
	]
	assert tabs[1].title == 'Google News'


@pytest.mark.asyncio
async def test_dom_mode_keeps_event_driven_target_cache_behavior():
	session = BrowserSession(headless=True)
	manager = SessionManager(session)
	object.__setattr__(session, 'session_manager', manager)

	target_id = 'focused-target'
	manager._targets[target_id] = Target(
		target_id=target_id,
		target_type='page',
		url='https://cached.example/old',
		title='Cached Title',
	)
	session.agent_focus_target_id = target_id
	session._cdp_client_root = _fake_root_client(
		[
			{
				'targetId': target_id,
				'type': 'page',
				'url': 'https://live.example/new',
				'title': 'Live Title',
			}
		]
	)

	current_url = await session.get_current_page_url()
	current_title = await session.get_current_page_title()

	assert current_url == 'https://cached.example/old'
	assert current_title == 'Cached Title'


@pytest.mark.asyncio
async def test_close_tab_relies_on_detach_recovery_for_focused_tab():
	session = BrowserSession(headless=True)
	session.agent_focus_target_id = 'closing-target'
	manager = SimpleNamespace(ensure_valid_focus=AsyncMock(return_value=True))
	object.__setattr__(session, 'session_manager', manager)

	close_target = AsyncMock(return_value={'success': True})
	fake_cdp_session = SimpleNamespace(
		cdp_client=SimpleNamespace(send=SimpleNamespace(Target=SimpleNamespace(closeTarget=close_target)))
	)

	with patch.object(BrowserSession, 'get_or_create_cdp_session', new=AsyncMock(return_value=fake_cdp_session)):
		await session.on_CloseTabEvent(CloseTabEvent(target_id='closing-target', event_timeout=4.0))

	close_target.assert_awaited_once()
	manager.ensure_valid_focus.assert_awaited_once_with(timeout=4.0)
