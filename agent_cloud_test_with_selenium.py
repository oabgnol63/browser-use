import os
import sys
import asyncio
import time
from dotenv import load_dotenv
load_dotenv()


os.environ['BROWSER_USE_LOGGING_LEVEL'] = 'debug'
os.environ['BROWSER_USE_CLOUD_SYNC'] = 'false'
os.environ['BROWSER_USE_SCREENSHOT_FILE'] = 'debug_screenshot.png'
os.environ['TIMEOUT_ClickElementEvent'] = '30'
os.environ['TIMEOUT_NavigationCompleteEvent'] = '30'
os.environ['TIMEOUT_ScreenshotEvent'] = '90'
os.environ['TIMEOUT_BrowserStateRequestEvent'] = '180'

SAFEVIEW_URL = os.getenv("SAFEVIEW_URL")
PROXY_URL = os.getenv("PROXY_URL")
PROXY_USERNAME = os.getenv("PROXY_USERNAME")
PROXY_PASSWORD = os.getenv("PROXY_PASSWORD")
GEMINI_API_KEY = os.getenv('GOOGLE_API_KEY')
GEMINI_API_KEY_2 = os.getenv('GOOGLE_API_KEY_2') if os.getenv('GOOGLE_API_KEY_2') else GEMINI_API_KEY

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from browser_use.browser.profile import ViewportSize
from browser_use.browser import ProxySettings, CloudBrowserProfile
from browser_use import Agent, ChatGoogle
from sauce_manager import saucelabs_session_creation, close_saucelabs_session, _do_login_cdp_async
from selenium_client import create_selenium_client_from_cdp_url

async def main():
    # Initialize cloud profile and create SauceLabs session only when running main
    cloud_profile = CloudBrowserProfile(
        # required
        browser_name='chrome',
        browser_version='latest',
        platform_name='Windows 10',
        session_name="CloudBrowserProfile Test with Selenium",
        tags=['browser-use', 'cloudprofile', 'agent-test', 'selenium'],
        build_name='browser-use-cloudprofile-selenium',
        is_local=False,
        # optional
        # disable_security=True,  # don't set it as it will conflict with extensions loading
        window_size=ViewportSize(width=1440, height=900),
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
    
    # Perform login using CDP
    await _do_login_cdp_async(cdp_url, login_url="https://example.com", username=PROXY_USERNAME or "", password=PROXY_PASSWORD or "")
    
    # NEW: Create Selenium client that attaches to the same session
    print("\n🔗 Creating Selenium client for the same session...")
    selenium_client = create_selenium_client_from_cdp_url(cdp_url)
    driver = selenium_client.attach_to_session()
    
    # Use Selenium to perform some initial setup or verification
    print("🔍 Using Selenium to check current state...")
    current_url = selenium_client.get_current_url()
    page_title = selenium_client.get_page_title()
    print(f"📄 Current page (via Selenium): {page_title}")
    print(f"🔗 Current URL (via Selenium): {current_url}")
    
    # Take a screenshot before agent starts
    selenium_client.take_screenshot("before_agent.png")
    
    # Use Selenium to navigate to the starting page for the agent
    print("🌐 Using Selenium to navigate to BBC...")
    selenium_client.navigate_to("https://cnn.com")
    time.sleep(3)
    
    # Verify navigation with Selenium
    after_nav_title = selenium_client.get_page_title()
    after_nav_url = selenium_client.get_current_url()
    print(f"📄 After navigation (via Selenium): {after_nav_title}")
    print(f"🔗 After navigation URL (via Selenium): {after_nav_url}")
    
    # Set up LLMs and Agent
    llm = ChatGoogle(api_key=GEMINI_API_KEY, model="gemini-2.5-flash", temperature=0)
    page_extract_llm = ChatGoogle(api_key=GEMINI_API_KEY, model="gemini-2.5-flash", temperature=0)
    
    llm_task = """
        Go to https://www.cnn.com. Perform the following actions in sequence:
        1. Locate "More Top Stories" header. If scrolling is needed, only scroll 0.9 page each time. Click on the first article below this
        2. Click the browser's back button. Then forward again
        Click the back button again. Confirm if we're back to the homepage
        3. Locate search box and search for "football". Note that after typing text, press Enter key to submit search
        Articles with "football" must be shown. Note that after clicking search button, the page elements may change position, so re-evaluate the page before typing text or clicking search button
        4. Return to the homepage. Scroll down to the end of the page and up again to see if scrolling smooth
    """

    # Run the browser-use agent
    print("\n🤖 Starting browser-use Agent...")
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
    
    # After agent completes, use Selenium for final verification
    print("\n🔍 Using Selenium for post-agent verification...")
    final_title = selenium_client.get_page_title()
    final_url = selenium_client.get_current_url()
    print(f"📄 Final page (via Selenium): {final_title}")
    print(f"🔗 Final URL (via Selenium): {final_url}")
    
    # Take final screenshot
    selenium_client.take_screenshot("after_agent.png")
    
    # Use Selenium to gather some additional page information
    try:
        # Count the number of links on the page
        link_count = selenium_client.execute_javascript("return document.querySelectorAll('a').length")
        print(f"🔗 Number of links on page (via Selenium): {link_count}")
        
        # Get page height
        page_height = selenium_client.execute_javascript("return document.body.scrollHeight")
        print(f"📏 Page height (via Selenium): {page_height}px")
        
        # Check if we can find any specific BBC elements
        try:
            news_elements = selenium_client.execute_javascript("""
                return Array.from(document.querySelectorAll('[data-testid*="news"], [class*="news"], [class*="story"]')).length
            """)
            print(f"📰 News-related elements found (via Selenium): {news_elements}")
        except:
            print("📰 Could not count news elements")
            
    except Exception as e:
        print(f"⚠️ Error gathering additional info: {e}")
    
    # Clean up Selenium client
    selenium_client.quit()
    
    # Close SauceLabs session
    close_saucelabs_session(cdp_url)
    
    print("\n✅ Test completed successfully!")
    print("🎯 Both browser-use Agent and Selenium client operated on the same browser session")

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
