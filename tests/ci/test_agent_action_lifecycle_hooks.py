from types import SimpleNamespace
from unittest.mock import AsyncMock

from browser_use import Agent
from browser_use.agent.views import ActionResult
from tests.ci.conftest import create_mock_llm


class _BrowserSessionStub:
	_cached_browser_state_summary = None
	agent_focus_target_id = 'target-1'
	id = 'browser-session-test'

	def __init__(self) -> None:
		self.browser_profile = SimpleNamespace(wait_between_actions=0)
		self.get_current_page_url = AsyncMock(return_value='https://example.com/')


class _RecordingAgent(Agent):
	def __init__(self) -> None:
		super().__init__(task='Test action lifecycle hooks', llm=create_mock_llm(actions=None), directly_open_url=False)
		self.before_actions: list[tuple[str, int, int]] = []
		self.after_actions: list[tuple[str, int, int, ActionResult, object]] = []

	async def _before_action_execution(self, action, action_name: str, action_index: int, total_actions: int) -> object:
		self.before_actions.append((action_name, action_index, total_actions))
		return {'action_name': action_name, 'action_index': action_index}

	async def _after_action_execution(
		self,
		action,
		action_name: str,
		action_index: int,
		total_actions: int,
		result: ActionResult,
		context: object,
	) -> None:
		self.after_actions.append((action_name, action_index, total_actions, result, context))


def _wait_actions(agent: Agent, count: int):
	return [agent.ActionModel.model_validate({'wait': {'seconds': 1}}) for _ in range(count)]


async def test_action_lifecycle_hooks_run_for_each_executed_action() -> None:
	agent = _RecordingAgent()
	agent.browser_session = _BrowserSessionStub()  # type: ignore[assignment]
	agent.tools.act = AsyncMock(
		side_effect=[
			ActionResult(extracted_content='first'),
			ActionResult(extracted_content='second'),
		]
	)

	results = await agent.multi_act(_wait_actions(agent, 2))

	assert [result.extracted_content for result in results] == ['first', 'second']
	assert agent.before_actions == [('wait', 0, 2), ('wait', 1, 2)]
	assert [(name, index, total) for name, index, total, _, _ in agent.after_actions] == [
		('wait', 0, 2),
		('wait', 1, 2),
	]
	assert agent.after_actions[0][4] == {'action_name': 'wait', 'action_index': 0}


async def test_action_lifecycle_hooks_skip_actions_after_early_stop() -> None:
	agent = _RecordingAgent()
	agent.browser_session = _BrowserSessionStub()  # type: ignore[assignment]
	agent.tools.act = AsyncMock(return_value=ActionResult(error='stop the sequence'))

	results = await agent.multi_act(_wait_actions(agent, 2))

	assert len(results) == 1
	assert results[0].error == 'stop the sequence'
	assert agent.before_actions == [('wait', 0, 2)]
	assert len(agent.after_actions) == 1
	assert agent.after_actions[0][0:3] == ('wait', 0, 2)
	assert agent.tools.act.await_count == 1
