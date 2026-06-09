"""Tests for coordinate clicking feature.

This feature allows certain models (Claude Sonnet 4, Claude Opus 4, Gemini 3 Flash Preview, browser-use/* models)
to use coordinate-based clicking, while other models only get index-based clicking.
"""

import base64
import io
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest
from PIL import Image

from browser_use.agent.service import Agent
from browser_use.appium.action_service import AppiumActionService
from browser_use.browser.appium_session import AppiumBrowserSession
from browser_use.tools.registry.views import Mode
from browser_use.tools.service import Tools
from browser_use.tools.views import ClickElementAction, ClickElementActionIndexOnly
from tests.ci.conftest import create_mock_llm


class TestCoordinateClickingTools:
	"""Test the Tools class coordinate clicking functionality."""

	def test_default_coordinate_clicking_disabled(self):
		"""By default, coordinate clicking should be disabled."""
		tools = Tools()

		assert tools._coordinate_clicking_enabled is False

	def test_default_uses_index_only_action(self):
		"""Default Tools should use ClickElementActionIndexOnly."""
		tools = Tools()

		click_action = tools.registry.registry.actions.get('click')
		assert click_action is not None
		assert click_action.param_model == ClickElementActionIndexOnly

	def test_default_click_schema_has_only_index(self):
		"""Default click action schema should only have index property."""
		tools = Tools()

		click_action = tools.registry.registry.actions.get('click')
		assert click_action is not None
		schema = click_action.param_model.model_json_schema()

		assert 'index' in schema['properties']
		assert 'coordinate_x' not in schema['properties']
		assert 'coordinate_y' not in schema['properties']

	def test_enable_coordinate_clicking(self):
		"""Enabling coordinate clicking should switch to ClickElementAction."""
		tools = Tools()
		tools.set_coordinate_clicking(True)

		assert tools._coordinate_clicking_enabled is True

		click_action = tools.registry.registry.actions.get('click')
		assert click_action is not None
		assert click_action.param_model == ClickElementAction

	def test_enabled_click_schema_has_coordinates(self):
		"""Enabled click action schema should have index and coordinate properties."""
		tools = Tools()
		tools.set_coordinate_clicking(True)

		click_action = tools.registry.registry.actions.get('click')
		assert click_action is not None
		schema = click_action.param_model.model_json_schema()

		assert 'index' in schema['properties']
		assert 'coordinate_x' in schema['properties']
		assert 'coordinate_y' in schema['properties']

	def test_disable_coordinate_clicking(self):
		"""Disabling coordinate clicking should switch back to index-only."""
		tools = Tools()
		tools.set_coordinate_clicking(True)
		tools.set_coordinate_clicking(False)

		assert tools._coordinate_clicking_enabled is False

		click_action = tools.registry.registry.actions.get('click')
		assert click_action is not None
		assert click_action.param_model == ClickElementActionIndexOnly

	def test_set_coordinate_clicking_idempotent(self):
		"""Setting the same value twice should not cause issues."""
		tools = Tools()

		# Enable twice
		tools.set_coordinate_clicking(True)
		tools.set_coordinate_clicking(True)
		assert tools._coordinate_clicking_enabled is True

		# Disable twice
		tools.set_coordinate_clicking(False)
		tools.set_coordinate_clicking(False)
		assert tools._coordinate_clicking_enabled is False

	def test_schema_title_consistent(self):
		"""Schema title should be 'ClickElementAction' regardless of mode."""
		tools = Tools()

		# Check default (disabled)
		click_action = tools.registry.registry.actions.get('click')
		assert click_action is not None
		schema = click_action.param_model.model_json_schema()
		assert schema['title'] == 'ClickElementAction'

		# Check enabled
		tools.set_coordinate_clicking(True)
		click_action = tools.registry.registry.actions.get('click')
		assert click_action is not None
		schema = click_action.param_model.model_json_schema()
		assert schema['title'] == 'ClickElementAction'


class TestCoordinateClickingModelDetection:
	"""Test the model detection logic for coordinate clicking."""

	@pytest.mark.parametrize(
		'model_name,expected_coords',
		[
			# Models that SHOULD have coordinate clicking (claude-sonnet-4*, claude-opus-4*, gemini-3-flash-preview*, browser-use/*)
			('claude-sonnet-4-5', True),
			('claude-sonnet-4-5-20250101', True),
			('claude-sonnet-4-0', True),
			('claude-sonnet-4', True),
			('claude-opus-4-5', True),
			('claude-opus-4-5-latest', True),
			('claude-opus-4-0', True),
			('claude-opus-4', True),
			('gemini-3-flash-preview', True),
			('gemini-3-flash-preview-05-20', True),
			('browser-use/fast', True),
			('browser-use/accurate', True),
			('CLAUDE-SONNET-4-5', True),  # Case insensitive
			('CLAUDE-SONNET-4', True),  # Case insensitive
			('GEMINI-3-FLASH-PREVIEW', True),  # Case insensitive
			# Models that should NOT have coordinate clicking
			('claude-3-5-sonnet', False),
			('claude-sonnet-3-5', False),
			('gpt-4o', False),
			('gpt-4-turbo', False),
			('gemini-2.0-flash', False),
			('gemini-1.5-pro', False),
			('llama-3.1-70b', False),
			('mistral-large', False),
		],
	)
	def test_model_detection_patterns(self, model_name: str, expected_coords: bool):
		"""Test that the model detection patterns correctly identify coordinate-capable models."""
		model_lower = model_name.lower()
		supports_coords = any(
			pattern in model_lower
			for pattern in [
				'claude-sonnet-4',
				'claude-opus-4',
				'gemini-3-flash-preview',
				'browser-use/',
			]
		)
		assert supports_coords == expected_coords, f'Model {model_name}: expected {expected_coords}, got {supports_coords}'


class TestCoordinateClickingWithPassedTools:
	"""Test that coordinate clicking works correctly when Tools is passed to Agent."""

	def test_tools_can_be_modified_after_creation(self):
		"""Tools created externally can have coordinate clicking enabled."""
		tools = Tools()
		assert tools._coordinate_clicking_enabled is False

		# Simulate what Agent does for coordinate-capable models
		tools.set_coordinate_clicking(True)

		click_action = tools.registry.registry.actions.get('click')
		assert click_action is not None
		assert click_action.param_model == ClickElementAction


class TestAppiumCoordinateClickCompatibility:
	"""Appium coordinate click should honor the shared Selenium signature."""

	async def test_appium_type_text_prevents_partial_first_entry_via_character_typing(self):
		driver = MagicMock()
		driver.capabilities = {}
		element = MagicMock()
		state = {'value': ''}

		def click():
			return None

		def clear():
			state['value'] = ''

		def send_keys(text):
			if len(text) > 1:
				state['value'] = 'foot'
			else:
				state['value'] += text

		def get_attribute(name):
			assert name == 'value'
			return state['value']

		element.click.side_effect = click
		element.clear.side_effect = clear
		element.send_keys.side_effect = send_keys
		element.get_attribute.side_effect = get_attribute
		driver.switch_to.active_element = element

		service = AppiumActionService(driver)

		result = await service.type_text(element_node=None, text='football', clear_first=False)

		assert result == {
			'success': True,
			'text_length': len('football'),
			'actual_value': 'football',
		}
		assert [call.args[0] for call in element.send_keys.call_args_list] == list('football')
		assert state['value'] == 'football'

	async def test_appium_type_text_uses_framework_aware_clear_before_replacement(self):
		driver = MagicMock()
		driver.capabilities = {}
		element = MagicMock()
		state = {'value': 'foot'}

		def click():
			return None

		def clear():
			return None

		def send_keys(text):
			state['value'] += text

		def get_attribute(name):
			assert name == 'value'
			return state['value']

		def execute_script(script, passed_element, value):
			assert passed_element is element
			state['value'] = value
			return value

		element.click.side_effect = click
		element.clear.side_effect = clear
		element.send_keys.side_effect = send_keys
		element.get_attribute.side_effect = get_attribute
		driver.execute_script.side_effect = execute_script
		driver.switch_to.active_element = element

		service = AppiumActionService(driver)

		result = await service.type_text(element_node=None, text='foo', clear_first=True)

		assert result == {
			'success': True,
			'text_length': len('foo'),
			'actual_value': 'foo',
		}
		driver.execute_script.assert_called_once()
		assert [call.args[0] for call in element.send_keys.call_args_list] == list('foo')
		assert state['value'] == 'foo'

	async def test_appium_send_keys_plain_text_uses_same_active_element_typing_path(self):
		driver = MagicMock()
		driver.capabilities = {}
		element = MagicMock()
		state = {'value': ''}

		def click():
			return None

		def send_keys(text):
			state['value'] += text

		def get_attribute(name):
			assert name == 'value'
			return state['value']

		element.click.side_effect = click
		element.send_keys.side_effect = send_keys
		element.get_attribute.side_effect = get_attribute
		driver.switch_to.active_element = element

		service = AppiumActionService(driver)

		result = await service.send_keys('hello')

		assert result == {
			'success': True,
			'keys': 'hello',
			'actual_value': 'hello',
		}
		assert [call.args[0] for call in element.send_keys.call_args_list] == list('hello')
		assert state['value'] == 'hello'

	@pytest.mark.parametrize('human_like', [True, False])
	async def test_appium_click_coordinates_accepts_human_like(self, human_like: bool):
		driver = MagicMock()
		fake_builder = MagicMock()
		fake_pointer = MagicMock()
		fake_builder.pointer_action = fake_pointer
		fake_builder.perform = MagicMock()
		service = AppiumActionService(driver)

		with patch.object(service.logger, 'info') as info_log:
			with patch('browser_use.appium.action_service.ActionBuilder', return_value=fake_builder):
				result = await service.click_coordinates(120, 240, human_like=human_like)

		assert result == {
			'success': True,
			'x': 120,
			'y': 240,
			'method': 'w3c-touch-tap',
		}
		info_log.assert_called_once_with('Appium coordinate click used native touch tap at (120, 240)')
		fake_pointer.move_to_location.assert_called_once_with(120, 240)
		fake_pointer.pointer_down.assert_called_once()
		fake_pointer.pointer_up.assert_called_once()
		fake_builder.perform.assert_called_once()
		driver.execute_script.assert_not_called()

	async def test_appium_take_screenshot_returns_selenium_default_when_size_matches(self):
		"""Appium screenshot path should pass through the raw Selenium screenshot."""
		driver = MagicMock()
		from PIL import Image as _Img
		buf = io.BytesIO()
		_Img.new('RGB', (768, 1072), color='white').save(buf, format='PNG')
		raw_png = buf.getvalue()
		driver.get_screenshot_as_png.return_value = raw_png
		driver.capabilities = {}
		service = AppiumActionService(driver)

		result = await service.take_screenshot()

		assert result == raw_png
		driver.get_screenshot_as_png.assert_called_once()

	async def test_appium_coordinate_click_falls_back_to_js(self):
		driver = MagicMock()
		driver.execute_script.return_value = True
		service = AppiumActionService(driver)

		with patch.object(service.logger, 'info') as info_log:
			with patch('browser_use.appium.action_service.ActionBuilder', side_effect=RuntimeError('tap failed')):
				result = await service.click_coordinates(120, 240)

		assert result == {
			'success': True,
			'x': 120,
			'y': 240,
			'method': 'js-click',
		}
		info_log.assert_called_once_with('Appium coordinate click used JS elementFromPoint click at (120, 240)')
		driver.execute_script.assert_called_once()
		script, *_args = driver.execute_script.call_args.args
		assert 'document.elementFromPoint(120, 240)' in script

	async def test_appium_ios_enter_uses_newline_when_it_navigates(self):
		driver = MagicMock()
		driver.capabilities = {
			'platformName': 'iOS',
			'appium:automationName': 'XCUITest',
		}
		element = MagicMock()
		driver.switch_to.active_element = element
		service = AppiumActionService(driver)

		with patch.object(type(driver), 'current_url', new_callable=PropertyMock, create=True) as current_url:
			current_url.side_effect = [
				'https://safe.surfcrew.com/https://www.bbc.com/',
				'https://safe.surfcrew.com/https://www.bbc.com/search?q=Football',
			]
			result = await service.send_keys('Enter')

		assert result == {
			'success': True,
			'keys': 'Enter',
			'method': 'ios-newline-submit',
		}
		element.send_keys.assert_called_once_with('\n')
		driver.execute_script.assert_not_called()

	async def test_appium_ios_enter_falls_back_to_js_submit_when_newline_does_not_navigate(self):
		driver = MagicMock()
		driver.capabilities = {
			'platformName': 'iOS',
			'appium:automationName': 'XCUITest',
		}
		element = MagicMock()
		driver.switch_to.active_element = element
		driver.execute_script.return_value = {
			'method': 'ios-enter-search-click',
			'submitted': True,
			'isMultiline': False,
		}
		service = AppiumActionService(driver)

		with patch.object(type(driver), 'current_url', new_callable=PropertyMock, create=True) as current_url:
			current_url.side_effect = [
				'https://safe.surfcrew.com/https://www.bbc.com/',
				'https://safe.surfcrew.com/https://www.bbc.com/',
			]
			result = await service.send_keys('Enter')

		assert result == {
			'success': True,
			'keys': 'Enter',
			'method': 'ios-enter-search-click',
			'fallback': {
				'method': 'ios-enter-search-click',
				'submitted': True,
				'isMultiline': False,
			},
		}
		element.send_keys.assert_called_once_with('\n')
		driver.execute_script.assert_called_once()
		script, passed_element = driver.execute_script.call_args.args
		assert 'requestSubmit' in script
		assert 'bestCandidate.click()' in script
		assert passed_element is element

	async def test_appium_normalized_coordinates_map_screenshot_to_viewport(self):
		"""Screenshot space maps back into viewport space through the Appium session hook."""
		tools = Tools()
		tools.set_coordinate_clicking(True)
		click_action = tools.registry.registry.actions['click']

		driver = MagicMock()
		driver.capabilities = {}
		selenium_session = SimpleNamespace(action_service=SimpleNamespace(), driver=driver)
		browser_session = AppiumBrowserSession(
			selenium_session=selenium_session,
			is_local=False,
		)
		browser_session.llm_coordinate_system = 'normalized_1000'
		browser_session._original_viewport_size = (384, 536)
		browser_session._actual_screenshot_size = (768, 1072)
		object.__setattr__(browser_session, 'get_tabs', AsyncMock(return_value=[]))
		object.__setattr__(browser_session, 'highlight_coordinate_click', AsyncMock(return_value=None))

		captured_events: list[object] = []

		class _FakeEvent:
			def __init__(self, event):
				self._event = event

			def __await__(self):
				async def _done():
					return self
				return _done().__await__()

			async def event_result(self, **_kwargs):
				return {'success': True}

		def _dispatch(event):
			captured_events.append(event)
			return _FakeEvent(event)

		browser_session.event_bus.dispatch = _dispatch

		result = await click_action.function(
			params=ClickElementAction(coordinate_x=915, coordinate_y=750),
			browser_session=browser_session,
		)

		# llm normalized (915, 750) -> screenshot (703, 804) -> viewport scale ÷2 -> (351, 402)
		assert len(captured_events) == 1
		assert captured_events[0].coordinate_x == 351
		assert captured_events[0].coordinate_y == 402
		assert result.metadata == {'click_x': 351, 'click_y': 402}

	def test_appium_map_uses_uniform_scale_from_screenshot_to_viewport(self):
		driver = MagicMock()
		driver.capabilities = {}
		selenium_session = SimpleNamespace(action_service=SimpleNamespace(), driver=driver)
		browser_session = AppiumBrowserSession(
			selenium_session=selenium_session,
			is_local=False,
		)
		browser_session._original_viewport_size = (384, 536)
		browser_session._actual_screenshot_size = (768, 1072)

		assert browser_session.map_screenshot_coordinates_to_action_space(176, 948) == (88, 474)

	def test_appium_map_returns_identity_when_metadata_missing(self):
		driver = MagicMock()
		driver.capabilities = {}
		selenium_session = SimpleNamespace(action_service=SimpleNamespace(), driver=driver)
		browser_session = AppiumBrowserSession(
			selenium_session=selenium_session,
			is_local=False,
		)
		browser_session._original_viewport_size = None
		browser_session._actual_screenshot_size = None

		assert browser_session.map_screenshot_coordinates_to_action_space(176, 948) == (176, 948)


class TestCoordinateClickingAgentMode:
	async def test_dom_mode_keeps_dom_enabled_while_enabling_coordinate_tools(self, browser_session):
		llm = create_mock_llm()
		llm.model = 'gemini-3-flash-preview'

		agent = Agent(
			task='Test task',
			llm=llm,
			browser_session=browser_session,
			override_system_message='Test system prompt',
		)
		get_browser_state_summary = AsyncMock(
			return_value=SimpleNamespace(url='https://example.com', screenshot=None, dom_state=None)
		)
		object.__setattr__(agent.browser_session, 'get_browser_state_summary', get_browser_state_summary)
		agent._check_and_update_downloads = AsyncMock()
		agent._log_step_context = lambda *_args, **_kwargs: None
		agent._check_stop_or_pause = AsyncMock()
		agent._update_action_models_for_page = AsyncMock()
		agent._maybe_compact_messages = AsyncMock()
		agent._message_manager.prepare_step_state = lambda **_kwargs: None
		agent._message_manager.create_state_messages = lambda **_kwargs: None

		await agent._prepare_context()

		assert agent.tools.registry.active_mode == Mode.DOM
		assert agent.tools._coordinate_clicking_enabled is True
		assert agent.browser_session._use_native_computer_use is False
		assert get_browser_state_summary.await_args.kwargs['include_dom'] is True

	async def test_native_computer_use_switches_to_vision_mode(self, browser_session):
		llm = create_mock_llm()
		llm.model = 'gemini-3-flash-preview'

		agent = Agent(
			task='Test task',
			llm=llm,
			browser_session=browser_session,
			use_native_computer_use=True,
			override_system_message='Test system prompt',
		)

		assert agent.tools.registry.active_mode == Mode.VISION
		assert agent.browser_session._use_native_computer_use is True

	def test_tools_state_preserved_after_modification(self):
		"""Verify that other tool state is preserved when toggling coordinate clicking."""
		tools = Tools(exclude_actions=['search'])

		# Search should be excluded
		assert 'search' not in tools.registry.registry.actions

		# Enable coordinate clicking
		tools.set_coordinate_clicking(True)

		# Search should still be excluded
		assert 'search' not in tools.registry.registry.actions

		# Click should have coordinates
		click_action = tools.registry.registry.actions.get('click')
		assert click_action is not None
		assert click_action.param_model == ClickElementAction


class TestSeleniumScreenshotHighlighting:
	@staticmethod
	def _png_bytes(width: int = 200, height: int = 100) -> bytes:
		image = Image.new('RGB', (width, height), color='white')
		buffer = io.BytesIO()
		image.save(buffer, format='PNG')
		return buffer.getvalue()

	@pytest.mark.asyncio
	async def test_appium_get_state_renders_python_highlighted_screenshot(self):
		png_bytes = self._png_bytes()
		driver = MagicMock()
		driver.capabilities = {}
		driver.execute_script.return_value = {
			'scrollX': 0,
			'scrollY': 0,
			'viewportWidth': 100,
			'viewportHeight': 50,
			'pageWidth': 100,
			'pageHeight': 50,
		}
		selector_map = {7: SimpleNamespace(backend_node_id=123)}
		dom_state = SimpleNamespace(selector_map=selector_map)
		selenium_session = SimpleNamespace(
			action_service=SimpleNamespace(),
			driver=driver,
			dom_service=SimpleNamespace(clear_all_highlights=AsyncMock()),
			get_page_info=AsyncMock(
				return_value={
					'url': 'https://example.com',
					'title': 'Example',
					'viewport': {'width': 100, 'height': 50},
				}
			),
			take_screenshot=AsyncMock(return_value=png_bytes),
			get_dom_state=AsyncMock(return_value=(dom_state, selector_map)),
		)
		browser_session = AppiumBrowserSession(
			selenium_session=selenium_session,
			is_local=False,
		)

		with patch(
			'browser_use.browser.selenium_session.create_highlighted_screenshot',
			new=AsyncMock(return_value='highlighted-b64'),
		) as create_highlighted:
			state = await browser_session.get_state()

		assert state.screenshot == 'highlighted-b64'
		assert state.clean_screenshot == base64.b64encode(png_bytes).decode('utf-8')
		create_highlighted.assert_awaited_once()
		assert create_highlighted.await_args.args[:2] == (state.clean_screenshot, selector_map)
		assert create_highlighted.await_args.kwargs['device_pixel_ratio'] == 2.0
		assert create_highlighted.await_args.kwargs['label_mode'] == 'selector_index'
