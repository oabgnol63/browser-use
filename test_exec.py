import os
import asyncio
import sys
import yaml

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
PROXY_HOST = os.getenv('PROXY_HOST', "http://proxy.surfcrew.com:3129")
@dataclass
class TestRunConfig:
    task: str
    proxy_host: str = PROXY_HOST
    proxy_username: Optional[str] = None
    proxy_pwd: Optional[str] = None
    llm_api_key: Optional[str] = None
    llm_model: Optional[str] = "gemini-2.5-flash"
    use_proxy: bool = False

def load_test_from_yaml(file_path: str):
    with open(file_path, 'r') as file:
        test_data = yaml.safe_load(file)
    return test_data['tests']
 
def create_test_run_agent(config: TestRunConfig) -> Agent:
    
    if config.use_proxy:
        proxy_settings: ProxySettings = {
            "server": config.proxy_host
        }
        br_profile = BrowserProfile(
            headless=False,
            proxy=proxy_settings,
            # Using user_data_dir=None ensures a clean, temporary profile for the test.
            user_data_dir=None,
            # keep_alive=True,
        )
        browser_session = BrowserSession(
            browser_profile=br_profile,
        )        
        
    else:
        browser_session = BrowserSession()

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
    
    llm = ChatGoogle(api_key=config.llm_api_key, model=config.llm_model if config.llm_model else "gemini-2.5-flash", temperature=1)
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
        tests = load_test_from_yaml('test_scripts.yaml')
        for test in tests:
            px_steps_dict = test['TestStepsPXY']
            npx_steps_dict = test.get('TestSteps', None)
            params = test['TestParams']
            px_steps_string = '\n'.join(key + ': ' + value for key, value in px_steps_dict.items()).format(**params)
            npx_steps_string = '\n'.join(key + ': ' + value for key, value in npx_steps_dict.items()).format(**params)
            px_test_run_config = TestRunConfig(
                proxy_username=os.getenv("PROXY_USERNAME"),
                proxy_pwd=os.getenv("PROXY_PWD"),
                proxy_host=PROXY_HOST,
                llm_api_key=os.getenv("GOOGLE_API_KEY"),
                llm_model="gemini-2.5-pro", 
                task=px_steps_string,
                use_proxy=True
            )
            agent_px = create_test_run_agent(px_test_run_config)
            if npx_steps_dict:
                npx_test_run_config = TestRunConfig(
                    llm_api_key=os.getenv("GOOGLE_API_KEY"),
                    llm_model="gemini-2.5-flash",
                    task=npx_steps_string
                )
                agent_no_px = create_test_run_agent(npx_test_run_config)
            await asyncio.gather(agent_px.run(), agent_no_px.run())
            await agent_px.close()
            await agent_no_px.close()
    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    asyncio.run(main())