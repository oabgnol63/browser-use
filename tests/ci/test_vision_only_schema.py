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


def test_vision_only_thinking_schema_required_fields():
	tools = Tools()
	ActionModel = tools.registry.create_action_model()
	VisionOnly = AgentOutput.type_with_custom_actions_vision_only(ActionModel)

	schema = VisionOnly.model_json_schema()
	assert schema['required'] == ['screen_assessment', 'visual_state', 'memory', 'next_goal', 'action']

	# Dropped fields
	for dropped in ('thinking', 'evaluation_previous_goal', 'current_plan_item', 'plan_update', 'plan'):
		assert dropped not in schema['properties'], f'{dropped} should be dropped from vision-only schema'

	# Required fields are constructible
	output = VisionOnly(
		screen_assessment='on_target',
		visual_state='Current screenshot shows the login form and no blocking popup.',
		memory='captcha solved',
		next_goal='click the login button at ~500,620',
		action=[{'wait': {'seconds': 1}}],
	)
	assert output.screen_assessment == 'on_target'
	assert output.visual_state == 'Current screenshot shows the login form and no blocking popup.'
	assert output.memory == 'captcha solved'
	assert output.next_goal == 'click the login button at ~500,620'
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
	visual_state_desc = schema['properties']['visual_state'].get('description', '')
	assessment_desc = schema['properties']['screen_assessment'].get('description', '')

	assert '120 characters' in memory_desc
	assert '120 characters' in next_goal_desc
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


def test_vision_only_fields_normalization(mock_llm):
	from browser_use import Agent
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
		action=[{'wait': {'seconds': 1}}],
	)

	agent._normalize_vision_only_fields(output)

	assert len(output.memory) == 120
	assert output.memory.endswith('...')
	assert len(output.next_goal) == 120
	assert output.next_goal.endswith('...')
	assert len(output.visual_state) == 250
	assert output.visual_state.endswith('...')

