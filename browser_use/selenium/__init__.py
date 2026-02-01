"""
Selenium-based browser backend for Firefox and Safari support.

This module provides an isolated implementation using Selenium WebDriver
to control Firefox/Safari browsers, with SauceLabs integration for cloud testing.

Enhanced iframe support:
- Same-origin iframes: Full DOM extraction and element interaction
- Cross-origin iframes: Coordinate-based interaction and metadata
- Automatic iframe context management
"""

from browser_use.selenium.session import SeleniumSession
from browser_use.selenium.dom_service import SeleniumDomService
from browser_use.selenium.action_service import SeleniumActionService
from browser_use.selenium.iframe_handler import SeleniumIframeHandler, IframeInfo, FrameContext
from browser_use.selenium.firefox_profile import (
    FIREFOX_DEFAULT_PREFS,
    FIREFOX_STEALTH_PREFS,
    FIREFOX_DISABLE_SECURITY_PREFS,
    FIREFOX_DETERMINISTIC_RENDERING_PREFS,
    FIREFOX_HEADLESS_ARGS,
    FIREFOX_DOCKER_ARGS,
    FIREFOX_DISABLE_SECURITY_ARGS,
    get_firefox_preferences,
    apply_firefox_preferences,
)

__all__ = [
    'SeleniumSession',
    'SeleniumDomService',
    'SeleniumActionService',
    # Iframe support
    'SeleniumIframeHandler',
    'IframeInfo',
    'FrameContext',
    # Firefox configuration
    'FIREFOX_DEFAULT_PREFS',
    'FIREFOX_STEALTH_PREFS',
    'FIREFOX_DISABLE_SECURITY_PREFS',
    'FIREFOX_DETERMINISTIC_RENDERING_PREFS',
    'FIREFOX_HEADLESS_ARGS',
    'FIREFOX_DOCKER_ARGS',
    'FIREFOX_DISABLE_SECURITY_ARGS',
    'get_firefox_preferences',
    'apply_firefox_preferences',
]
