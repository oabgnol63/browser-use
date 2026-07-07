from __future__ import annotations

from browser_use.selenium.action_service import SeleniumActionService


class _Driver:
	def __init__(self) -> None:
		self.scripts: list[str] = []

	def execute_script(self, script: str):
		self.scripts.append(script)
		return True


async def test_selenium_scroll_up_uses_negative_window_delta():
	driver = _Driver()
	service = SeleniumActionService(driver)  # type: ignore[arg-type]

	await service.scroll(direction='up', amount=50)

	assert driver.scripts
	assert all('window.scrollBy(0, -' in script for script in driver.scripts)


async def test_selenium_scroll_down_uses_positive_window_delta():
	driver = _Driver()
	service = SeleniumActionService(driver)  # type: ignore[arg-type]

	await service.scroll(direction='down', amount=50)

	assert driver.scripts
	assert all('window.scrollBy(0, -' not in script for script in driver.scripts)
