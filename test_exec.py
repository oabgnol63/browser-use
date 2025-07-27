import os
import asyncio
import sys
import yaml
import argparse

from typing import Optional
from dataclasses import dataclass
from dotenv import load_dotenv
from browser_use.browser import BrowserSession, BrowserProfile
from browser_use.browser.types import ProxySettings
from browser_use.logging_config import setup_logging
from browser_use import Agent, Controller, ActionResult
from browser_use.llm import ChatGoogle

load_dotenv()
setup_logging(log_level='DEBUG')
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
 
if not os.getenv('GOOGLE_API_KEY'):
    raise ValueError('GOOGLE_API_KEY is not set. Please add it to your environment variables.')

@dataclass
class TestRunConfig:
    task: str
    proxy_host: Optional[str] = None
    proxy_username: Optional[str] = None
    proxy_pwd: Optional[str] = None
    llm_api_key: Optional[str] = None
    llm_model: Optional[str] = "gemini-2.5-flash"
    use_proxy: bool = False
    real_browser: bool = False

def load_test_from_yaml(file_path: str):
    with open(file_path, 'r') as file:
        test_data = yaml.safe_load(file)
    return test_data['tests']
 
def create_test_run_agent(config: TestRunConfig) -> Agent:
    
    if config.use_proxy and config.proxy_host:
        proxy_settings: ProxySettings = {
            "server": config.proxy_host
        }
        br_profile = BrowserProfile(
            headless=False,
            proxy=proxy_settings,
            # Using user_data_dir=None ensures a clean, temporary profile for the test.
            user_data_dir=None,
            minimum_wait_page_load_time=10,
            maximum_wait_page_load_time=60,
            # keep_alive=True,
        )
        browser_session = BrowserSession(
            browser_profile=br_profile,
        )        
        
    else:
        browser_session = BrowserSession()

    if config.real_browser:
        browser_session.browser_profile.executable_path = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe"  # Path to Chrome executable
        print("Using real browser for testing.")

    task = config.task

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
        
    @controller.action("Simulate the go forward button in the browser.")
    async def go_forward(browser_session: BrowserSession) -> ActionResult:
        try:
            page = await browser_session.get_current_page()
            await page.go_forward()
            return ActionResult(extracted_content=f"Successfully navigated forward in the browser history.")
        except Exception as e:
            return ActionResult(error=f"Failed to navigate forward: {e}")

    # @controller.action("Evaluate if a page is fully loaded")
    # async def is_load_complete(browser_session: BrowserSession) -> ActionResult:
    #     script = '''
    #         () => {
    #             // First, check the document's readyState.
    #             if (document.readyState !== 'complete') {
    #                 return {
    #                     is_complete: false,
    #                     reason: `Document not ready yet. Current state: ${document.readyState}`
    #                 };
    #             }
 
    #             // Then, check all image elements on the page.
    #             const images = Array.from(document.images);
    #             const incompleteImages = images.filter(img => !img.complete || img.naturalWidth === 0);
 
    #             if (incompleteImages.length > 0) {
    #                 return {
    #                     is_complete: false,
    #                     reason: `${incompleteImages.length} image(s) are still loading or failed to load.`,
    #                     // For debugging, list the first 5 incomplete image URLs
    #                     incomplete_urls: incompleteImages.slice(0, 5).map(img => img.src)
    #                 };
    #             }
 
    #             // If all checks pass, the page is considered fully loaded.
    #             return { is_complete: true, reason: 'Document and all images are fully loaded.' };
 
    #         }
    #     '''
    #     try:
    #         result = await browser_session.execute_javascript(script)
    #         message = f"✅ {result['reason']}" if result['is_complete'] else f"⏳ {result['reason']}"
    #         if not result.get('is_complete') and result.get('incomplete_urls'):
    #             message += f" Example URLs: {result['incomplete_urls']}"
    #         return ActionResult(extracted_content=message, long_term_memory=message)
    #     except Exception as e:
    #         return ActionResult(error=f"Failed to evaluate page load state: {e}")
    
    llm = ChatGoogle(api_key=config.llm_api_key, model=config.llm_model if config.llm_model else "gemini-2.5-flash", temperature=1,)
    agent = Agent(task=task,
                  llm=llm,
                  use_thinking=True,
                  browser_session=browser_session,
                  controller=controller,
                  enable_cloud_sync=False,
                  calculate_cost=True,
                  max_remote_calls=15,
                  )
    return agent
 
async def main():
    try:
        parser = argparse.ArgumentParser(description="Run browser tests with optional proxy.")
        parser.add_argument('--proxy_url', action='store', required=True, help="(Required) Use proxy settings for the tests.")
        parser.add_argument('--proxy_username', action='store', required=True, help="Proxy username for authentication.")
        parser.add_argument('--proxy_password', action='store', required=True, help="Proxy password for authentication.")
        parser.add_argument('--test_id', action='store', required=False, help="ID of the test to run. If not provided, all tests will be executed.")
        parser.add_argument('--use_real_browser', action='store', type=bool, required=False, help="Use real browser for testing.")
        args = vars(parser.parse_args())
        tests = load_test_from_yaml('test_scripts.yaml')
        if args['test_id']:
            tests = [test for test in tests if str(test['TestID']) == str(args['test_id'])]
            if not tests:
                print(f"No test found with ID: {args['test_id']}")
                return
        for test in tests:
            pxy_steps_dict = test['TestStepsPXY']
            npxy_steps_dict = test.get('TestSteps', None)
            params = test['TestParams']
            params['TestName'] = test['TestName']
            params.update(args)
            px_steps_string = 'Execute the test cases with the following steps:\n' + \
                            '\n'.join(key + ': ' + value for key, value in pxy_steps_dict.items()).format(**params)
            npx_steps_string = '\n'.join(key + ': ' + value for key, value in npxy_steps_dict.items()).format(**params)
            px_test_run_config = TestRunConfig(
                proxy_username=params['proxy_username'],
                proxy_pwd=params['proxy_password'],
                proxy_host=params['proxy_url'],
                llm_api_key=os.getenv("GOOGLE_API_KEY"),
                llm_model="gemini-2.5-flash-lite", 
                task=px_steps_string,
                use_proxy=True,
                real_browser=params.get('use_real_browser', False)
            )
            agent_pxy = create_test_run_agent(px_test_run_config)
            if npxy_steps_dict:
                npx_test_run_config = TestRunConfig(
                    llm_api_key=os.getenv("GOOGLE_API_KEY"),
                    llm_model="gemini-2.5-flash-lite",
                    task=npx_steps_string,
                    real_browser=params.get('use_real_browser', False)
                )
                agent_no_pxy = create_test_run_agent(npx_test_run_config)
                await asyncio.gather(agent_pxy.run(), agent_no_pxy.run())
                await asyncio.gather(agent_pxy.close(), agent_no_pxy.close())
            else:
                await agent_pxy.run()
                await agent_pxy.close()

    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    asyncio.run(main())