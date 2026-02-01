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
        # cross_origin_iframes=True,
        # minimum_wait_page_load_time=7,
        # window_size=ViewportSize(width=1440, height=900),
        # proxy=ProxySettings(
        #     server=PROXY_URL,
        #     username=PROXY_USERNAME,
        #     password=PROXY_PASSWORD
        # ),
    )

async def main():

        llm = ChatGoogle(api_key=GEMINI_API_KEY, model="gemini-2.5-flash", temperature=0)
        page_extract_llm = ChatGoogle(api_key=GEMINI_API_KEY, model="gemini-2.5-flash-lite", temperature=0)
        llm_task = """
Go to cnn.com.
Locate Weekend Read header on homepage. If scroll is needed, scroll one page each.
Click on the first article link under this header.
Scroll down 2 pages on the article page.
Navigate back to homepage.
Navigate forward to the article page.
        """
        
        agent = Agent(
            task=llm_task,
            llm=llm,
            page_extract_llm=page_extract_llm,
            # flash_mode=True,
            use_thinking=True,
            browser_profile=profile,
            calculate_cost=True,
            # use_vision=True,
            # vision_detail_level='low',
            llm_timeout=60,
        )
        result = await agent.run()
        
        print("\nAGENT RESULT:")
        print(result)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())