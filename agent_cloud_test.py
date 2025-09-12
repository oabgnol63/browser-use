import os
import sys
import asyncio
from dotenv import load_dotenv
load_dotenv()

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.environ['BROWSER_USE_LOGGING_LEVEL'] = 'debug'
os.environ['BROWSER_USE_CLOUD_SYNC'] = 'false'
os.environ['BROWSER_USE_SCREENSHOT_FILE'] = 'debug_screenshot.png'
os.environ['TIMEOUT_NavigationCompleteEvent'] = '60'
os.environ['TIMEOUT_ScreenshotEvent'] = '90'
os.environ['TIMEOUT_BrowserStateRequestEvent'] = '120'
SAFEVIEW_URL = os.getenv("SAFEVIEW_URL")
PROXY_URL = os.getenv("PROXY_URL")
PROXY_USERNAME = os.getenv("PROXY_USERNAME")
PROXY_PASSWORD = os.getenv("PROXY_PASSWORD")
GEMINI_API_KEY = os.getenv('GOOGLE_API_KEY')
GEMINI_API_KEY_2 = os.getenv('GOOGLE_API_KEY_2') if os.getenv('GOOGLE_API_KEY_2') else GEMINI_API_KEY

from browser_use.browser.profile import ViewportSize
from browser_use.browser import ProxySettings, CloudBrowserProfile
from browser_use import Agent, ChatGoogle
from sauce_manager import saucelabs_session_creation, close_saucelabs_session, _do_login_cdp_async

async def main():
    # Initialize cloud profile and create SauceLabs session only when running main
    cloud_profile = CloudBrowserProfile(
        # required
        browser_name='chrome',
        browser_version='latest',
        platform_name='Windows 10',
        session_name="CloudBrowserProfile Test",
        tags=['browser-use', 'cloudprofile', 'agent-test'],
        build_name='browser-use-cloudprofile',
        is_local=False,
        # optional
        # disable_security=True,  # don't set it as it will conflict with extensions loading
        minimum_wait_page_load_time=7,
        maximum_wait_page_load_time=10,
        wait_for_network_idle_page_load_time=1.5,
        default_navigation_timeout=30000,
        timeout=60000,
        cross_origin_iframes=True,
        skip_iframe_documents=False,  # experimental, should not use
        stealth=True,
        enable_default_extensions=True,
        viewport=ViewportSize(width=1440, height=900),
        proxy=ProxySettings(
            server=PROXY_URL,
            username=PROXY_USERNAME,
            password=PROXY_PASSWORD
        ),
    )

    cdp_url = saucelabs_session_creation(cloud_profile)

    if not cdp_url:
        return
    cloud_profile.cdp_url = cdp_url
    await _do_login_cdp_async(cdp_url, login_url="https://example.com", username=PROXY_USERNAME or "", password=PROXY_PASSWORD or "")
    llm = ChatGoogle(api_key=GEMINI_API_KEY, model="gemini-2.5-flash", temperature=0)
    page_extract_llm = ChatGoogle(api_key=GEMINI_API_KEY, model="gemini-2.5-flash", temperature=0)
    llm_task = """
	I can see we're on the CNN website. Without searching action, please:
	1. Locate "More Top Stories" header. If scrolling is needed, only scroll 0.9 page each time. Click on the first article below this
	   Use tool fw_take_screenshot to take a screenshot, save as a.png
	   Use tool take_surrogate_screenshot to take a surrogate screenshot, dsf=1, timeout_secs=5, retain_text_metrics=True
	   If any popup appears, close it before taking screenshots
	2. Click the browser's back button. Then forward again
	   Use tool fw_take_screenshot to take a screenshot, save as b.png
	   Use tool take_surrogate_screenshot to take a surrogate screenshot, dsf=1, timeout_secs=5, retain_text_metrics=True
	   If any popup appears, close it before taking screenshots
	   Click the back button again. Confirm if we're back to the homepage
	3. Locate search box. Type "tariff" and press Enter, do not click search button!. Website must be navigated and Articles with "tariff" must be shown
	   Use tool fw_take_screenshot to take a screenshot, save as search.png
	   Use tool take_surrogate_screenshot to take a surrogate screenshot, dsf=1, timeout_secs=5, retain_text_metrics=True
	   If any popup appears, close it before taking screenshots
	   Use compare_screenshots to compare these 2 search images, and report similarity score
	4. Return to the homepage. Scroll down to the end of the page and up again to see if scrolling smooth
    """

    agent = Agent(
        task=llm_task,
        llm=llm,
        page_extract_llm=page_extract_llm,
        flash_mode=True,
        use_thinking=False,
        browser_profile=cloud_profile,
        calculate_cost=True,
        use_vision=True,
        vision_detail_level='low',
        llm_timeout=60,
    )
    await agent.run()
    close_saucelabs_session(cdp_url)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())