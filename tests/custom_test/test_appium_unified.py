"""
Verification test for unified Agent with AppiumSession via SeleniumBrowserSession.

Appium's ``execute_cdp_cmd(...)`` transport can send one-off CDP commands, but it does
not provide the full async CDP event stream that BrowserSession's watchdog stack expects
(target attach/detach, lifecycle events, screenshot/page event monitoring). For mobile
web we therefore run Appium through the Selenium-compatible backend that already exists
in this repo instead of trying to emulate a full CDP connection.
"""

import asyncio
import os

from dotenv import load_dotenv

os.environ['BROWSER_USE_LOGGING_LEVEL'] = 'debug'
os.environ['BROWSER_USE_CLOUD_SYNC'] = 'false'
os.environ['TIMEOUT_NavigateToUrlEvent'] = '90'
os.environ['TIMEOUT_GoBackEvent'] = '30'
os.environ['TIMEOUT_GoForwardEvent'] = '30'
os.environ['TIMEOUT_ScreenshotEvent'] = '120'
os.environ['TIMEOUT_BrowserStateRequestEvent'] = '180'
os.environ['BROWSER_USE_PRINT_LLM_MESSAGES'] = 'true'
load_dotenv()

from browser_use import Agent, ChatOpenAI
from browser_use.appium import AppiumSession
from browser_use.browser.appium_session import AppiumBrowserSession


async def main():
    print('Creating Sauce Labs Appium session (Android Chrome)...')

    username = os.environ.get('SAUCE_USERNAME') or os.environ.get('SAUCELABS_USERNAME')
    access_key = os.environ.get('SAUCE_ACCESS_KEY') or os.environ.get('SAUCELABS_PRIVATEKEY')
    if not username or not access_key:
        raise ValueError(
            'Sauce Labs credentials not found. Set SAUCE_USERNAME/SAUCE_ACCESS_KEY '
            'or SAUCELABS_USERNAME/SAUCELABS_PRIVATEKEY environment variables.'
        )

    appium_server_url = os.environ.get(
        'SAUCE_APPIUM_SERVER_URL',
        f'https://{username}:{access_key}@ondemand.us-west-1.saucelabs.com:443/wd/hub',
    )
    device_name = (
        os.environ.get('SAUCE_ANDROID_DEVICE')
        or os.environ.get('SAUCE_DEVICE_NAME')
        or 'Android GoogleAPI Emulator'
    )
    platform_version = (
        os.environ.get('SAUCE_ANDROID_VERSION')
        or os.environ.get('SAUCE_PLATFORM_VERSION')
        or '15.0'
    )
    capability_style = os.environ.get('SAUCE_APPIUM_CAPABILITY_STYLE', 'appium')
    appium_version = os.environ.get('SAUCE_APPIUM_VERSION')

    appium_capabilities = {
        'acceptInsecureCerts': True,
        'pageLoadStrategy': 'normal',
        'noSign:noSign': True,
        'goog:chromeOptions': {
            'w3c': True,
            'args': [
                '--ssl-version-max=tls1.2',
                '--disable-fre',
                '--disable-popup-blocking',
                '--enable-automation',
                '--ignore-certificate-errors',
                '--metrics-recording-only',
                '--no-first-run',
                '--disable-startup-promos-for-testing',
                '--ignore-certificate-errors-spki-list=CaajU/RXdG9fbq7r4O5DlED2+GE6xuJh1So/49rGML0=',
            ],
            'extensions': [],
        },
    }
    vendor_options = {'name': 'browser-use-appium-selenium-backend'}
    if appium_version:
        vendor_options['appiumVersion'] = appium_version

    appium_session = await AppiumSession.new_mobile_web_session(
        appium_server_url=appium_server_url,
        platform='android',
        device_name=device_name,
        platform_version=platform_version,
        capability_style=capability_style,
        appium_capabilities=appium_capabilities,
        vendor_options=vendor_options,
    )

    browser_session = AppiumBrowserSession(selenium_session=appium_session, is_local=False)
    agent = None
    try:
        print(f'Returned capabilities: {dict(appium_session.driver.capabilities or {})}')

        print('Starting browser session...')
        await browser_session.start()
        print('Browser session started.')

        llm = ChatOpenAI(
            model=os.environ.get('BROWSER_USE_TEST_MODEL', 'gemini-3-flash-preview'),
            base_url=os.environ.get('BROWSER_USE_TEST_BASE_URL', 'http://localhost:8844/v1'),
            api_key=os.environ.get('BROWSER_USE_TEST_API_KEY', 'your-api-key-1'),
            temperature=0.0,
            add_schema_to_system_prompt=True,
            dont_force_structured_output=True,
            remove_min_items_from_schema=True,
            remove_defaults_from_schema=True,
        )

        task = """
Open https://m.imdb.com.
If a consent or region popup appears, dismiss it.
Find a horizontal carousel of movies or news items.
Use the "swipe_coordinate" action (from right to left) to swipe horizontally through the carousel to see more items.
Confirm you were able to swipe and see new items.
""".strip()

        agent = Agent(task=task, llm=llm, browser_session=browser_session)
        print('Running agent...')
        result = await agent.run()
        print(f'Agent result: {result}')
    finally:
        if agent is not None:
            try:
                await agent.close()
            except Exception:
                pass
        try:
            await browser_session.stop()
        except Exception:
            pass
        await appium_session.close()
        print('Done.')


if __name__ == '__main__':
    asyncio.run(main())
