"""
SauceLabs integration utilities for Selenium-based browser sessions.

Provides helpers for creating and connecting to SauceLabs browser sessions
with Firefox and Safari.
"""

import logging
import os
from typing import Literal

from selenium import webdriver
from selenium.webdriver.remote.webdriver import WebDriver

from browser_use.selenium.firefox_profile import apply_firefox_preferences

logger = logging.getLogger(__name__)

# SauceLabs endpoints
SAUCELABS_HUB_URL = "https://ondemand.{region}.saucelabs.com:443/wd/hub"
SAUCELABS_REGIONS = {
    'us-west': 'us-west-1',
    'eu-central': 'eu-central-1',
    'apac-southeast': 'apac-southeast-1',
}


def get_saucelabs_credentials() -> tuple[str, str]:
    """
    Get SauceLabs credentials from environment variables.
    
    Returns:
        Tuple of (username, access_key)
        
    Raises:
        ValueError: If credentials are not set
    """
    username = os.environ.get('SAUCE_USERNAME')
    access_key = os.environ.get('SAUCE_ACCESS_KEY')
    
    if not username or not access_key:
        raise ValueError(
            'SauceLabs credentials not found. Set SAUCE_USERNAME and SAUCE_ACCESS_KEY environment variables.'
        )
    
    return username, access_key


def create_saucelabs_session(
    browser: Literal['firefox', 'safari'] = 'firefox',
    browser_version: str = 'latest',
    platform: str = 'Windows 10',
    test_name: str = 'browser-use-session',
    region: str = 'us-west',
    username: str | None = None,
    access_key: str | None = None,
    additional_capabilities: dict | None = None,
    stealth: bool = True,
) -> WebDriver:
    """
    Create a new SauceLabs browser session.
    
    Args:
        browser: Browser type ('firefox' or 'safari')
        browser_version: Browser version (e.g., 'latest', '120')
        platform: Operating system (e.g., 'Windows 10', 'macOS 13')
        test_name: Name for the SauceLabs session
        region: SauceLabs region ('us-west', 'eu-central', 'apac-southeast')
        username: SauceLabs username (defaults to SAUCE_USERNAME env var)
        access_key: SauceLabs access key (defaults to SAUCE_ACCESS_KEY env var)
        additional_capabilities: Additional W3C capabilities
        stealth: Apply stealth preferences to avoid CAPTCHA/detection (default: True)

    Returns:
        Selenium WebDriver connected to SauceLabs
    """
    if not username or not access_key:
        username, access_key = get_saucelabs_credentials()
    
    # Build hub URL
    region_code = SAUCELABS_REGIONS.get(region, 'us-west-1')
    hub_url = SAUCELABS_HUB_URL.format(region=region_code)
    
    # Build capabilities
    sauce_options = {
        'username': username,
        'accessKey': access_key,
        'name': test_name,
        'build': 'browser-use',
        'idleTimeout': 300,
        'maxDuration': 1800,
    }
    
    if browser == 'firefox':
        options = webdriver.FirefoxOptions()
        options.browser_version = browser_version
        options.platform_name = platform
        options.set_capability('sauce:options', sauce_options)

        # Apply preferences
        apply_firefox_preferences(
            options,
            include_default=True,
            include_stealth=stealth,
        )
    elif browser == 'safari':
        options = webdriver.SafariOptions()
        options.browser_version = browser_version
        options.platform_name = platform
        options.set_capability('sauce:options', sauce_options)
    else:
        raise ValueError(f'Unsupported browser: {browser}. Use "firefox" or "safari".')
    
    # Add any additional capabilities
    if additional_capabilities:
        for key, value in additional_capabilities.items():
            options.set_capability(key, value)
    
    logger.info(f'Creating SauceLabs {browser} session on {platform}...')
    
    driver = webdriver.Remote(
        command_executor=hub_url,
        options=options,
    )
    
    logger.info(f'SauceLabs session created: {driver.session_id}')
    return driver


def connect_to_saucelabs_session(
    session_id: str,
    region: str = 'us-west',
    username: str | None = None,
    access_key: str | None = None,
) -> WebDriver:
    """
    Connect to an existing SauceLabs session by session ID.
    
    This is useful for attaching to a browser session that was created elsewhere,
    allowing browser-use to control an already-running browser.
    
    Args:
        session_id: The SauceLabs session ID to connect to
        region: SauceLabs region where the session was created
        username: SauceLabs username (defaults to SAUCE_USERNAME env var)
        access_key: SauceLabs access key (defaults to SAUCE_ACCESS_KEY env var)
        
    Returns:
        Selenium WebDriver attached to the existing session
    """
    if not username or not access_key:
        username, access_key = get_saucelabs_credentials()
    
    # Build hub URL
    region_code = SAUCELABS_REGIONS.get(region, 'us-west-1')
    hub_url = SAUCELABS_HUB_URL.format(region=region_code)
    
    logger.info(f'Connecting to existing SauceLabs session: {session_id}')
    
    # Create a minimal Remote driver and override the session
    # This is a known technique for connecting to existing sessions
    options = webdriver.ChromeOptions()  # Minimal options, will be overridden
    
    driver = webdriver.Remote(
        command_executor=hub_url,
        options=options,
    )
    
    # Override the session ID to attach to existing session
    # Note: This is not officially supported but works in practice
    driver.close()  # Close the new session we just created
    driver.session_id = session_id
    
    logger.info(f'Connected to SauceLabs session: {session_id}')
    return driver


def get_session_status(
    session_id: str,
    region: str = 'us-west',
    username: str | None = None,
    access_key: str | None = None,
) -> dict:
    """
    Get the status of a SauceLabs session.
    
    Args:
        session_id: The SauceLabs session ID
        region: SauceLabs region
        username: SauceLabs username
        access_key: SauceLabs access key
        
    Returns:
        Dict with session status information
    """
    import requests
    
    if not username or not access_key:
        username, access_key = get_saucelabs_credentials()
    
    region_code = SAUCELABS_REGIONS.get(region, 'us-west-1')
    api_url = f'https://api.{region_code}.saucelabs.com/rest/v1/{username}/jobs/{session_id}'
    
    response = requests.get(api_url, auth=(username, access_key))
    response.raise_for_status()
    
    return response.json()


def update_session_status(
    session_id: str,
    passed: bool,
    region: str = 'us-west',
    username: str | None = None,
    access_key: str | None = None,
) -> dict:
    """
    Update the pass/fail status of a SauceLabs session.
    
    Args:
        session_id: The SauceLabs session ID
        passed: Whether the test passed
        region: SauceLabs region
        username: SauceLabs username
        access_key: SauceLabs access key
        
    Returns:
        Dict with updated session information
    """
    import requests
    
    if not username or not access_key:
        username, access_key = get_saucelabs_credentials()
    
    region_code = SAUCELABS_REGIONS.get(region, 'us-west-1')
    api_url = f'https://api.{region_code}.saucelabs.com/rest/v1/{username}/jobs/{session_id}'
    
    response = requests.put(
        api_url,
        auth=(username, access_key),
        json={'passed': passed},
    )
    response.raise_for_status()
    
    return response.json()
