import asyncio
import logging
from types import SimpleNamespace

import pytest

from browser_use.dom.service import DomService


@pytest.mark.asyncio
async def test_cancelled_dom_capture_drains_parallel_cdp_tasks():
	started = 0
	cancelled = 0
	all_started = asyncio.Event()

	async def block():
		nonlocal started, cancelled
		started += 1
		if started == 4:
			all_started.set()
		try:
			await asyncio.Future()
		except asyncio.CancelledError:
			cancelled += 1
			raise

	class Runtime:
		async def evaluate(self, params=None, session_id=None):
			if params and params.get('includeCommandLineAPI'):
				return {'result': {}}
			return {'result': {'value': {}}}

	class DOMSnapshot:
		async def captureSnapshot(self, params=None, session_id=None):
			return await block()

	class DOM:
		async def getDocument(self, params=None, session_id=None):
			return await block()

	class Page:
		async def getFrameTree(self, session_id=None):
			return {'frameTree': {'frame': {'id': 'root'}}}

		async def getLayoutMetrics(self, session_id=None):
			return await block()

	class Accessibility:
		async def getFullAXTree(self, params=None, session_id=None):
			return await block()

	cdp_session = SimpleNamespace(
		session_id='session',
		cdp_client=SimpleNamespace(
			send=SimpleNamespace(
				Runtime=Runtime(),
				DOMSnapshot=DOMSnapshot(),
				DOM=DOM(),
				Page=Page(),
				Accessibility=Accessibility(),
			)
		),
	)
	browser_session = SimpleNamespace(
		logger=logging.getLogger(__name__),
		get_or_create_cdp_session=lambda **kwargs: asyncio.sleep(0, result=cdp_session),
	)
	service = DomService(browser_session)

	capture = asyncio.create_task(service._get_all_trees('target'))
	await asyncio.wait_for(all_started.wait(), timeout=1)
	capture.cancel()
	with pytest.raises(asyncio.CancelledError):
		await capture

	assert cancelled == 4


@pytest.mark.asyncio
async def test_ax_tree_requests_are_batched():
	running = 0
	peak = 0

	class Page:
		async def getFrameTree(self, session_id=None):
			return {
				'frameTree': {
					'frame': {'id': 'root'},
					'childFrames': [{'frame': {'id': f'child-{index}'}} for index in range(19)],
				}
			}

	class Accessibility:
		async def getFullAXTree(self, params=None, session_id=None):
			nonlocal running, peak
			running += 1
			peak = max(peak, running)
			await asyncio.sleep(0)
			running -= 1
			return {'nodes': []}

	cdp_session = SimpleNamespace(
		session_id='session',
		cdp_client=SimpleNamespace(send=SimpleNamespace(Page=Page(), Accessibility=Accessibility())),
	)
	browser_session = SimpleNamespace(
		logger=logging.getLogger(__name__),
		get_or_create_cdp_session=lambda **kwargs: asyncio.sleep(0, result=cdp_session),
	)

	await DomService(browser_session)._get_ax_tree_for_all_frames('target')

	assert peak == 8


@pytest.mark.asyncio
async def test_retry_pending_tasks_are_drained(monkeypatch):
	"""Forcing the retry branch and reporting everything pending must cancel+drain retry tasks."""
	started = 0
	cancelled = 0

	async def block():
		nonlocal started, cancelled
		started += 1
		try:
			await asyncio.Future()
		except asyncio.CancelledError:
			cancelled += 1
			raise

	class Runtime:
		async def evaluate(self, params=None, session_id=None):
			if params and params.get('includeCommandLineAPI'):
				return {'result': {}}
			return {'result': {'value': {}}}

	class DOMSnapshot:
		async def captureSnapshot(self, params=None, session_id=None):
			return await block()

	class DOM:
		async def getDocument(self, params=None, session_id=None):
			return await block()

	class Page:
		async def getFrameTree(self, session_id=None):
			return {'frameTree': {'frame': {'id': 'root'}}}

		async def getLayoutMetrics(self, session_id=None):
			return await block()

	class Accessibility:
		async def getFullAXTree(self, params=None, session_id=None):
			return await block()

	cdp_session = SimpleNamespace(
		session_id='session',
		cdp_client=SimpleNamespace(
			send=SimpleNamespace(
				Runtime=Runtime(), DOMSnapshot=DOMSnapshot(), DOM=DOM(), Page=Page(), Accessibility=Accessibility()
			)
		),
	)
	browser_session = SimpleNamespace(
		logger=logging.getLogger(__name__),
		get_or_create_cdp_session=lambda **kwargs: asyncio.sleep(0, result=cdp_session),
	)

	calls = 0

	async def fake_wait(tasks, timeout=None):
		nonlocal calls
		calls += 1
		# Let the freshly-created tasks start running before we report them all pending.
		for _ in range(5):
			await asyncio.sleep(0)
		return set(), set(tasks)

	monkeypatch.setattr(asyncio, 'wait', fake_wait)

	# Both required tasks fail (all pending → cancelled), so a TimeoutError is expected.
	with pytest.raises(TimeoutError):
		await DomService(browser_session)._get_all_trees('target')

	assert calls == 2  # primary wait + retry wait
	assert cancelled == 8  # 4 primary + 4 retry tasks all drained


@pytest.mark.asyncio
async def test_optional_precapture_timeout_still_reaches_main_group():
	"""A pre-capture phase that hangs must be bounded and let the main CDP group run."""
	snapshot_called = asyncio.Event()

	class Runtime:
		async def evaluate(self, params=None, session_id=None):
			# readyState phase hangs; it must be bounded and not block the main group.
			if params and params.get('expression') == 'document.readyState':
				await asyncio.Future()
			if params and params.get('includeCommandLineAPI'):
				return {'result': {}}
			return {'result': {'value': {}}}

	class DOMSnapshot:
		async def captureSnapshot(self, params=None, session_id=None):
			snapshot_called.set()
			return {'documents': [], 'strings': []}

	class DOM:
		async def getDocument(self, params=None, session_id=None):
			return {'root': {}}

	class Page:
		async def getFrameTree(self, session_id=None):
			return {'frameTree': {'frame': {'id': 'root'}}}

		async def getLayoutMetrics(self, session_id=None):
			return {}

	class Accessibility:
		async def getFullAXTree(self, params=None, session_id=None):
			return {'nodes': []}

	cdp_session = SimpleNamespace(
		session_id='session',
		cdp_client=SimpleNamespace(
			send=SimpleNamespace(
				Runtime=Runtime(), DOMSnapshot=DOMSnapshot(), DOM=DOM(), Page=Page(), Accessibility=Accessibility()
			)
		),
	)
	browser_session = SimpleNamespace(
		logger=logging.getLogger(__name__),
		get_or_create_cdp_session=lambda **kwargs: asyncio.sleep(0, result=cdp_session),
	)

	# 3s bounded readyState + main group; well under any state budget.
	result = await asyncio.wait_for(DomService(browser_session)._get_all_trees('target'), timeout=20)
	assert snapshot_called.is_set()
	assert result.snapshot == {'documents': [], 'strings': []}


@pytest.mark.asyncio
async def test_total_ax_work_capped_at_max_iframes():
	"""274 discovered frames must issue at most max_iframes (20) AX requests."""
	ax_requests = 0

	class Page:
		async def getFrameTree(self, session_id=None):
			return {
				'frameTree': {
					'frame': {'id': 'root'},
					'childFrames': [{'frame': {'id': f'child-{index}'}} for index in range(273)],
				}
			}

	class Accessibility:
		async def getFullAXTree(self, params=None, session_id=None):
			nonlocal ax_requests
			ax_requests += 1
			await asyncio.sleep(0)
			return {'nodes': []}

	cdp_session = SimpleNamespace(
		session_id='session',
		cdp_client=SimpleNamespace(send=SimpleNamespace(Page=Page(), Accessibility=Accessibility())),
	)
	browser_session = SimpleNamespace(
		logger=logging.getLogger(__name__),
		get_or_create_cdp_session=lambda **kwargs: asyncio.sleep(0, result=cdp_session),
	)

	await DomService(browser_session, max_iframes=20)._get_ax_tree_for_all_frames('target')

	assert ax_requests == 20  # root + 19 children


@pytest.mark.asyncio
async def test_ax_failure_preserves_snapshot_and_dom():
	"""AX failing must not discard valid snapshot+DOM; state degrades to an empty AX tree."""

	class Runtime:
		async def evaluate(self, params=None, session_id=None):
			if params and params.get('includeCommandLineAPI'):
				return {'result': {}}
			return {'result': {'value': {}}}

	class DOMSnapshot:
		async def captureSnapshot(self, params=None, session_id=None):
			return {'documents': [], 'strings': []}

	class DOM:
		async def getDocument(self, params=None, session_id=None):
			return {'root': {'nodeId': 1}}

	class Page:
		async def getFrameTree(self, session_id=None):
			# Root frame AX will be requested and must fail on both attempts.
			return {'frameTree': {'frame': {'id': 'root'}}}

		async def getLayoutMetrics(self, session_id=None):
			return {}

	class Accessibility:
		async def getFullAXTree(self, params=None, session_id=None):
			raise RuntimeError('AX unavailable')

	cdp_session = SimpleNamespace(
		session_id='session',
		cdp_client=SimpleNamespace(
			send=SimpleNamespace(
				Runtime=Runtime(), DOMSnapshot=DOMSnapshot(), DOM=DOM(), Page=Page(), Accessibility=Accessibility()
			)
		),
	)
	browser_session = SimpleNamespace(
		logger=logging.getLogger(__name__),
		get_or_create_cdp_session=lambda **kwargs: asyncio.sleep(0, result=cdp_session),
	)

	result = await DomService(browser_session)._get_all_trees('target')

	assert result.snapshot == {'documents': [], 'strings': []}
	assert result.dom_tree == {'root': {'nodeId': 1}}
	assert result.ax_tree == {'nodes': []}
	assert result.device_pixel_ratio == 1.0
