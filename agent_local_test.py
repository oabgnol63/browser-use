import os
import sys
from dotenv import load_dotenv
load_dotenv()

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.environ['BROWSER_USE_LOGGING_LEVEL'] = 'debug'
os.environ['BROWSER_USE_CLOUD_SYNC'] = 'false'
os.environ['BROWSER_USE_SCREENSHOT_FILE'] = 'debug_screenshot.png'
SAFEVIEW_URL = os.getenv("SAFEVIEW_URL")
PROXY_URL = os.getenv("PROXY_URL")
PROXY_USERNAME = os.getenv("PROXY_USERNAME")
PROXY_PASSWORD = os.getenv("PROXY_PASSWORD")

GEMINI_API_KEY = os.getenv('GOOGLE_API_KEY')
GEMINI_API_KEY_2 = os.getenv('GOOGLE_API_KEY_2') if os.getenv('GOOGLE_API_KEY_2') else GEMINI_API_KEY

from browser_use.browser.profile import BrowserProfile
from browser_use.browser import ProxySettings
from browser_use.browser.profile import ViewportSize
from browser_use import Agent
from browser_use.llm import ChatGoogle

profile = BrowserProfile(
        cross_origin_iframes=True,
        minimum_wait_page_load_time=7,
        window_size=ViewportSize(width=1440, height=900),
        proxy=ProxySettings(
            server=PROXY_URL,
            username=PROXY_USERNAME,
            password=PROXY_PASSWORD
        ),
    )

async def main():

        llm = ChatGoogle(api_key=GEMINI_API_KEY, model="gemini-2.5-flash", temperature=0)
        page_extract_llm = ChatGoogle(api_key=GEMINI_API_KEY, model="gemini-2.5-flash-lite", temperature=0)
        llm_task = """
        Go to https://safe.surfcrew.com/https://www.cnn.com
        Perform the following actions in sequence:
        1. Locate "More Top Stories" header. If scrolling is needed, only scroll 0.9 page each time. Click on the first article below this
        2. Click the browser's back button. Then forward again
        Click the back button again. Confirm if we're back to the homepage
        3. Locate search box and search for "football"
        Articles with "football" must be shown. Note that after clicking search button, the page elements may change position, so re-evaluate the page before typing text or clicking search button
        4. Return to the homepage. Scroll down to the end of the page and up again to see if scrolling smooth
        """
        
        agent = Agent(
            task=llm_task,
            llm=llm,
            page_extract_llm=page_extract_llm,
            flash_mode=True,
            use_thinking=False,
            browser_profile=profile,
            calculate_cost=True,
            use_vision=True,
            vision_detail_level='low',
            llm_timeout=60,
        )
        await agent.run()

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())