"""
SauceLabs integration utilities for Selenium-based browser sessions.

Provides helpers for creating and connecting to SauceLabs browser sessions
with Firefox and Safari.
"""

import logging
import os
import tempfile
import requests
import base64
import urllib.request
from typing import Literal, Union
from selenium.webdriver.firefox.firefox_profile import FirefoxProfile
from selenium import webdriver
from selenium.webdriver.remote.webdriver import WebDriver



logger = logging.getLogger(__name__)

# SauceLabs endpoints
SAUCELABS_HUB_URL = "https://ondemand.{region}.saucelabs.com:443/wd/hub"
SAUCELABS_REGIONS = {
    'us-west': 'us-west-1',
    'eu-central': 'eu-central-1',
    'apac-southeast': 'apac-southeast-1',
}

# Default Firefox extensions for automation
DEFAULT_FIREFOX_EXTENSIONS = [
    {
        'name': 'Noptcha: hCaptcha Solver',
        'id': '{2f67aecb-5dac-4f76-9378-0ac4f2bedc9c}',
        'url': 'https://addons.mozilla.org/firefox/downloads/latest/noptcha/latest.xpi',
    }
]


def _download_firefox_extension(url: str, name: str) -> str | None:
    """Download a Firefox extension to a temporary file and return the path."""
    try:
        # Use a consistent cache directory to avoid re-downloading
        cache_dir = os.path.join(tempfile.gettempdir(), 'browser-use-extensions')
        os.makedirs(cache_dir, exist_ok=True)
        
        # Use simple hash of name for filename
        filename = f"{name.lower().replace(' ', '_').replace(':', '')}.xpi"
        output_path = os.path.join(cache_dir, filename)
        
        if not os.path.exists(output_path):
            logger.info(f"Downloading extension: {name} from {url}...")
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req) as response:
                with open(output_path, 'wb') as f:
                    f.write(response.read())
            logger.info(f"Successfully downloaded extension {name} to {output_path}")
        else:
            logger.info(f"Using cached extension: {name} ({output_path})")
        return output_path
    except Exception as e:
        logger.error(f"Failed to download extension {name}: {e}")
        return None


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
    extension_path: Union[str, list[str], None] = None,
    firefox_preferences: dict | None = None,
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
        extension_path: Path(s) to Firefox extension(s) to install
        firefox_preferences: Additional Firefox preferences to apply

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
    
    # Normalize extension_path to a list
    extension_paths = []
    if extension_path:
        if isinstance(extension_path, list):
            extension_paths.extend(extension_path)
        else:
            extension_paths.append(extension_path)

    if browser == 'firefox':
        options = webdriver.FirefoxOptions()
        options.browser_version = browser_version
        options.platform_name = platform
        options.set_capability('sauce:options', sauce_options)

        # Add default extensions
        for ext_info in DEFAULT_FIREFOX_EXTENSIONS:
            path = _download_firefox_extension(ext_info['url'], ext_info['name'])
            if path:
                extension_paths.append(path)

        # Hide "Browser is remote controlled" UI
        profile = FirefoxProfile()
        profile.set_preference("toolkit.legacyUserProfileCustomizations.stylesheets", True)
        chrome_dir = os.path.join(profile.path, "chrome")
        os.makedirs(chrome_dir, exist_ok=True)
        with open(os.path.join(chrome_dir, "userChrome.css"), "w") as f:
            f.write("#remote-control-box { display: none !important; }\\n")
            f.write("#urlbar-background { background-image: none !important; box-shadow: none !important; }")
        options.profile = profile
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
    
    if browser == 'firefox' and extension_paths:
        # webdriver.Remote does not have driver.install_addon(), so we manually register the command
        logger.info(f"🚀 [FIREFOX EXTENSION SETUP] Attempting to install {len(extension_paths)} extensions: {extension_paths}")
        
        for path in extension_paths:
            try:
                if not os.path.exists(path):
                    logger.error(f"Extension file not found: {path}")
                    continue
                    
                with open(path, "rb") as f:
                    addon_content = f.read()
                
                orig_size = len(addon_content)
                
                logger.info(f"Installing {os.path.basename(path)} (Size: {orig_size} bytes)...")
                addon_b64 = base64.b64encode(addon_content).decode("utf-8")
                
                driver.command_executor._commands["INSTALL_ADDON"] = ("POST", "/session/$sessionId/moz/addon/install")
                res = driver.execute("INSTALL_ADDON", {"addon": addon_b64, "temporary": True})
                
                logger.info(f"Raw INSTALL_ADDON response for {os.path.basename(path)}: {res}")
                addon_id = res.get("value", "unknown")
                if addon_id and addon_id != "unknown":
                    logger.info(f"Successfully installed Firefox addon: {addon_id}")
                else:
                    logger.error(f"Failed to install Firefox addon: {os.path.basename(path)}. Response: {res}")
            except Exception as e:
                logger.exception(f"CRITICAL: Failed to install Firefox extension {path} to SauceLabs")

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
