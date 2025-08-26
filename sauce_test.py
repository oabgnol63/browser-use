import os
import asyncio
import sys
from dotenv import load_dotenv

load_dotenv()
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.environ['BROWSER_USE_LOGGING_LEVEL'] = 'debug'
os.environ['BROWSER_USE_CLOUD_SYNC'] = 'false'

from browser_use.llm import ChatGoogle
from browser_use import Agent
from browser_use.browser import BrowserProfile
from playwright.async_api import async_playwright

GEMINI_API_KEY = os.getenv('GOOGLE_API_KEY')
GEMINI_API_KEY_2 = os.getenv('GOOGLE_API_KEY_2') if os.getenv('GOOGLE_API_KEY_2') else GEMINI_API_KEY
os.environ['SELENIUM_REMOTE_URL'] = "https://bao_vi:51edb4f2-d883-4bd4-b57a-4800736f73d3@ondemand.us-west-1.saucelabs.com:443/wd/hub"
os.environ['SELENIUM_REMOTE_CAPABILITIES'] = '{"browserName": "chrome", "platformName": "Windows 11", "sauce:options": {"devTools": true, "name": "My Playwright CDP Test"}}'
llm = ChatGoogle(api_key=GEMINI_API_KEY, model="gemini-2.5-flash", temperature=0)
page_extraction_llm = ChatGoogle(api_key=GEMINI_API_KEY_2, model="gemini-2.5-flash-lite", temperature=0)


async def main():
    async with async_playwright() as pw:
        # Launch connects to remote Sauce Labs browser via CDP
        browser = await pw.chromium.launch(headless=False)  # Headless=False for video capture in Sauce Labs
        bf_profile = BrowserProfile(
            headless=False, # cannot config proxy settings in headless mode
            user_data_dir=None, # Using a temporary profile (None) is best practice for isolated tests.
            minimum_wait_page_load_time=7,
            maximum_wait_page_load_time=10,
            wait_for_network_idle_page_load_time=1.5,
            default_navigation_timeout=30000,
        )
        agent = Agent(
            task="Go to https://google.com\nSearch Playwright\nIf capcha, ensure new images are load before click Verify",
            llm=llm,
            page_extraction_llm=page_extraction_llm,
            browser=browser,
            flash_mode=True,
            vision_detail_level='low',
            # browser_profile=bf_profile  # type: ignore
        )

        await agent.run()

        # Clean up
        await browser.close()

if __name__ == '__main__':
    asyncio.run(main())