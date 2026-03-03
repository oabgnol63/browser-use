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
from browser_use import Agent, Tools, ActionResult, ChatGoogle, BrowserSession
from sauce_manager import saucelabs_session_creation, close_saucelabs_session, _do_login_cdp_async

async def main():
    tools = Tools()
    @tools.registry.action(description='Locate a header on the page and scroll to it smoothly')
    async def locate_header(header: str, browser_session: BrowserSession) -> ActionResult:
        try:
            # Get CDP session
            cdp_session = await browser_session.get_or_create_cdp_session()
            cdp_client = cdp_session.cdp_client
            session_id = cdp_session.session_id
            
            # Escape header text for JavaScript
            search_text = header.strip().replace('\\', '\\\\').replace('"', '\\"').replace("'", "\\'")
            
            # Use JavaScript to find header - searches the ENTIRE page, not just viewport
            find_header_js = f'''
                (() => {{
                    const searchText = "{search_text}".toLowerCase().trim();
                    
                    // Optimization: Single DOM traversal instead of multiple XPath evaluations
                    // Select all potential header elements
                    const candidates = document.querySelectorAll('h1, h2, h3, h4, h5, h6, header, [role="heading"], .heading, .header');
                    
                    for (const element of candidates) {{
                        const text = (element.innerText || element.textContent || '').toLowerCase();
                        if (text.includes(searchText)) {{
                             const rect = element.getBoundingClientRect();
                             element.scrollIntoView({{ behavior: 'smooth', block: 'center' }});
                             return {{
                                found: true,
                                tag: element.tagName,
                                text: (element.innerText || element.textContent || '').trim().substring(0, 100),
                                top: rect.top + window.scrollY
                             }};
                        }}
                        
                        // Check anchor tags inside headers (common pattern)
                        const link = element.querySelector('a');
                        if (link) {{
                            const linkText = (link.innerText || link.textContent || '').toLowerCase();
                            if (linkText.includes(searchText)) {{
                                 const rect = element.getBoundingClientRect();
                                 element.scrollIntoView({{ behavior: 'smooth', block: 'center' }});
                                 return {{
                                    found: true,
                                    tag: element.tagName,
                                    text: (element.innerText || element.textContent || '').trim().substring(0, 100),
                                    top: rect.top + window.scrollY
                                 }};
                            }}
                        }}
                    }}
                    
                    return {{ found: false }};
                }})()
            '''
            
            # Execute JavaScript to find and scroll to the element
            # Note: awaitPromise=False because scrollIntoView is synchronous (it triggers scroll but doesn't wait)
            result = await cdp_client.send.Runtime.evaluate(
                params={'expression': find_header_js, 'returnByValue': True},
                session_id=session_id
            )
            
            result_value = result.get('result', {}).get('value', {})
            
            if isinstance(result_value, dict) and result_value.get('found'):
                tag = result_value.get('tag', 'unknown')
                text = result_value.get('text', '')
                top = result_value.get('top', 0)
                
                print(f"[PRINT] Header found: <{tag}> text='{text}' at Y={top}")
                
                # Wait a short time for scroll to complete
                # This is much safer than awaiting a JS promise
                await asyncio.sleep(1)
                
                result_msg = f"Header '{header}' located and scrolled into view"
                print(f"[PRINT] {result_msg}")
                return ActionResult(extracted_content=result_msg, include_in_memory=True)
            
            else:
                # Header not found - get list of available headers for debugging
                get_headers_js = '''
                    (() => {
                        const headers = document.querySelectorAll('h1, h2, h3, h4, h5, h6');
                        return Array.from(headers).slice(0, 10).map(h => ({
                            tag: h.tagName,
                            text: (h.innerText || h.textContent || '').trim().substring(0, 80)
                        }));
                    })()
                '''
                
                # Re-acquire CDP session in case it changed
                cdp_session = await browser_session.get_or_create_cdp_session()
                headers_result = await cdp_session.cdp_client.send.Runtime.evaluate(
                    params={'expression': get_headers_js, 'returnByValue': True},
                    session_id=cdp_session.session_id
                )
                
                all_headers = headers_result.get('result', {}).get('value', [])
                
                print(f"[PRINT] Header '{header}' not found. Available headers (first 10):")
                for idx, h in enumerate(all_headers, 1):
                    print(f"  {idx}. <{h.get('tag', '?')}> : {h.get('text', '')}")
                
                result_msg = f"Header '{header}' not found on the page."
                print(f"[PRINT] {result_msg}")
                return ActionResult(error=result_msg, include_in_memory=True, success=False)
            
        except Exception as e:
            print(f"[PRINT] Error occurred while locating header: {e}")
            import traceback
            traceback.print_exc()
            return ActionResult(error=f"An error occurred while locating header: {e}")
			

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
        stealth=True,
        enable_default_extensions=False,
        viewport=ViewportSize(width=1440, height=900),
        # proxy=ProxySettings(
        #     server=PROXY_URL,
        #     username=PROXY_USERNAME,
        #     password=PROXY_PASSWORD
        # ),
    )

    cdp_url = saucelabs_session_creation(cloud_profile)

    if not cdp_url:
        return
    cloud_profile.cdp_url = cdp_url
    # await _do_login_cdp_async(cdp_url, login_url="https://example.com", username=PROXY_USERNAME or "", password=PROXY_PASSWORD or "")
    llm = ChatGoogle(api_key=GEMINI_API_KEY, model="gemini-2.5-flash", temperature=0)
    page_extract_llm = ChatGoogle(api_key=GEMINI_API_KEY, model="gemini-2.5-flash", temperature=0)
    llm_task = """
    Go to cnn.com
    If there are any cookie banners or popups, close them or accept them.
    Use the locate_header tool to find and scroll to the header "More From CNN".
    Click on the first link under that header.
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
        tools=tools,
    )
    await agent.run()
    close_saucelabs_session(cdp_url)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())