import os
import sys
from dotenv import load_dotenv
load_dotenv()

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.environ['BROWSER_USE_LOGGING_LEVEL'] = 'debug'
os.environ['BROWSER_USE_CLOUD_SYNC'] = 'false'
GEMINI_API_KEY = os.getenv('GOOGLE_API_KEY')
GEMINI_API_KEY_2 = os.getenv('GOOGLE_API_KEY_2') if os.getenv('GOOGLE_API_KEY_2') else GEMINI_API_KEY

from browser_use.browser.profile import CloudBrowserProfile, ViewportSize
from browser_use import Agent
from browser_use.llm import ChatGoogle
from sauce_manager import saucelabs_session_creation, close_saucelabs_session

async def main():
    # Initialize cloud profile and create SauceLabs session only when running main
    cloud_profile = CloudBrowserProfile(
        # required
        browser_name='chrome',
        browser_version='latest',
        platform_name='Windows 11',
        session_name="CloudBrowserProfile Test",
        tags=['browser-use', 'cloudprofile', 'agent-test'],
        build_name='browser-use-cloudprofile',
        is_local=False,
        # optional
        minimum_wait_page_load_time=7,
        maximum_wait_page_load_time=10,
        wait_for_network_idle_page_load_time=1.5,
        default_navigation_timeout=30000,
        timeout=60000,
        cross_origin_iframes=False,
        skip_iframe_documents=False,  # experimental, should not use
        stealth=True,
        enable_default_extensions=True,
        viewport=ViewportSize(width=1440, height=900),
    )

    cdp_url = saucelabs_session_creation(cloud_profile)

    if not cdp_url:
        return
    cloud_profile.cdp_url = cdp_url

    llm = ChatGoogle(api_key=GEMINI_API_KEY, model="gemini-2.5-flash", temperature=0)
    page_extract_llm = ChatGoogle(api_key=GEMINI_API_KEY, model="gemini-2.5-flash-lite", temperature=0)
    llm_task = """
    Go to https://bbc.com\n
    Locate "Only From The BBC" headline\n
    Click on the first article below this\n
    Fifty words to describe it?\n
    Click go backward button\n
    Is it a homepage?
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