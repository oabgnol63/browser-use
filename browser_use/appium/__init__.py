"""
Appium-based mobile web backend.

This package contains Appium-specific session helpers that build on the
existing Selenium-compatible browser backend.
"""

from browser_use.appium.action_service import AppiumActionService
from browser_use.appium.session import APPIUM_PLATFORM_DEFAULTS, AppiumSession

__all__ = [
	'APPIUM_PLATFORM_DEFAULTS',
	'AppiumActionService',
	'AppiumSession',
]
