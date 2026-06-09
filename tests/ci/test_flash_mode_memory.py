from browser_use.agent.service import Agent
from browser_use.agent.views import AgentOutput


class _DummyAgentOutput(AgentOutput):
	action: list = []


def test_flash_mode_memory_is_trimmed_to_short_hint():
	agent = object.__new__(Agent)
	agent.settings = type('S', (), {'flash_mode': True})()
	parsed = _DummyAgentOutput(
		memory='This is a deliberately long flash mode memory string that should be shortened into a compact carry forward hint instead of keeping the full narration.'
	)

	agent._normalize_flash_mode_memory(parsed)

	assert parsed.memory is not None
	assert len(parsed.memory) <= 123
	assert parsed.memory.endswith('...')


def test_non_flash_mode_memory_is_left_unchanged():
	agent = object.__new__(Agent)
	agent.settings = type('S', (), {'flash_mode': False})()
	parsed = _DummyAgentOutput(memory='Keep this memory unchanged.')

	agent._normalize_flash_mode_memory(parsed)

	assert parsed.memory == 'Keep this memory unchanged.'
