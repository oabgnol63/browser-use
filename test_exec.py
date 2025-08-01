import os
import asyncio
import multiprocessing
import sys
import argparse
import inspect
import yaml
import time
import json
import io
import tkinter
import numpy as np
from dotenv import load_dotenv
from PIL import Image
from typing import Optional, Dict
from pydantic import BaseModel, Field
from dataclasses import dataclass

load_dotenv()
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if not os.getenv('GOOGLE_API_KEY'):
    raise ValueError('GOOGLE_API_KEY is not set. Please add it to your environment variables.')
GEMINI_API_KEY = os.getenv('GOOGLE_API_KEY')
GEMINI_API_KEY_2 = os.getenv('GOOGLE_API_KEY_2') if os.getenv('GOOGLE_API_KEY_2') else GEMINI_API_KEY

parser = argparse.ArgumentParser(description="Run browser tests with optional proxy.")
parser.add_argument('--proxy_url', action='store', required=True, help="(Required) Use proxy settings for the tests.")
parser.add_argument('--proxy_username', action='store', required=True, help="Proxy username for authentication.")
parser.add_argument('--proxy_password', action='store', required=True, help="Proxy password for authentication.")
parser.add_argument('--test_id', action='store', required=False, help="ID of the test to run, or all tests will be executed.")
parser.add_argument('--use_real_browser', action='store_true', required=False, help="Use real browser for testing.")
parser.add_argument('--headless', action='store_true', help="Run browser in headless mode.")
parser.add_argument('--log_level', action='store', default='info', choices=['debug', 'info', 'warning', 'error', 'result'],
                    help="Set the logging level (default: info).")
args = vars(parser.parse_args())

if args['log_level']:
    os.environ['BROWSER_USE_LOGGING_LEVEL'] = args['log_level']
# Disable cloud sync function
os.environ['BROWSER_USE_CLOUD_SYNC'] = 'false'

from browser_use.browser import BrowserSession, BrowserProfile
from browser_use.browser.types import ProxySettings, ViewportSize
from browser_use import Agent, Controller, ActionResult
from browser_use.llm import ChatGoogle


class AgentStructuredOutput(BaseModel):
    result: str = Field(description="'Pass' or 'Fail': The result of the test case")
    describe: str = Field(description="The web state evaluated by test steps")
    screenshot_path: str = Field(description="Path to the screenshot captured")
    confidence: Optional[float] = Field(default=None, description="Confidence score from image comparison, if any.")


@dataclass
class TestRunConfig:
    task: str
    max_actions_per_step: Optional[int]
    proxy_host: Optional[str] = None
    proxy_username: Optional[str] = None
    proxy_pwd: Optional[str] = None
    llm_api_key: Optional[str] = None
    llm_model: Optional[str] = "gemini-2.5-flash"
    use_proxy: bool = False
    real_browser: bool = False
    headless: bool = False


def get_screen_size():
    """Gets the screen size, with a fallback for headless environments."""
    try:
        root = tkinter.Tk()
        root.withdraw()
        width = root.winfo_screenwidth()
        height = root.winfo_screenheight()
        root.destroy()
        return width, height
    except tkinter.TclError:
        print("Warning: Could not detect screen size (no display available). Falling back to 1920x1080.")
        return 1920, 1080

# Get screen dimensions
screen_width, screen_height = get_screen_size()

def load_test_from_yaml(file_path: str):
    with open(file_path, "r") as file:
        test_data = yaml.safe_load(file)
    return test_data['tests']


def generate_result(agent: Agent) -> Optional[Dict]:
    agent_result = agent.state.history.final_result()
    if agent_result:
        agent_result = json.loads(agent_result)
        agent_result["ExecutionTime"] = agent.state.history.total_duration_seconds()
        agent_result["AISteps"] = agent.state.history.number_of_steps()
        if agent.state.history.usage:
            agent_result["TotalCost"] = agent.state.history.usage.total_cost
            agent_result["TotalTokens"] = agent.state.history.usage.total_tokens
        else:
            agent_result["TotalCost"] = 0
            agent_result["TotalTokens"] = 0
        return agent_result
    return None

 
async def create_test_run_agent(config: TestRunConfig) -> Agent:
    signature = inspect.signature(Agent.__init__)
    if config.use_proxy and config.proxy_host:
        proxy_settings: ProxySettings = {
            "server": config.proxy_host
        }
        br_profile = BrowserProfile(
            # cannot config proxy settings in headless mode
            headless=False,
            proxy=proxy_settings,
            # Using user_data_dir=None ensures a clean, temporary profile for the test.
            user_data_dir=None,
            minimum_wait_page_load_time=10,
            maximum_wait_page_load_time=60,
            window_size=ViewportSize(width=screen_width, height=screen_height),
            stealth=True
        )
        browser_session = BrowserSession(
            browser_profile=br_profile,
        )        
    else:
        browser_session = BrowserSession(
            browser_profile=BrowserProfile(
                headless=config.headless,
                minimum_wait_page_load_time=30,
                maximum_wait_page_load_time=60,
                window_size=ViewportSize(width=screen_width, height=screen_height),
                stealth=True,
            )
        )
    if config.real_browser:
        browser_session.browser_profile.executable_path = "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe"
        print("Using real browser for testing.")

    task = config.task
    output_schema = AgentStructuredOutput
    controller = Controller(output_model=output_schema)


    @controller.action("Compare 2 images and return a confidence score.")
    async def check_img_similarity(img1_path: str, img2_path: str, size_tolerance: float = 0.05) -> ActionResult:
        try:
            MAX_HEIGHT_DIMENSION = 16384
            print(f"Comparing images: {img1_path} and {img2_path}")
            if img1_path == img2_path:
                return ActionResult(error="Image paths must be different. Same img?")
            
            img1 = Image.open(img1_path).convert("RGB")
            img2 = Image.open(img2_path).convert("RGB")
            if img1.height > MAX_HEIGHT_DIMENSION:
                img1 = img1.crop((0, 0, img1.width, MAX_HEIGHT_DIMENSION))
                img1.save(img1_path)
            if img2.height > MAX_HEIGHT_DIMENSION:
                img2 = img2.crop((0, 0, img2.width, MAX_HEIGHT_DIMENSION))
                img2.save(img2_path)
            if img1.size != img2.size:
                print("Images are in different sizes. Resizing")
                area1 = img1.width * img1.height
                area2 = img2.width * img2.height
                if area1 == 0 or area2 == 0:
                    return ActionResult(error="One of the images has zero area and cannot be compared.")
                area_diff_ratio = abs(area1 - area2) / max(area1, area2)
                if area_diff_ratio > size_tolerance:
                    message = (f"Images have a size difference of {area_diff_ratio:.2%}, "
                               f"which is larger than the tolerance of {size_tolerance:.2%}.")
                    return ActionResult(extracted_content=message, long_term_memory=message)
                if area1 < area2:
                    img2 = img2.resize(img1.size, Image.Resampling.LANCZOS)
                else:
                    img1 = img1.resize(img2.size, Image.Resampling.LANCZOS)
            arr1 = np.array(img1).astype(np.float32)
            arr2 = np.array(img2).astype(np.float32)
            mse = np.mean((arr1 - arr2) ** 2)
            max_pixel_val = 255.0
            confidence = 1 - (mse / (max_pixel_val ** 2))
            confidence = max(0.0, min(1.0, float(confidence)))
            if confidence > 0.95:
                message = f"Two images are similar with {confidence:.3f} confidence score."
            else:
                message = f"The two images are not similar, with a confidence score of {confidence:.3f}."
            return ActionResult(extracted_content=message, long_term_memory=message)
        except FileNotFoundError as e:
            return ActionResult(error=f"Failed to compare images: File not found - {e.filename}")
        except Exception as e:
            return ActionResult(error=f"Failed to compare 2 images: {e}")

    @controller.action("Find a file in the current directory by name and return its path.")
    async def find_file(name: str) -> ActionResult:
        try:
            curent_dir = os.path.dirname(os.path.abspath(__file__))
            file_path = os.path.join(curent_dir, name)
            if not os.path.exists(file_path):
                return ActionResult(error=f"File {name} not found in the current directory: {curent_dir}")
            print(f"File {name} found at: {file_path}")
            return ActionResult(extracted_content=f"File {name} found at {file_path}",)
        except Exception as e:
            return ActionResult(error=f"Failed to find file {name}: {e}")
    
    @controller.action("Wait for a file to exist in the current directory, with a timeout.")
    async def wait_for_file(file_name: str, timeout: int = 120) -> ActionResult:
        """
        Waits for a specific file to appear in the current directory.

        Args:
            file_name: The name of the file to wait for.
            timeout: The maximum time to wait in seconds.

        Returns:
            An ActionResult indicating success or timeout.
        """
        try:
            curent_dir = os.path.dirname(os.path.abspath(__file__))
            file_path = os.path.join(curent_dir, file_name)
            
            start_time = time.time()
            print(f"Waiting for file '{file_name}' to be created (timeout: {timeout}s)...")
            while not os.path.exists(file_path):
                if time.time() - start_time > timeout:
                    error_message = f"Timeout: File '{file_name}' was not found within {timeout} seconds in directory {curent_dir}."
                    print(error_message)
                    return ActionResult(error=error_message)
                await asyncio.sleep(2)  # Poll every 2 seconds
            success_message = f"File '{file_name}' found at {file_path}."
            print(success_message)
            return ActionResult(extracted_content=success_message, long_term_memory=success_message)
        except Exception as e:
            return ActionResult(error=f"An error occurred while waiting for file '{file_name}': {e}")

    @controller.action("Takes a screenshot of the current page and saves it to a file.")
    async def capture_and_save_screen(
        browser_session: BrowserSession, file_name: str, full_page: bool = False) -> ActionResult:

        try:
            file_path = os.path.join(os.path.curdir, file_name)
            page = await browser_session.get_current_page()
            await browser_session.remove_highlights()
            await page.evaluate("window.scrollTo(0, 0)")
            screenshot_bytes = await page.screenshot(full_page=full_page, animations="disabled")
            with Image.open(io.BytesIO(screenshot_bytes)) as img:
                img.convert("RGB").save(file_path)
            return ActionResult(extracted_content=f"Screenshot saved to {file_name}",
                                long_term_memory=f"Screenshot saved to {file_path}",)
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
    
    llm = ChatGoogle(api_key=config.llm_api_key, model=config.llm_model if config.llm_model else "gemini-2.5-flash", temperature=0.5)
    page_extraction_llm = ChatGoogle(api_key=config.llm_api_key, model="gemini-2.5-flash", temperature=0)
    agent = Agent(
                    task=task,
                    llm=llm,
                    page_extraction_llm=page_extraction_llm,
                    flash_mode=True,
                    use_thinking=True,
                    browser_session=browser_session,
                    controller=controller,
                    calculate_cost=True,
                    max_actions_per_step=config.max_actions_per_step if config.max_actions_per_step else signature.parameters['max_actions_per_step'].default,
                    validate_output=True,
                )
    return agent
 
def run_agent_worker(work_item):
    test, args, agent_type = work_item
    async def async_run_single_agent():
        params = test['TestParams']
        params['TestName'] = test['TestName']
        params.update(args)

        important_note = \
            '\n\n **Important**:\n' + \
            '1. Follow strictly the order of steps in the test case.\n' + \
            '2. If a click action failed, retry by sending key if possible, else by evaluating and clicking on nearby elements \n' \
            '3. If the evaluation at the end of the test case fails, retry from the failed step. Max retry is 1\n'

        agent_result = None
        agent = None

        try:
            if agent_type == 'PXY':
                steps_dict = test['TestStepsPXY']
                steps_string = \
                    'Execute the test cases with the following steps:\n' + \
                    '\n'.join(key + ': ' + value for key, value in steps_dict.items()).format(**params) + \
                    important_note
                
                test_run_config = TestRunConfig(
                    proxy_username=params['proxy_username'],
                    proxy_pwd=params['proxy_password'],
                    proxy_host=params['proxy_url'],
                    llm_api_key=GEMINI_API_KEY,
                    llm_model="gemini-2.5-flash",
                    task=steps_string,
                    use_proxy=True,
                    real_browser=params.get('use_real_browser', False),
                    headless=params.get('headless', False),
                    max_actions_per_step=params.get('apt'),
                )
                agent = await create_test_run_agent(test_run_config)

            elif agent_type == 'NO_PXY':
                steps_dict = test.get('TestSteps')
                if not steps_dict:
                    return (test['TestName'], agent_type, None)

                steps_string = \
                    'Execute the test cases with the following steps:\n' + \
                    '\n'.join(key + ': ' + value for key, value in steps_dict.items()).format(**params) + \
                    important_note

                test_run_config = TestRunConfig(
                    llm_api_key=GEMINI_API_KEY_2,
                    llm_model="gemini-2.5-flash",
                    task=steps_string,
                    real_browser=params.get('use_real_browser', False),
                    headless=params.get('headless', False),
                    max_actions_per_step=params.get('apt'),
                )
                agent = await create_test_run_agent(test_run_config)
            
            else:
                raise ValueError(f"Unknown agent_type: {agent_type}")

            await agent.run()
            agent_result = generate_result(agent)

        finally:
            if agent:
                print(f"Closing browser agent for test {test['TestID']}, type {agent_type}...")
                await agent.close()
        
        return (test['TestName'], agent_type, agent_result)

    try:
        print(f"--- Running agent: TestID {test['TestID']} - {test['TestName']} - Type {agent_type} ---")
        result = asyncio.run(async_run_single_agent())
        print(f"--- Finished agent: TestID {test['TestID']} - {test['TestName']} - Type {agent_type} ---")
        return result
    except Exception as e:
        print(f"An error occurred in agent worker for TestID {test.get('TestID')}, Type {agent_type}: {e}")
        return (test.get('TestName', 'Unknown'), agent_type, None)

# Wrapper function to execute the worker and put the result in the queue
def worker_wrapper(work_item, queue):
    result = run_agent_worker(work_item)
    queue.put(result)

def main():
    try:
        tests = load_test_from_yaml('test_scripts.yaml')
        if args['test_id']:
            tests = [
                test for test in tests if str(test['TestID']) == str(args['test_id'])
            ]
            if not tests:
                print(f"No test found with ID: {args['test_id']}")
                return
        
        for test in tests:
            print(f"\n{'='*20} Starting Test: {test['TestName']} (ID: {test['TestID']}) {'='*20}")
            
            work_items = []
            if 'TestStepsPXY' in test:
                work_items.append((test, args, 'PXY'))
            if test.get('TestSteps'):
                work_items.append((test, args, 'NO_PXY'))

            if not work_items:
                print(f"No steps found for test {test['TestName']}. Skipping.")
                continue

            num_processes = len(work_items)
            print(f"Running {num_processes} agents in parallel for test '{test['TestName']}'...")

            # Use a queue to collect results from the parallel processes
            result_queue = multiprocessing.Queue()

            # Create and start a process for each agent
            processes = [multiprocessing.Process(target=worker_wrapper, args=(item, result_queue)) for item in work_items]
            for p in processes:
                p.start()

            # Retrieve results from the queue
            results = [result_queue.get() for _ in work_items]

            # Wait for all processes to complete
            for p in processes:
                p.join()

            final_result = {
                "COST": .0,
                "TOKENS": 0,
                "CONFIDENCE_SCORE": .0,
            }
            test_name = test['TestName']

            for item in results:
                if item is None: 
                    continue
                
                _, agent_type, agent_run_result = item
                
                if agent_run_result:
                    final_result[agent_type] = agent_run_result
                    final_result["COST"] += agent_run_result.get("TotalCost", 0)
                    final_result["TOKENS"] += agent_run_result.get("TotalTokens", 0)
                    if agent_type == 'PXY':
                        final_result["CONFIDENCE_SCORE"] = agent_run_result.get("confidence", 0.0)
            
            if final_result and (final_result.get("PXY") or final_result.get("NO_PXY")):
                file_path = f"{test_name}_final_result.json"
                with open(file_path, "w") as f:
                    json.dump(final_result, f, indent=4)
                print(f"✅ Successfully wrote aggregated results to {file_path}")
            else:
                print(f"⚠️ No final result generated for {test_name}, skipping file write.")
            
            print(f"{'='*20} Finished Test: {test['TestName']} (ID: {test['TestID']}) {'='*20}")

        print("\nAll tests have been executed.")

    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()