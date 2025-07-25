import os
import asyncio
import sys
import yaml
 
from dataclasses import dataclass
from dotenv import load_dotenv
load_dotenv()
 
from browser_use.browser import BrowserSession, BrowserProfile
from browser_use.browser.types import ProxySettings
from browser_use.logging_config import setup_logging
setup_logging(log_level='DEBUG')
 
 
from browser_use import Agent, Controller, ActionResult
from browser_use.llm import ChatGoogle
 
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
 
if not os.getenv('GOOGLE_API_KEY'):
    raise ValueError('GOOGLE_API_KEY is not set. Please add it to your environment variables.')
 
@dataclass
class TestRunConfig:
    proxy_username: str | None
    proxy_pwd: str | None
    proxy_host: str | None
    llm_api_key: str | None
    llm_model: str

def load_test_from_yaml(file_path: str):
    with open(file_path, 'r') as file:
        test_data = yaml.safe_load(file)
    return test_data['test']
 
def create_test_run_agent(config: TestRunConfig, use_proxy: bool = False) -> Agent:
    
    if use_proxy:
        proxy_settings: ProxySettings = {
            "server": "http://proxy.surfcrew.com:3129",
        }
        
        br_profile = BrowserProfile(
            headless=False,
            proxy=proxy_settings,
            # Using user_data_dir=None ensures a clean, temporary profile for the test.
            user_data_dir=None,
            # executable_path="C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe"
        )

        browser_session = BrowserSession(
            browser_profile=br_profile,
        )        
        
        task = f'''
            Execute a test case that test how a website is rendered via proxy, with the following steps:\n
                - Step 1: Go to 'https://nbcnews.com'\n
                - Step 2: Wait 10 seconds. If a window prompted for proxy authentication: input {config.proxy_username} for "Email/Login ID" and click "Next". Otherwise ignore this step and go to Step 4\n
                - Step 3: Wait 10 seconds for the password page loaded. Input {config.proxy_pwd} for password and click "Log in"\n
                - Step 4: Wait for 20 seconds for browser to redirect to the website\n
                - Step 5: After the website is loaded, wait 60 seconds for all elements loaded completely. If not, reload the page and repeat this step, max 2 times\n
                - Step 6: Scroll down till the end of the page and up to top 2 times to make sure it smoothly\n
                - Step 7: Evaluate if the website is fully loaded or not using {{is_load_complete}} tool.If not loaded fully, wait for more 60 seconds, max 1 time\n
                - Step 8: Evalute the result: The test pass if it meets criteria:\n
                    * All elements(images, texts, fonts, etc,) are visible and not crashed or overlapped. Can use {{is_load_complete}} tool\n
                    * Scrolling smoothy\n
                - Step 9: Finally, use the {{screenshot}} tool to capture full-page screenshot and save as 'screenshot_px.png'.\n
        '''
    else:
        browser_session = BrowserSession(
            # browser_profile=BrowserProfile(
            #     executable_path="C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe"
            # )
        )
        task = f'''
            - Step 1: Go to 'https://nbcnews.com'\n
            - Step 2: Wait for 20 seconds for browser to redirect to the website\n
            - Step 3: After the website is loaded, wait 60 seconds for all elements loaded completely.\n
            - Step 4: Scroll down till the end of the page and up again a 2 times to make sure it work perfectly\n
            - Step 5: Evaluate if the website is fully loaded or not using {{is_load_complete}} tool.If not loaded fully, wait for more 60 seconds, max 1 time\n
            - Step 6: Finally, use the {{screenshot}} tool to capture full-page screenshot and save as 'screenshot_no_px.png'.\n
        '''
 
    controller = Controller()
   
    @controller.action("Takes a screenshot of the current page and saves it to a file.")
    async def screenshot(browser_session: BrowserSession, file_name: str, full_page: bool = False) -> ActionResult:
        """
        Takes a screenshot using Playwright's built-in method and saves it to the specified file.
        Args:
            browser_session: The BrowserSession instance.
            file_name: The file path to save the screenshot.
            full_page: If True, captures the full page; otherwise, just the viewport.
        Returns:
            ActionResult with the result or error.
        """
        try:
            page = await browser_session.get_current_page()
            await browser_session.remove_highlights()
            await page.bring_to_front()
            await page.screenshot(path=file_name, full_page=full_page)
            return ActionResult(extracted_content=f"Screenshot saved to {file_name}")
        except Exception as e:
            return ActionResult(error=f"Failed to save screenshot: {e}")
        
    @controller.action("Evaluate if a page is fully loaded")
    async def is_load_complete(browser_session: BrowserSession) -> ActionResult:
        script = '''
            () => {
                // First, check the document's readyState.
                if (document.readyState !== 'complete') {
                    return {
                        is_complete: false,
                        reason: `Document not ready yet. Current state: ${document.readyState}`
                    };
                }
 
                // Then, check all image elements on the page.
                const images = Array.from(document.images);
                const incompleteImages = images.filter(img => !img.complete || img.naturalWidth === 0);
 
                if (incompleteImages.length > 0) {
                    return {
                        is_complete: false,
                        reason: `${incompleteImages.length} image(s) are still loading or failed to load.`,
                        // For debugging, list the first 5 incomplete image URLs
                        incomplete_urls: incompleteImages.slice(0, 5).map(img => img.src)
                    };
                }
 
                // If all checks pass, the page is considered fully loaded.
                return { is_complete: true, reason: 'Document and all images are fully loaded.' };
 
            }
        '''
        try:
            result = await browser_session.execute_javascript(script)
            message = f"✅ {result['reason']}" if result['is_complete'] else f"⏳ {result['reason']}"
            if not result.get('is_complete') and result.get('incomplete_urls'):
                message += f" Example URLs: {result['incomplete_urls']}"
            return ActionResult(extracted_content=message, long_term_memory=message)
        except Exception as e:
            return ActionResult(error=f"Failed to evaluate page load state: {e}")
 
 
    
    llm = ChatGoogle(api_key=config.llm_api_key, model=config.llm_model, temperature=1)
 
    agent = Agent(task=task,
                  llm=llm,
                  use_thinking=True,
                  browser_session=browser_session,
                  controller=controller,
                  enable_cloud_sync=False,
                  )
    return agent
 
async def main():
    try:
        test_run_config_px = TestRunConfig(
            proxy_username=os.getenv("PROXY_USERNAME"),
            proxy_pwd=os.getenv("PROXY_PWD"),
            proxy_host=os.getenv("PROXY_HOST", "http://proxy.surfcrew.com:3129"),
            llm_api_key=os.getenv("GOOGLE_API_KEY"),
            llm_model="gemini-2.5-pro"
        )
 
        test_run_config_no_px = TestRunConfig(
            proxy_username=None,
            proxy_pwd=None,
            proxy_host=None,
            llm_api_key=os.getenv("GOOGLE_API_KEY"),
            llm_model="gemini-2.5-pro"
        )
 
        agent_px = create_test_run_agent(test_run_config_px, use_proxy=True)
        agent_no_px = create_test_run_agent(test_run_config_no_px)
        await asyncio.gather(agent_px.run(), agent_no_px.run())
        await agent_px.close()
        await agent_no_px.close()
    except Exception as e:
        print(e)
 
def main2():
    tests = load_test_from_yaml('test_scripts.yaml')
    for test in tests:
        steps = test['TestSteps']
if __name__ == "__main__":
    asyncio.run(main())