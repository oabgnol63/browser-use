import os
import sys
from dotenv import load_dotenv
load_dotenv()

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.environ['BROWSER_USE_LOGGING_LEVEL'] = 'debug'
os.environ['BROWSER_USE_CLOUD_SYNC'] = 'false'
GEMINI_API_KEY = os.getenv('GOOGLE_API_KEY')
GEMINI_API_KEY_2 = os.getenv('GOOGLE_API_KEY_2') if os.getenv('GOOGLE_API_KEY_2') else GEMINI_API_KEY

from browser_use.browser.profile import BrowserProfile
from browser_use.browser.session import BrowserSession
from browser_use.browser.profile import ViewportSize
from browser_use import Agent
from browser_use.llm import ChatGoogle

profile = BrowserProfile(
        minimum_wait_page_load_time=7,
        wait_for_network_idle_page_load_time=1.5,
        cross_origin_iframes=False,
        window_size=ViewportSize(width=1920, height=1080),
    )

async def main():

        llm = ChatGoogle(api_key=GEMINI_API_KEY, model="gemini-2.5-flash", temperature=0)
        page_extract_llm = ChatGoogle(api_key=GEMINI_API_KEY, model="gemini-2.5-flash-lite", temperature=0)
        llm_task = """
        Go to https://tinhocngoisao.com/products/pc-star-karmish-b-plus-intel-core-i5-14400f-b760-ddr5-32gb-ssd-512-rtx-5060-wifi
        Search for a table under "THÔNG SỐ KỸ THUẬT" header
        Compare the sum of all components' prices with the price in the first page
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