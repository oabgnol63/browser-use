import asyncio
import json
from unittest.mock import AsyncMock, Mock

import pytest
from pytest_httpserver import HTTPServer

from browser_use.tools import service as tools_service_module
from browser_use.browser import BrowserProfile, BrowserSession
from browser_use.browser.events import ClickMultipleCoordinatesEvent
from browser_use.llm.google.chat import ChatGoogle
from browser_use.llm import BaseChatModel
from browser_use.llm.views import ChatInvokeCompletion
from browser_use.tools.registry.views import Backend, Mode
from browser_use.tools.service import Tools
from browser_use.tools.views import VisionClickLoopAction, VisionClickLoopDecision, VisionFinishDecision


@pytest.fixture(scope='session')
def http_server():
	"""Serve a visual two-round challenge for coordinate-click loop tests."""
	server = HTTPServer()
	server.start()

	server.expect_request('/vision-challenge').respond_with_data(
		"""
		<!DOCTYPE html>
		<html>
		<head>
			<title>Vision Challenge</title>
			<style>
				html, body { margin: 0; padding: 0; width: 100%; height: 100%; overflow: hidden; font-family: sans-serif; }
				body { background: #f6f7fb; }
				#stage { position: relative; width: 100vw; height: 100vh; }
				#status { position: absolute; top: 24px; left: 24px; font-size: 24px; color: #1f2937; }
				.tile {
					position: absolute;
					width: 120px;
					height: 120px;
					border: 3px solid #111827;
					background: linear-gradient(135deg, #fde68a, #f97316);
					color: transparent;
					cursor: pointer;
				}
				#submit {
					position: absolute;
					right: 48px;
					bottom: 48px;
					width: 180px;
					height: 64px;
					font-size: 22px;
				}
			</style>
		</head>
		<body>
			<div id="stage">
				<div id="status">Round 1 ready</div>
				<button id="submit" type="button" onclick="submitChallenge()">Submit</button>
			</div>

			<script>
				const layouts = {
					1: [
						{ id: 'r1-a', left: 120, top: 140 },
						{ id: 'r1-b', left: 320, top: 140 }
					],
					2: [
						{ id: 'r2-a', left: 980, top: 220 },
						{ id: 'r2-b', left: 1180, top: 220 }
					]
				};

				window.visionChallengeState = {
					round: 1,
					selected: [],
					completed: false,
					submitted: false,
					status: 'Round 1 ready'
				};

				function render() {
					const state = window.visionChallengeState;
					const stage = document.getElementById('stage');
					document.querySelectorAll('.tile').forEach((tile) => tile.remove());
					document.body.setAttribute('data-round', String(state.round));
					document.body.setAttribute('data-completed', state.completed ? 'true' : 'false');
					document.getElementById('status').textContent = state.status;

					if (state.completed) {
						return;
					}

					for (const tile of layouts[state.round]) {
						const button = document.createElement('button');
						button.type = 'button';
						button.className = 'tile';
						button.style.left = tile.left + 'px';
						button.style.top = tile.top + 'px';
						button.setAttribute('data-tile-id', tile.id);
						button.onclick = () => selectTile(tile.id);
						stage.appendChild(button);
					}
				}

				function selectTile(tileId) {
					const state = window.visionChallengeState;
					if (!state.selected.includes(tileId)) {
						state.selected.push(tileId);
					}

					if (state.selected.length >= layouts[state.round].length) {
						if (state.round === 1) {
							state.round = 2;
							state.selected = [];
							state.status = 'Loading round 2';
							render();
							setTimeout(() => {
								state.status = 'Round 2 ready';
								render();
							}, 350);
							return;
						}

						state.completed = true;
						state.status = 'Challenge complete - ready to submit';
						render();
						return;
					}

					state.status = 'Selected ' + state.selected.length + ' tile(s) in round ' + state.round;
					document.getElementById('status').textContent = state.status;
				}

				function submitChallenge() {
					const state = window.visionChallengeState;
					state.submitted = true;
					state.status = state.completed ? 'Submitted' : 'Please complete 2nd round';
					render();
				}

				render();
			</script>
		</body>
		</html>
		""",
		content_type='text/html',
	)

	server.expect_request('/vision-checkbox-challenge').respond_with_data(
		"""
		<!DOCTYPE html>
		<html>
		<head>
			<title>Vision Checkbox Challenge</title>
			<style>
				html, body { margin: 0; padding: 0; width: 100%; height: 100%; overflow: hidden; font-family: sans-serif; }
				body { background: #eef2ff; }
				#stage { position: relative; width: 100vw; height: 100vh; }
				#status { position: absolute; top: 24px; left: 24px; font-size: 24px; color: #1f2937; }
				#checkbox {
					position: absolute;
					left: 120px;
					top: 160px;
					width: 360px;
					height: 88px;
					border: 2px solid #111827;
					background: white;
					font-size: 26px;
				}
				.tile {
					position: absolute;
					width: 120px;
					height: 120px;
					border: 3px solid #111827;
					background: linear-gradient(135deg, #86efac, #22c55e);
					color: transparent;
					cursor: pointer;
				}
				#verify {
					position: absolute;
					right: 48px;
					bottom: 48px;
					width: 200px;
					height: 64px;
					font-size: 22px;
				}
			</style>
		</head>
		<body>
			<div id="stage">
				<div id="status">Checkbox ready</div>
				<button id="checkbox" type="button" onclick="startChallenge()">I'm not a robot</button>
				<button id="verify" type="button" onclick="verifyChallenge()">Verify</button>
			</div>

			<script>
				const layouts = {
					1: [
						{ id: 'r1-a', left: 120, top: 320 },
						{ id: 'r1-b', left: 320, top: 320 }
					],
					2: [
						{ id: 'r2-a', left: 920, top: 320 },
						{ id: 'r2-b', left: 1120, top: 320 }
					]
				};

				window.visionCheckboxChallengeState = {
					checkboxClicked: false,
					round: 0,
					selected: [],
					completed: false,
					submitted: false,
					status: 'Checkbox ready'
				};

				function render() {
					const state = window.visionCheckboxChallengeState;
					const stage = document.getElementById('stage');
					document.querySelectorAll('.tile').forEach((tile) => tile.remove());
					document.body.setAttribute('data-checkbox-clicked', state.checkboxClicked ? 'true' : 'false');
					document.body.setAttribute('data-round', String(state.round));
					document.body.setAttribute('data-completed', state.completed ? 'true' : 'false');
					document.getElementById('status').textContent = state.status;
					document.getElementById('checkbox').style.display = state.checkboxClicked ? 'none' : 'block';
					document.getElementById('verify').style.display = state.checkboxClicked ? 'block' : 'none';

					if (!state.checkboxClicked || state.completed || state.round === 0) {
						return;
					}

					for (const tile of layouts[state.round]) {
						const button = document.createElement('button');
						button.type = 'button';
						button.className = 'tile';
						button.style.left = tile.left + 'px';
						button.style.top = tile.top + 'px';
						button.onclick = () => selectTile(tile.id);
						stage.appendChild(button);
					}
				}

				function startChallenge() {
					const state = window.visionCheckboxChallengeState;
					if (state.checkboxClicked) {
						return;
					}
					state.checkboxClicked = true;
					state.status = 'Loading challenge';
					render();
					setTimeout(() => {
						state.round = 1;
						state.status = 'Round 1 ready';
						render();
					}, 250);
				}

				function selectTile(tileId) {
					const state = window.visionCheckboxChallengeState;
					if (!state.selected.includes(tileId)) {
						state.selected.push(tileId);
					}

					if (state.selected.length >= layouts[state.round].length) {
						if (state.round === 1) {
							state.round = 2;
							state.selected = [];
							state.status = 'Loading round 2';
							render();
							setTimeout(() => {
								state.status = 'Round 2 ready';
								render();
							}, 250);
							return;
						}

						state.completed = true;
						state.status = 'Challenge complete - ready to verify';
						render();
						return;
					}

					state.status = 'Selected ' + state.selected.length + ' tile(s) in round ' + state.round;
					document.getElementById('status').textContent = state.status;
				}

				function verifyChallenge() {
					const state = window.visionCheckboxChallengeState;
					state.submitted = true;
					state.status = state.completed ? 'Verified' : 'Please complete all rounds';
					render();
				}

				render();
			</script>
		</body>
		</html>
		""",
		content_type='text/html',
	)

	server.expect_request('/vision-4x4-inline-finish').respond_with_data(
		"""
		<!DOCTYPE html>
		<html>
		<head>
			<title>Vision 4x4 Inline Finish</title>
			<style>
				html, body { margin: 0; padding: 0; width: 100%; height: 100%; overflow: hidden; font-family: sans-serif; }
				body { background: #f8fafc; }
				#stage { position: relative; width: 100vw; height: 100vh; }
				#status { position: absolute; top: 24px; left: 24px; font-size: 24px; color: #1f2937; }
				.tile {
					position: absolute;
					width: 120px;
					height: 120px;
					border: 3px solid #111827;
					background: linear-gradient(135deg, #93c5fd, #2563eb);
					color: transparent;
					cursor: pointer;
				}
				#finish {
					position: absolute;
					right: 48px;
					bottom: 48px;
					width: 220px;
					height: 64px;
					font-size: 22px;
				}
			</style>
		</head>
		<body>
			<div id="stage">
				<div id="status">Select all bicycle tiles</div>
				<button id="finish" type="button" onclick="submitChallenge()">Skip</button>
			</div>
			<script>
				const requiredTiles = ['a', 'b', 'c', 'd'];
				const layout = [
					{ id: 'a', left: 120, top: 140 },
					{ id: 'b', left: 320, top: 140 },
					{ id: 'c', left: 980, top: 220 },
					{ id: 'd', left: 1180, top: 220 }
				];

				window.vision4x4State = {
					selected: [],
					submitted: false,
					completed: false,
					buttonLabel: 'Skip',
					status: 'Select all bicycle tiles'
				};

				function render() {
					const state = window.vision4x4State;
					document.getElementById('finish').textContent = state.buttonLabel;
					document.getElementById('status').textContent = state.status;
					document.body.setAttribute('data-button-label', state.buttonLabel);
				}

				for (const tile of layout) {
					const button = document.createElement('button');
					button.type = 'button';
					button.className = 'tile';
					button.style.left = tile.left + 'px';
					button.style.top = tile.top + 'px';
					button.setAttribute('data-tile-id', tile.id);
					button.onclick = () => selectTile(tile.id);
					document.getElementById('stage').appendChild(button);
				}

				function selectTile(tileId) {
					const state = window.vision4x4State;
					if (!state.selected.includes(tileId)) {
						state.selected.push(tileId);
					}
					if (state.selected.length === 0) {
						state.buttonLabel = 'Skip';
					} else if (state.selected.length < requiredTiles.length) {
						state.buttonLabel = 'Next';
					} else {
						state.buttonLabel = 'Verify';
						state.completed = true;
					}
					state.status = 'Selected ' + state.selected.length + ' tile(s)';
					render();
				}

				function submitChallenge() {
					const state = window.vision4x4State;
					state.submitted = true;
					state.status = state.completed ? 'Verified' : 'Submitted early';
					render();
				}

				render();
			</script>
		</body>
		</html>
		""",
		content_type='text/html',
	)

	yield server
	server.stop()


@pytest.fixture(scope='session')
def base_url(http_server):
	return f'http://{http_server.host}:{http_server.port}'


@pytest.fixture(scope='module')
async def browser_session():
	session = BrowserSession(
		browser_profile=BrowserProfile(
			headless=True,
			user_data_dir=None,
			keep_alive=True,
		)
	)
	await session.start()
	yield session
	await session.kill()
	await session.event_bus.stop(clear=True, timeout=5)


@pytest.fixture(scope='function')
def tools():
	return Tools()


def _build_mock_action_llm(
	decisions: list[dict],
	required_prompt_texts: list[str] | None = None,
	required_image_detail: str | None = None,
) -> AsyncMock:
	mock_llm = AsyncMock(spec=BaseChatModel)
	mock_llm.model = 'mock-vision-llm'
	mock_llm._verified_api_keys = True
	mock_llm.provider = 'mock'
	mock_llm.name = 'mock-vision-llm'
	mock_llm.model_name = 'mock-vision-llm'

	decision_queue = list(decisions)

	async def custom_ainvoke(messages, output_format=None, **kwargs):
		has_image = False
		text_parts: list[str] = []
		for msg in messages:
			content = getattr(msg, 'content', None)
			if isinstance(content, str):
				text_parts.append(content)
			if isinstance(content, list):
				for part in content:
					if hasattr(part, 'type') and part.type == 'image_url':
						has_image = True
						if required_image_detail is not None:
							assert getattr(part.image_url, 'detail', None) == required_image_detail
					text = getattr(part, 'text', None)
					if isinstance(text, str):
						text_parts.append(text)
		assert has_image, 'vision_click_loop should send a screenshot to the action LLM'
		if required_prompt_texts:
			combined_text = '\n'.join(text_parts)
			for expected_text in required_prompt_texts:
				assert expected_text in combined_text, f'Missing prompt text: {expected_text}'

		payload = decision_queue.pop(0)
		if output_format is not None:
			completion = output_format.model_validate(payload)
		else:
			completion = json.dumps(payload)
		return ChatInvokeCompletion(completion=completion, usage=None)

	mock_llm.ainvoke.side_effect = custom_ainvoke
	return mock_llm


class TestVisionClickLoop:
	def test_registered(self, tools):
		action = tools.registry.registry.actions.get('vision_click_loop')
		assert action is not None
		assert action.modes == {Mode.DOM, Mode.VISION}
		assert action.backends == {Backend.CDP, Backend.WEBDRIVER}

	def test_action_defaults_allow_full_batch(self):
		action = VisionClickLoopAction(instruction='click all matching challenge tiles')
		assert action.max_rounds == 5

	async def test_vision_click_loop_handles_two_visual_rounds(self, browser_session, base_url, tools):
		await tools.navigate(url=f'{base_url}/vision-challenge', new_tab=False, browser_session=browser_session)
		await asyncio.sleep(0.5)
		highlight_mock = AsyncMock()
		original_dispatch = browser_session.event_bus.dispatch
		original_highlight = browser_session.highlight_coordinate_click
		dispatched_click_events: list[ClickMultipleCoordinatesEvent] = []
		object.__setattr__(browser_session, 'highlight_coordinate_click', highlight_mock)

		def spy_dispatch(event):
			if isinstance(event, ClickMultipleCoordinatesEvent):
				dispatched_click_events.append(event)
			return original_dispatch(event)

		object.__setattr__(browser_session.event_bus, 'dispatch', spy_dispatch)

		try:
			mock_llm = _build_mock_action_llm(
				[
					{
						'status': 'click_more',
						'clicks': [{'x': 180, 'y': 200}, {'x': 380, 'y': 200}],
						'reasoning': 'Round 1 matching tiles are visible.',
					},
					{
						'status': 'click_more',
						'clicks': [{'x': 1040, 'y': 280}, {'x': 1240, 'y': 280}],
						'reasoning': 'Round 2 matching tiles are visible.',
					},
					{
						'status': 'click_finish',
						'clicks': [],
						'finish_click': {'x': 1780, 'y': 1000},
						'reasoning': 'The tile rounds appear complete, and the Submit button is visible.',
					},
				],
				required_prompt_texts=[
					'Choose exactly one status: click_more, click_finish, or ready_to_submit.',
					'If an unchecked reCAPTCHA-style checkbox is visible and the image challenge has not opened yet, use click_more with the checkbox center first.',
					'When multiple visible images clearly match the instruction, return them all in the SAME click_more response.',
					'If the challenge is a 3x3 grid, expect replacement tiles after each click',
					'For a 4x4 grid, if the Next/Verify/Skip button is visible in the CURRENT screenshot and should be pressed immediately after the tile selections, return status=click_more',
				],
			)

			result = await tools.vision_click_loop(
				instruction='click all matching challenge tiles',
				browser_session=browser_session,
				action_llm=mock_llm,
			)

			assert result.error is None, result.error
			assert result.metadata is not None
			assert result.metadata['ready_to_submit'] is True
			assert result.metadata['stop_reason'] == 'finish_clicked'
			assert result.metadata['rounds_executed'] == 3
			assert result.metadata['total_clicked'] == 5
			highlight_mock.assert_not_called()
			assert dispatched_click_events
			assert all(event.human_like is False for event in dispatched_click_events)
			assert all(event.highlight is False for event in dispatched_click_events)

			cdp_session = await browser_session.get_or_create_cdp_session()
			js_result = await cdp_session.cdp_client.send.Runtime.evaluate(
				params={'expression': 'JSON.stringify(window.visionChallengeState)', 'returnByValue': True},
				session_id=cdp_session.session_id,
			)
			state = json.loads(js_result['result']['value'])
			assert state['completed'] is True
			assert state['submitted'] is True
			assert state['status'] == 'Submitted'
		finally:
			object.__setattr__(browser_session.event_bus, 'dispatch', original_dispatch)
			object.__setattr__(browser_session, 'highlight_coordinate_click', original_highlight)

	async def test_vision_click_loop_can_begin_from_checkbox(self, browser_session, base_url, tools):
		await tools.navigate(url=f'{base_url}/vision-checkbox-challenge', new_tab=False, browser_session=browser_session)
		await asyncio.sleep(0.5)

		mock_llm = _build_mock_action_llm(
			[
				{
					'status': 'click_more',
					'clicks': [{'x': 300, 'y': 205}],
					'reasoning': 'The checkbox is visible and should be clicked first to open the challenge.',
				},
				{
					'status': 'click_more',
					'clicks': [{'x': 180, 'y': 380}, {'x': 380, 'y': 380}],
					'reasoning': 'Round 1 matching tiles are visible.',
				},
				{
					'status': 'click_more',
					'clicks': [{'x': 980, 'y': 380}, {'x': 1180, 'y': 380}],
					'reasoning': 'Round 2 matching tiles are visible.',
				},
				{
					'status': 'click_finish',
					'clicks': [],
					'finish_click': {'x': 1780, 'y': 1000},
					'reasoning': 'The challenge is complete and Verify is visible.',
				},
			]
		)

		result = await tools.vision_click_loop(
			instruction='complete the recaptcha challenge',
			browser_session=browser_session,
			action_llm=mock_llm,
		)

		assert result.error is None, result.error
		assert result.metadata is not None
		assert result.metadata['ready_to_submit'] is True
		assert result.metadata['stop_reason'] == 'finish_clicked'
		assert result.metadata['rounds_executed'] == 4
		assert result.metadata['total_clicked'] == 6

		cdp_session = await browser_session.get_or_create_cdp_session()
		js_result = await cdp_session.cdp_client.send.Runtime.evaluate(
			params={'expression': 'JSON.stringify(window.visionCheckboxChallengeState)', 'returnByValue': True},
			session_id=cdp_session.session_id,
		)
		state = json.loads(js_result['result']['value'])
		assert state['checkboxClicked'] is True
		assert state['completed'] is True
		assert state['submitted'] is True
		assert state['status'] == 'Verified'

	async def test_vision_click_loop_4x4_can_click_tiles_and_button_in_same_round(self, browser_session, base_url, tools):
		await tools.navigate(url=f'{base_url}/vision-4x4-inline-finish', new_tab=False, browser_session=browser_session)
		await asyncio.sleep(0.5)

		mock_llm = _build_mock_action_llm(
			[
				{
					'status': 'click_more',
					'clicks': [
						{'x': 180, 'y': 200},
						{'x': 380, 'y': 200},
						{'x': 1040, 'y': 280},
						{'x': 1240, 'y': 280},
					],
					'finish_click': {'x': 1780, 'y': 1000},
					'reasoning': '4x4 grid: click all bicycle tiles, then press the same button coordinate immediately.',
				}
			]
		)

		result = await tools.vision_click_loop(
			instruction='click all matching challenge tiles',
			browser_session=browser_session,
			action_llm=mock_llm,
		)

		assert result.error is None
		assert result.metadata is not None
		assert result.metadata['ready_to_submit'] is True
		assert result.metadata['stop_reason'] == 'finish_clicked'
		assert result.metadata['rounds_executed'] == 1
		assert result.metadata['total_clicked'] == 5

		cdp_session = await browser_session.get_or_create_cdp_session()
		js_result = await cdp_session.cdp_client.send.Runtime.evaluate(
			params={'expression': 'JSON.stringify(window.vision4x4State)', 'returnByValue': True},
			session_id=cdp_session.session_id,
		)
		state = json.loads(js_result['result']['value'])
		assert state['completed'] is True
		assert state['submitted'] is True
		assert state['buttonLabel'] == 'Verify'
		assert state['status'] == 'Verified'

	async def test_vision_click_loop_can_leave_submit_for_later(self, browser_session, base_url, tools):
		await tools.navigate(url=f'{base_url}/vision-challenge', new_tab=False, browser_session=browser_session)
		await asyncio.sleep(0.5)

		mock_llm = _build_mock_action_llm(
			[
				{
					'status': 'click_more',
					'clicks': [{'x': 180, 'y': 200}, {'x': 380, 'y': 200}],
					'reasoning': 'Round 1 matching tiles are visible.',
				},
				{
					'status': 'click_more',
					'clicks': [{'x': 1040, 'y': 280}, {'x': 1240, 'y': 280}],
					'reasoning': 'Round 2 matching tiles are visible.',
				},
				{
					'status': 'click_finish',
					'clicks': [],
					'finish_click': {'x': 1780, 'y': 1000},
					'reasoning': 'The tile rounds appear complete, and the Submit button is visible.',
				},
			]
		)

		result = await tools.vision_click_loop(
			instruction='click all matching challenge tiles',
			click_finish_when_ready=False,
			browser_session=browser_session,
			action_llm=mock_llm,
		)

		assert result.error is None, result.error
		assert result.metadata is not None
		assert result.metadata['ready_to_submit'] is True
		assert result.metadata['stop_reason'] == 'ready_to_submit'
		assert result.metadata['total_clicked'] == 4

		cdp_session = await browser_session.get_or_create_cdp_session()
		js_result = await cdp_session.cdp_client.send.Runtime.evaluate(
			params={'expression': 'JSON.stringify(window.visionChallengeState)', 'returnByValue': True},
			session_id=cdp_session.session_id,
		)
		state = json.loads(js_result['result']['value'])
		assert state['completed'] is True
		assert state['submitted'] is False

	async def test_vision_click_loop_respects_print_llm_messages_env(self, browser_session, base_url, tools, monkeypatch):
		await tools.navigate(url=f'{base_url}/vision-challenge', new_tab=False, browser_session=browser_session)
		await asyncio.sleep(0.5)

		monkeypatch.setenv('BROWSER_USE_PRINT_LLM_MESSAGES', 'true')
		logger_info_mock = Mock()
		monkeypatch.setattr(tools_service_module.logger, 'info', logger_info_mock)

		mock_llm = _build_mock_action_llm(
			[
				{
					'status': 'ready_to_submit',
					'clicks': [],
					'reasoning': 'Stop after logging request and response output.',
				}
			]
		)

		result = await tools.vision_click_loop(
			instruction='click all matching challenge tiles',
			browser_session=browser_session,
			action_llm=mock_llm,
		)

		assert result.error is None
		logged_messages = '\n'.join(str(call.args[0]) for call in logger_info_mock.call_args_list if call.args)
		assert 'VISION CLICK LOOP REQUEST' in logged_messages
		assert 'VISION CLICK LOOP RESPONSE' in logged_messages

	async def test_vision_click_loop_overrides_chatgoogle_for_vision_loop_config(self, browser_session, base_url, tools, monkeypatch):
		await tools.navigate(url=f'{base_url}/vision-challenge', new_tab=False, browser_session=browser_session)
		await asyncio.sleep(0.5)

		observed: dict[str, object] = {}

		async def fake_ainvoke(self, messages, output_format=None, **kwargs):
			observed['model'] = self.model
			observed['thinking_level'] = getattr(self, 'thinking_level', None)
			observed['thinking_budget'] = getattr(self, 'thinking_budget', None)
			for msg in messages:
				content = getattr(msg, 'content', None)
				if isinstance(content, list):
					for part in content:
						if getattr(part, 'type', None) == 'image_url':
							observed['image_detail'] = getattr(part.image_url, 'detail', None)
			completion = output_format.model_validate(
				{
					'status': 'ready_to_submit',
					'clicks': [],
					'reasoning': 'Stop after verifying the override config.',
				}
			)
			return ChatInvokeCompletion(completion=completion, usage=None)

		monkeypatch.setattr(ChatGoogle, 'ainvoke', fake_ainvoke)
		llm = ChatGoogle(model='gemini-3-flash-preview')

		result = await tools.vision_click_loop(
			instruction='click all matching challenge tiles',
			screenshot_detail='low',
			browser_session=browser_session,
			action_llm=llm,
		)

		assert result.error is None
		assert observed['model'] == 'gemini-3-flash-preview'
		assert observed['thinking_level'] == 'medium'
		assert observed['thinking_budget'] is None
		assert observed['image_detail'] == 'high'

	async def test_vision_click_loop_final_round_skips_extra_full_round(self, browser_session, base_url, tools):
		"""final_round=True on a click_more decision should trigger a single lightweight find-finish pass instead of another full LLM round."""
		await tools.navigate(url=f'{base_url}/vision-challenge', new_tab=False, browser_session=browser_session)
		await asyncio.sleep(0.5)

		ainvoke_call_log: list[dict] = []

		async def custom_ainvoke(messages, output_format=None, **kwargs):
			ainvoke_call_log.append({'output_format': output_format})
			if output_format is VisionClickLoopDecision:
				payload = {
					'status': 'click_more',
					'clicks': [
						{'x': 180, 'y': 200}, {'x': 380, 'y': 200},
						{'x': 1040, 'y': 280}, {'x': 1240, 'y': 280},
					],
					'final_round': True,
					'reasoning': 'All matches in the grid clicked; expect Submit next.',
				}
				return ChatInvokeCompletion(completion=output_format.model_validate(payload), usage=None)
			if output_format is VisionFinishDecision:
				payload = {
					'status': 'click_finish',
					'finish_click': {'x': 1780, 'y': 1000},
					'reasoning': 'Submit visible.',
				}
				return ChatInvokeCompletion(completion=output_format.model_validate(payload), usage=None)
			raise AssertionError(f'unexpected output_format: {output_format}')

		mock_llm = AsyncMock(spec=BaseChatModel)
		mock_llm.model = 'mock-vision-llm'
		mock_llm._verified_api_keys = True
		mock_llm.provider = 'mock'
		mock_llm.name = 'mock-vision-llm'
		mock_llm.model_name = 'mock-vision-llm'
		mock_llm.ainvoke.side_effect = custom_ainvoke

		# Drive the JS state forward enough that round 1 click batch completes both rounds
		# of the test page (4 selected tiles -> completed); doesn't matter for this test
		# since we only assert LLM call count and the finish click dispatch.
		result = await tools.vision_click_loop(
			instruction='click all matching tiles',
			browser_session=browser_session,
			action_llm=mock_llm,
		)

		assert result.error is None, result.error
		assert result.metadata is not None
		assert result.metadata['stop_reason'] == 'finish_clicked'
		# Exactly 2 LLM calls: round 1 full decision + 1 lightweight finish pass.
		assert len(ainvoke_call_log) == 2, f'expected 2 LLM calls, got {len(ainvoke_call_log)}'
		assert ainvoke_call_log[0]['output_format'] is VisionClickLoopDecision
		assert ainvoke_call_log[1]['output_format'] is VisionFinishDecision

	async def test_vision_click_loop_final_round_falls_back_when_finish_not_visible(self, browser_session, base_url, tools):
		"""When lightweight pass returns no_finish_visible, the loop should fall through to a full next round."""
		await tools.navigate(url=f'{base_url}/vision-challenge', new_tab=False, browser_session=browser_session)
		await asyncio.sleep(0.5)

		ainvoke_call_log: list[dict] = []

		async def custom_ainvoke(messages, output_format=None, **kwargs):
			ainvoke_call_log.append({'output_format': output_format})
			if output_format is VisionClickLoopDecision:
				if len([c for c in ainvoke_call_log if c['output_format'] is VisionClickLoopDecision]) == 1:
					payload = {
						'status': 'click_more',
						'clicks': [{'x': 180, 'y': 200}, {'x': 380, 'y': 200}],
						'final_round': True,
						'reasoning': 'thought this was the last batch',
					}
				else:
					payload = {
						'status': 'ready_to_submit',
						'clicks': [],
						'reasoning': 'fell back to full round and stopped cleanly',
					}
				return ChatInvokeCompletion(completion=output_format.model_validate(payload), usage=None)
			if output_format is VisionFinishDecision:
				payload = {'status': 'no_finish_visible', 'reasoning': 'no submit visible yet'}
				return ChatInvokeCompletion(completion=output_format.model_validate(payload), usage=None)
			raise AssertionError(f'unexpected output_format: {output_format}')

		mock_llm = AsyncMock(spec=BaseChatModel)
		mock_llm.model = 'mock-vision-llm'
		mock_llm._verified_api_keys = True
		mock_llm.provider = 'mock'
		mock_llm.name = 'mock-vision-llm'
		mock_llm.model_name = 'mock-vision-llm'
		mock_llm.ainvoke.side_effect = custom_ainvoke

		result = await tools.vision_click_loop(
			instruction='click all matching tiles',
			browser_session=browser_session,
			action_llm=mock_llm,
		)

		assert result.error is None, result.error
		# Calls: round1 decision + finish lightweight + round2 decision = 3
		assert len(ainvoke_call_log) == 3
		assert ainvoke_call_log[0]['output_format'] is VisionClickLoopDecision
		assert ainvoke_call_log[1]['output_format'] is VisionFinishDecision
		assert ainvoke_call_log[2]['output_format'] is VisionClickLoopDecision
		assert result.metadata is not None
		assert result.metadata['stop_reason'] == 'ready_to_submit'

	async def test_vision_click_loop_round_two_uses_lighter_vision_config(self, browser_session, base_url, tools, monkeypatch):
		"""Round 1 uses high detail, while later rounds stay low-thinking and drop to auto detail."""
		await tools.navigate(url=f'{base_url}/vision-challenge', new_tab=False, browser_session=browser_session)
		await asyncio.sleep(0.5)

		observed_per_call: list[dict] = []
		decisions_iter = iter([
			{'status': 'click_more', 'clicks': [{'x': 180, 'y': 200}], 'reasoning': 'r1'},
			{'status': 'ready_to_submit', 'clicks': [], 'reasoning': 'r2'},
		])

		async def fake_ainvoke(self, messages, output_format=None, **kwargs):
			detail = None
			for msg in messages:
				content = getattr(msg, 'content', None)
				if isinstance(content, list):
					for part in content:
						if getattr(part, 'type', None) == 'image_url':
							detail = getattr(part.image_url, 'detail', None)
			observed_per_call.append({
				'thinking_level': getattr(self, 'thinking_level', None),
				'thinking_budget': getattr(self, 'thinking_budget', None),
				'image_detail': detail,
			})
			payload = next(decisions_iter)
			return ChatInvokeCompletion(completion=output_format.model_validate(payload), usage=None)

		monkeypatch.setattr(ChatGoogle, 'ainvoke', fake_ainvoke)
		llm = ChatGoogle(model='gemini-3-flash-preview')

		result = await tools.vision_click_loop(
			instruction='click all matching tiles',
			browser_session=browser_session,
			action_llm=llm,
		)

		assert result.error is None, result.error
		assert len(observed_per_call) == 2
		assert observed_per_call[0]['thinking_level'] == 'medium'
		assert observed_per_call[0]['image_detail'] == 'high'
		assert observed_per_call[1]['thinking_level'] == 'medium'
		assert observed_per_call[1]['image_detail'] == 'auto'
