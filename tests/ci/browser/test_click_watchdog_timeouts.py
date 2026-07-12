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
	assert event.event_timeout == 15.0


@pytest.mark.asyncio
async def test_click_coordinate_deadline_wraps_click_coro(monkeypatch):
	import asyncio

	session = BrowserSession(headless=True)
	session.agent_focus_target_id = 'target-1'
	session._downloads_watchdog = _NoopDownloadsWatchdog()
	watchdog = DefaultActionWatchdog(event_bus=session.event_bus, browser_session=session)

	async def slow_click(*args, **kwargs):
		await asyncio.sleep(1.0)

	monkeypatch.setattr(watchdog, '_click_on_coordinate', slow_click)

	event = ClickCoordinateEvent(coordinate_x=100, coordinate_y=200, force=True, event_timeout=0.01)

	with pytest.raises(TimeoutError):
		await watchdog.on_ClickCoordinateEvent(event)


@pytest.mark.asyncio
async def test_click_deadline_timeout_has_labeled_message(monkeypatch):
	"""A deadline expiry must raise a non-empty, self-identifying message, not a bare TimeoutError."""
	import asyncio

	from browser_use.browser.watchdogs.default_action_watchdog import _await_with_deadline

	async def slow():
		await asyncio.sleep(1.0)

	deadline = time.monotonic() + 0.01
	with pytest.raises(TimeoutError) as exc_info:
		await _await_with_deadline(slow(), deadline, 'coordinate click')

	message = str(exc_info.value)
	assert message  # not empty
	assert 'coordinate click' in message
	assert 'event deadline' in message


@pytest.mark.asyncio
async def test_act_preserves_inner_labeled_timeout(monkeypatch):
	"""Tools.act must keep the inner labeled timeout (naming the real operation) instead of
	rewriting it as the generic outer per-action budget."""
	from types import SimpleNamespace

	from browser_use.tools.service import Tools

	tools = Tools()

	async def raise_labeled(**kwargs):
		raise TimeoutError('coordinate click exceeded event deadline after 45.0s')

	monkeypatch.setattr(tools.registry, 'execute_action', raise_labeled)

	action = SimpleNamespace(model_dump=lambda exclude_unset=True: {'click': {'index': 1}})
	result = await tools.act(action=action, browser_session=SimpleNamespace(), action_timeout=180)

	assert result.error == 'coordinate click exceeded event deadline after 45.0s'


@pytest.mark.asyncio
async def test_act_reports_outer_budget_on_bare_timeout(monkeypatch):
	"""When the outer asyncio.wait_for cap fires (bare, empty TimeoutError), act reports the
	configured per-action budget rather than an empty message."""
	import asyncio
	from types import SimpleNamespace

	from browser_use.tools.service import Tools

	tools = Tools()

	async def hang(**kwargs):
		await asyncio.sleep(1.0)

	monkeypatch.setattr(tools.registry, 'execute_action', hang)

	action = SimpleNamespace(model_dump=lambda exclude_unset=True: {'click': {'index': 1}})
	result = await tools.act(action=action, browser_session=SimpleNamespace(), action_timeout=0.05)

	assert 'timed out after' in result.error


@pytest.mark.asyncio
async def test_click_element_deadline_wraps_click_coro(monkeypatch):
	import asyncio

	from browser_use.browser.events import ClickElementEvent
	from browser_use.dom.views import EnhancedDOMTreeNode, NodeType

	session = BrowserSession(headless=True)
	session.agent_focus_target_id = 'target-1'
	session._downloads_watchdog = _NoopDownloadsWatchdog()
	watchdog = DefaultActionWatchdog(event_bus=session.event_bus, browser_session=session)

	async def slow_click(*args, **kwargs):
		await asyncio.sleep(1.0)

	monkeypatch.setattr(watchdog, '_click_element_node_impl', slow_click)

	node = EnhancedDOMTreeNode(
		node_id=1,
		backend_node_id=1,
		node_type=NodeType.ELEMENT_NODE,
		node_name='BUTTON',
		node_value='',
		attributes={},
		is_scrollable=None,
		is_visible=True,
		absolute_position=None,
		target_id='target-1',
		frame_id=None,
		session_id=None,
		content_document=None,
		shadow_root_type=None,
		shadow_roots=None,
		parent_node=None,
		children_nodes=None,
		ax_node=None,
		snapshot_node=None,
	)

	event = ClickElementEvent(node=node, event_timeout=0.01)

	with pytest.raises(TimeoutError):
		await watchdog.on_ClickElementEvent(event)
