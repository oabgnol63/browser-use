import os
import sys
import asyncio
import time
from dotenv import load_dotenv
load_dotenv()

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
os.environ['BROWSER_USE_LOGGING_LEVEL'] = 'debug'
os.environ['BROWSER_USE_CLOUD_SYNC'] = 'false'
SAFEVIEW_URL = os.getenv("SAFEVIEW_URL")
PROXY_URL = os.getenv("PROXY_URL")
PROXY_USERNAME = os.getenv("PROXY_USERNAME", "msc@capp.com")
PROXY_PASSWORD = os.getenv("PROXY_PASSWORD", "Exploit99*")
GEMINI_API_KEY = os.getenv('GOOGLE_API_KEY')
GEMINI_API_KEY_2 = os.getenv('GOOGLE_API_KEY_2') if os.getenv('GOOGLE_API_KEY_2') else GEMINI_API_KEY

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
    selenium_client.navigate_to("https://bbc.com")
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
    I can see we're on the BBC website. Please:
    1. Locate "More News" or similar headline section
    2. Click on the first article below this
    3. Provide a fifty-word description of the article
    4. Click the browser's back button
    5. Click the browser's forward button  
    6. Confirm if the content is the same
    7. Click the back button again
    8. Confirm if we're back to the homepage
    9. Scroll down to the end of the page
    10. Look for a way to subscribe to BBC news
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
