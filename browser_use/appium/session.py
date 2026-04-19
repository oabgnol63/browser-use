"""
Appium-backed mobile web session helpers.

This module keeps Appium support separate from the Selenium desktop/browser
integration while still reusing the SeleniumSession implementation as the
runtime backend. The resulting driver is standard W3C WebDriver, so the
existing SeleniumBrowserSession adapter can consume it directly.
"""

import asyncio
import logging
from typing import Any, Literal

from selenium import webdriver
from selenium.webdriver.common.options import ArgOptions

from browser_use.appium.action_service import AppiumActionService
from browser_use.selenium.session import SeleniumSession

APPIUM_PLATFORM_DEFAULTS = {
	'android': {
		'platform_name': 'Android',
		'browser_name': 'chrome',
		'automation_name': 'UiAutomator2',
	},
	'ios': {
		'platform_name': 'iOS',
		'browser_name': 'safari',
		'automation_name': 'XCUITest',
	},
}


class AppiumSession(SeleniumSession):
	"""SeleniumSession subclass with Appium mobile-web constructors."""

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		self.action_service = AppiumActionService(self.driver, logger=self.logger)

	@classmethod
	def build_mobile_web_capabilities(
		cls,
		*,
		platform: Literal['android', 'ios'],
		device_name: str | None = None,
		platform_version: str | None = None,
		browser_name: str | None = None,
		automation_name: str | None = None,
		capability_style: Literal['appium', 'sauce_compat'] = 'appium',
		new_command_timeout: int = 300,
		appium_capabilities: dict[str, Any] | None = None,
		vendor_options: dict[str, Any] | None = None,
		vendor_options_key: str = 'sauce:options',
	) -> dict[str, Any]:
		"""Build W3C capabilities for Appium mobile-web sessions."""
		platform_key = platform.lower()
		if platform_key not in APPIUM_PLATFORM_DEFAULTS:
			raise ValueError(f'Unsupported Appium platform: {platform}. Use "android" or "ios".')
		if capability_style not in {'appium', 'sauce_compat'}:
			raise ValueError(
				f'Unsupported capability style: {capability_style}. '
				'Use "appium" or "sauce_compat".'
			)

		defaults = APPIUM_PLATFORM_DEFAULTS[platform_key]
		platform_name = defaults['platform_name']
		if capability_style == 'sauce_compat' and platform_version:
			platform_name = f'{platform_name} {platform_version}'

		capabilities: dict[str, Any] = {
			'platformName': platform_name,
			'browserName': browser_name or defaults['browser_name'],
			'appium:automationName': automation_name or defaults['automation_name'],
			'appium:newCommandTimeout': new_command_timeout,
		}
		if str(capabilities['browserName']).lower() in {'chrome', 'edge'}:
			capabilities['webSocketUrl'] = True

		if device_name:
			capabilities['appium:deviceName'] = device_name

		if platform_version and capability_style == 'appium':
			capabilities['appium:platformVersion'] = platform_version

		if appium_capabilities:
			capabilities.update(appium_capabilities)

		if vendor_options:
			capabilities[vendor_options_key] = vendor_options

		return capabilities

	@classmethod
	async def new_mobile_web_session(
		cls,
		*,
		appium_server_url: str,
		platform: Literal['android', 'ios'],
		device_name: str | None = None,
		platform_version: str | None = None,
		browser_name: str | None = None,
		automation_name: str | None = None,
		capability_style: Literal['appium', 'sauce_compat'] = 'appium',
		new_command_timeout: int = 300,
		appium_capabilities: dict[str, Any] | None = None,
		vendor_options: dict[str, Any] | None = None,
		vendor_options_key: str = 'sauce:options',
		logger: logging.Logger | None = None,
		skip_processing_iframes: bool = False,
	) -> 'AppiumSession':
		"""
		Create a mobile-web session through an Appium-compatible server.

		The created driver still speaks the standard Selenium WebDriver
		interface, so it can plug into the existing Selenium-backed browser-use
		backend without any CDP dependency.
		"""
		_logger = logger or logging.getLogger(__name__)
		capabilities = cls.build_mobile_web_capabilities(
			platform=platform,
			device_name=device_name,
			platform_version=platform_version,
			browser_name=browser_name,
			automation_name=automation_name,
			capability_style=capability_style,
			new_command_timeout=new_command_timeout,
			appium_capabilities=appium_capabilities,
			vendor_options=vendor_options,
			vendor_options_key=vendor_options_key,
		)

		_logger.info(
			'Creating Appium mobile-web session for %s %s (%s)...',
			platform,
			browser_name or capabilities['browserName'],
			device_name or 'auto-device',
		)

		def create_driver():
			options = ArgOptions()
			for key, value in capabilities.items():
				options.set_capability(key, value)
			return webdriver.Remote(command_executor=appium_server_url, options=options)

		driver = await asyncio.get_event_loop().run_in_executor(None, create_driver)
		return cls(driver, logger=_logger, skip_processing_iframes=skip_processing_iframes)
