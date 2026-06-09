from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from browser_use.agent.service import Agent
from browser_use.agent.views import AgentStepInfo
from browser_use.browser.session import BrowserSession
from browser_use.browser.views import BrowserStateSummary, TabInfo
from tests.ci.conftest import create_mock_llm


def _browser_state(screenshot: str | None) -> BrowserStateSummary:
	dom_state = SimpleNamespace(selector_map={}, llm_representation=lambda include_attributes=None: '')
	return BrowserStateSummary(
		dom_state=dom_state,
		url='https://example.com',
		title='Example',
		tabs=[TabInfo(target_id='tab-1', url='https://example.com', title='Example')],
		screenshot=screenshot,
	)


def _prompt_templates() -> dict[str, str]:
	return {
		'system_prompt_no_dom.md': 'You are in vision-only mode.',
		'system_prompt.md': 'You are in DOM mode.',
		'system_prompt_no_thinking.md': 'No thinking.',
		'system_prompt_anthropic_flash.md': 'Anthropic flash.',
	}


@pytest.mark.asyncio
async def test_vision_only_missing_screenshot_skips_llm_call_and_records_failure():
	llm = create_mock_llm()
	browser_session = BrowserSession(headless=True)
	object.__setattr__(browser_session, 'session_manager', SimpleNamespace(ensure_valid_focus=AsyncMock(return_value=False)))

	with patch('browser_use.agent.prompts._get_prompt_templates', return_value=_prompt_templates()):
		agent = Agent(
			task='Click the search button',
			llm=llm,
			browser_session=browser_session,
			use_native_computer_use=True,
			final_response_after_failure=True,
		)
	agent._check_and_update_downloads = AsyncMock(return_value=None)  # type: ignore[method-assign]
	agent._update_action_models_for_page = AsyncMock(return_value=None)  # type: ignore[method-assign]
	agent._maybe_compact_messages = AsyncMock(return_value=None)  # type: ignore[method-assign]
	agent._inject_budget_warning = AsyncMock(return_value=None)  # type: ignore[method-assign]
	agent._force_done_after_last_step = AsyncMock(return_value=None)  # type: ignore[method-assign]
	agent._force_done_after_failure = AsyncMock(return_value=None)  # type: ignore[method-assign]
	agent._check_stop_or_pause = AsyncMock(return_value=None)  # type: ignore[method-assign]
	agent._demo_mode_log = AsyncMock(return_value=None)  # type: ignore[method-assign]
	agent._get_next_action = AsyncMock(side_effect=AssertionError('LLM should not be called without a screenshot'))  # type: ignore[method-assign]
	agent.save_file_system_state = lambda: None  # type: ignore[method-assign]

	with patch.object(BrowserSession, 'wait_if_captcha_solving', new=AsyncMock(return_value=None)):
		with patch.object(
			BrowserSession,
			'get_browser_state_summary',
			new=AsyncMock(side_effect=[_browser_state(None), _browser_state(None)]),
		) as get_browser_state_summary:
			await agent.step(AgentStepInfo(step_number=0, max_steps=5))

	assert agent._get_next_action.await_count == 0
	assert get_browser_state_summary.await_count == 2
	assert agent.state.last_result is not None
	assert 'requires a current screenshot' in (agent.state.last_result[0].error or '')


@pytest.mark.asyncio
async def test_vision_only_missing_screenshot_retry_can_recover():
	llm = create_mock_llm()
	browser_session = BrowserSession(headless=True)
	object.__setattr__(browser_session, 'session_manager', SimpleNamespace(ensure_valid_focus=AsyncMock(return_value=True)))

	with patch('browser_use.agent.prompts._get_prompt_templates', return_value=_prompt_templates()):
		agent = Agent(
			task='Click the search button',
			llm=llm,
			browser_session=browser_session,
			use_native_computer_use=True,
		)
	agent._check_and_update_downloads = AsyncMock(return_value=None)  # type: ignore[method-assign]
	agent._update_action_models_for_page = AsyncMock(return_value=None)  # type: ignore[method-assign]
	agent._maybe_compact_messages = AsyncMock(return_value=None)  # type: ignore[method-assign]
	agent._inject_budget_warning = AsyncMock(return_value=None)  # type: ignore[method-assign]
	agent._force_done_after_last_step = AsyncMock(return_value=None)  # type: ignore[method-assign]
	agent._force_done_after_failure = AsyncMock(return_value=None)  # type: ignore[method-assign]
	agent._check_stop_or_pause = AsyncMock(return_value=None)  # type: ignore[method-assign]

	with patch.object(BrowserSession, 'wait_if_captcha_solving', new=AsyncMock(return_value=None)):
		with patch.object(
			BrowserSession,
			'get_browser_state_summary',
			new=AsyncMock(side_effect=[_browser_state(None), _browser_state('abc123')]),
		) as get_browser_state_summary:
			browser_state = await agent._prepare_context(AgentStepInfo(step_number=0, max_steps=5))

	assert browser_state.screenshot == 'abc123'
	assert get_browser_state_summary.await_count == 2
	assert browser_session.session_manager.ensure_valid_focus.await_count == 1
