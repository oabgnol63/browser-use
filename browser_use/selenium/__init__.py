"""
Selenium-based browser backend for Firefox and Safari support.

This module provides an isolated implementation using Selenium WebDriver
to control Firefox/Safari browsers, with SauceLabs integration for cloud testing.
"""

from browser_use.selenium.session import SeleniumSession
from browser_use.selenium.dom_service import SeleniumDomService
from browser_use.selenium.action_service import SeleniumActionService

__all__ = [
    'SeleniumSession',
    'SeleniumDomService',
    'SeleniumActionService',
]
