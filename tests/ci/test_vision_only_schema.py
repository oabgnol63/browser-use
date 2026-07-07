"""Vision-only (`use_native_computer_use=True`) output schema variants."""

from pathlib import Path

import pytest

from browser_use.agent.message_manager.views import HistoryItem
from browser_use.agent.prompts import AgentMessagePrompt
from browser_use.agent.views import AgentHistoryList, AgentOutput
from browser_use.browser.views import BrowserStateSummary, TabInfo
from browser_use.dom.views import SerializedDOMState
from browser_use.filesystem.file_system import FileSystem
from browser_use.tools.service import Tools
from browser_use.tools.views import ClickElementAction


def test_vision_only_thinking_schema_required_fields():
	tools = Tools()
	ActionModel = tools.registry.create_action_model()
	VisionOnly = AgentOutput.type_with_custom_actions_vision_only(ActionModel)

	schema = VisionOnly.model_json_schema()
	assert schema['required'] == ['screen_assessment', 'visual_state', 'memory', 'next_goal', 'cache_intention', 'action']

	# Dropped fields
	for dropped in ('thinking', 'evaluation_previous_goal', 'current_plan_item', 'plan_update', 'plan'):
		assert dropped not in schema['properties'], f'{dropped} should be dropped from vision-only schema'

	# Required fields are constructible
	output = VisionOnly(
		screen_assessment='on_target',
		visual_state='Current screenshot shows the login form and no blocking popup.',
		memory='captcha solved',
		next_goal='click the login button at ~500,620',
		cache_intention='Click the visible login button.',
		action=[{'wait': {'seconds': 1}}],
	)
	assert output.screen_assessment == 'on_target'
	assert output.visual_state == 'Current screenshot shows the login form and no blocking popup.'
	assert output.memory == 'captcha solved'
	assert output.next_goal == 'click the login button at ~500,620'
	assert output.cache_intention == 'Click the visible login button.'
	assert output.current_state.visual_state == 'Current screenshot shows the login form and no blocking popup.'
	assert output.current_state.screen_assessment == 'on_target'
	assert output.current_state.next_goal == 'click the login button at ~500,620'


def test_vision_only_flash_schema_required_fields():
	"""Flash mode shares the same compact schema regardless of vision-only or DOM."""
	tools = Tools()
	ActionModel = tools.registry.create_action_model()
	FlashOutput = AgentOutput.type_with_custom_actions_flash_mode(ActionModel)

	schema = FlashOutput.model_json_schema()
	assert schema['required'] == ['memory', 'action']

	for dropped in ('thinking', 'evaluation_previous_goal', 'next_goal', 'current_plan_item', 'plan_update', 'plan'):
		assert dropped not in schema['properties'], f'{dropped} should be dropped from flash schema'

	output = FlashOutput(memory='form filled', action=[{'wait': {'seconds': 1}}])
	assert output.memory == 'form filled'


def test_vision_only_schema_field_descriptions_enforce_brevity():
	tools = Tools()
	ActionModel = tools.registry.create_action_model()
	VisionOnly = AgentOutput.type_with_custom_actions_vision_only(ActionModel)

	schema = VisionOnly.model_json_schema()
	memory_desc = schema['properties']['memory'].get('description', '')
	next_goal_desc = schema['properties']['next_goal'].get('description', '')
	cache_intention_desc = schema['properties']['cache_intention'].get('description', '')
	visual_state_desc = schema['properties']['visual_state'].get('description', '')
	assessment_desc = schema['properties']['screen_assessment'].get('description', '')

	assert '120 characters' in memory_desc
	assert '120 characters' in next_goal_desc
	assert 'durable' in cache_intention_desc.lower()
	assert 'specific title' in cache_intention_desc.lower()
	assert '160 characters' in cache_intention_desc
	assert 'current screenshot' in visual_state_desc.lower()
	assert 'on_target' in assessment_desc
	assert 'wrong_destination' in assessment_desc


def test_vision_only_history_preserves_visual_state():
	item = HistoryItem(
		step_number=2,
		screen_assessment='wrong_destination',
		visual_state='Current screenshot shows an article page with a visible headline.',
		memory='Clicked first article.',
		next_goal='verify title keyword',
		action_results='Action Results: checked title keyword.',
	)

	text = item.to_string()

	assert 'Screen Assessment: wrong_destination' in text
	assert 'Visual State: Current screenshot shows an article page with a visible headline.' in text
	assert 'Clicked first article.' in text
	assert 'verify title keyword' in text


def test_vision_only_latest_screenshot_is_labeled_current(tmp_path):
	browser_state = BrowserStateSummary(
		url='https://example.com/article',
		title='Article',
		tabs=[TabInfo(target_id='tab-1', url='https://example.com/article', title='Article')],
		screenshot='current_screenshot',
		dom_state=SerializedDOMState(_root=None, selector_map={}),
	)
	prompt = AgentMessagePrompt(
		browser_state_summary=browser_state,
		file_system=FileSystem(tmp_path, create_default_files=False),
		screenshots=['older_screenshot', 'current_screenshot'],
		use_native_computer_use=True,
	)

	message = prompt.get_user_message(use_vision=True)
	text_parts = [part.text for part in message.content if getattr(part, 'type', 'text') == 'text']

	assert 'Current screenshot:' in text_parts
	assert 'Previous screenshot:' not in text_parts


def test_vision_only_prompt_has_decision_gate():
	prompt = (Path(__file__).parents[2] / 'browser_use' / 'agent' / 'system_prompts' / 'system_prompt_no_dom.md').read_text()

	assert 'screen_assessment' in prompt
	assert 'wrong_destination' in prompt
	assert 'Only scroll when' in prompt
	assert 'subscription gate' in prompt


def test_no_dom_prompt_requests_click_target_description():
	prompt = (Path(__file__).parents[2] / 'browser_use' / 'agent' / 'system_prompts' / 'system_prompt_no_dom.md').read_text()

	assert 'target_description' in prompt
	assert 'concise visual description' in prompt


def test_no_dom_prompt_has_cache_region_and_cache_intention_guidance():
	prompt = (Path(__file__).parents[2] / 'browser_use' / 'agent' / 'system_prompts' / 'system_prompt_no_dom.md').read_text()

	assert 'cache_region' in prompt
	assert 'cache_intention' in prompt
	assert 'Do not use a tiny box around only the click point' in prompt
	assert 'whole modal/banner/prompt panel' in prompt
	assert 'image plus the title/text block' in prompt


def test_no_dom_prompt_requires_modal_container_cache_region():
	prompt = (Path(__file__).parents[2] / 'browser_use' / 'agent' / 'system_prompts' / 'system_prompt_no_dom.md').read_text()

	assert 'If a button sits inside a visible modal' in prompt
	assert 'do not return the button rectangle as `cache_region`' in prompt
	assert 'exclude dimmed page content outside the modal' in prompt


def test_click_cache_region_schema_describes_container_coordinates():
	schema = ClickElementAction.model_json_schema()
	cache_region = schema['properties']['cache_region']

	assert 'modal' in cache_region['description']
	assert 'container' in cache_region['description']
	assert 'not a tight box around the button' in cache_region['description']


def test_vision_only_fields_normalization(mock_llm, monkeypatch):
	from browser_use import Agent

	monkeypatch.setenv('BROWSER_USE_DEV_ENV', '1')
	agent = Agent(task="dummy", llm=mock_llm)
	agent.settings.use_native_computer_use = True

	tools = Tools()
	ActionModel = tools.registry.create_action_model()
	VisionOnly = AgentOutput.type_with_custom_actions_vision_only(ActionModel)

	output = VisionOnly(
		screen_assessment='on_target',
		visual_state='A' * 300,
		memory='B' * 200,
		next_goal='C' * 150,
		cache_intention='D' * 220,
		action=[{'wait': {'seconds': 1}}],
	)

	agent._normalize_vision_only_fields(output)

	assert len(output.memory) == 120
	assert output.memory.endswith('...')
	assert len(output.next_goal) == 120
	assert output.next_goal.endswith('...')
	assert len(output.cache_intention) == 160
	assert output.cache_intention.endswith('...')
	assert len(output.visual_state) == 250
	assert output.visual_state.endswith('...')
