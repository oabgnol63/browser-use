import os
import asyncio
import sys
import argparse
import yaml
import time
import json
import io
import inspect
import functools
import tkinter as tk
import numpy as np
import cv2
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

if not os.getenv('TEST_FILE'):
    raise ValueError('TEST_FILE is not set. Please add it to your environment variables.')
TEST_FILE = os.getenv('TEST_FILE')
RESULT_FOLDER = os.path.join(os.getcwd(), 'TestResults')
os.makedirs(RESULT_FOLDER, exist_ok=True)

parser = argparse.ArgumentParser(description="Run browser tests with optional proxy.")
parser.add_argument('--proxy_url', action='store', required=True, help="(Required) Use proxy settings for the tests.")
parser.add_argument('--proxy_username', action='store', required=True, help="Proxy username for authentication.")
parser.add_argument('--proxy_password', action='store', required=True, help="Proxy password for authentication.")
parser.add_argument('--test_id', action='store', required=False, help="ID of the test to run, or all tests will be executed.")
parser.add_argument('--use_real_browser', action='store', required=False, choices=['msedge', 'chrome'], help="Use real browser for testing.")
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
    describe: list[tuple] = Field(description="a list of tuples (step actions summary, result in details)")
    screenshot_path: str = Field(description="Absolute path to the screenshot captured")
    similarity_score: list[tuple] = Field(description="a list of tuples (image 1, image 2, similarity score of their comparison)")

@dataclass
class TestRunConfig:
    task: str
    result_folder: str = RESULT_FOLDER
    max_actions_per_step: int = 3
    real_browser: Optional[str] = None
    proxy_host: Optional[str] = None
    proxy_username: Optional[str] = None
    proxy_pwd: Optional[str] = None
    llm_api_key: Optional[str] = None
    llm_model: str = "gemini-2.5-flash"
    use_proxy: bool = False
    headless: bool = False


def load_test_from_yaml(file_path: str):
    with open(file_path, "r") as file:
        test_data = yaml.safe_load(file)
    return test_data['tests']

def detect_screen_size():
    """
    Detects the screen size of the primary monitor.
    Returns a tuple (width, height).
    """
    root = tk.Tk()
    root.withdraw()
    screen_width = root.winfo_screenwidth()
    screen_height = root.winfo_screenheight()
    root.destroy()
    return screen_width, screen_height

windows_width, windows_height = detect_screen_size()
print(f"Detected screen size: {windows_width}x{windows_height}")

def generate_result(agent: Agent) -> Optional[Dict]:
    agent_result = agent.history.final_result()
    if agent_result:
        agent_result = json.loads(agent_result)
        agent_result["ExecutionTime"] = agent.history.total_duration_seconds()
        agent_result["AISteps"] = agent.history.number_of_steps()
        if agent.history.usage:
            agent_result["TotalCost"] = agent.history.usage.total_cost
            agent_result["TotalTokens"] = agent.history.usage.total_tokens
        else:
            agent_result["TotalCost"] = 0
            agent_result["TotalTokens"] = 0
        return agent_result
    return None

 
async def create_test_run_agent(config: TestRunConfig) -> Agent:
    if config.real_browser:
        if config.real_browser == 'msedge':
            browser_executable_path = "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe"
        elif config.real_browser == 'chrome':
            browser_executable_path = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe"
        else:
            pass
    else:
        browser_executable_path = None  

    bf_profile = BrowserProfile(
        headless=False, # cannot config proxy settings in headless mode
        user_data_dir=None, # Using a temporary profile (None) is best practice for isolated tests.
        minimum_wait_page_load_time=7,
        maximum_wait_page_load_time=10,
        wait_for_network_idle_page_load_time=1.5,
        default_navigation_timeout=30000,
        window_size=ViewportSize(width=windows_width, height=windows_height-50),
        executable_path=browser_executable_path,
    )
    if config.use_proxy and config.proxy_host:
        proxy_settings: ProxySettings = {
            "server": config.proxy_host
        }
        bf_profile.proxy = proxy_settings
        bf_profile.wait_for_network_idle_page_load_time = 5 # overwrite for pxy browser
       
    browser_session = BrowserSession(
        browser_profile=bf_profile,
    )
    task = config.task
    output_schema = AgentStructuredOutput
    controller = Controller(output_model=output_schema)


    @controller.action("Compare 2 images and return a similarity score. Scores of at least 0.7 are considered similar.")
    async def check_img_similarity(img1_path: str, img2_path: str) -> ActionResult:
        """
        Compares two images for visual similarity using the ORB feature matching algorithm.

        This function is designed to be robust against changes in image size and minor 
        content shifts (e.g., due to dynamic ads on a webpage screenshot). It returns
        a similarity score between 0.0 (completely different) and 1.0 (very similar).

        Args:
            img1_path (str): Filesystem path to the first image.
            img2_path (str): Filesystem path to the second image.
            max_width (int): The width to which large images are resized for efficient 
                            processing. Maintains aspect ratio.
            n_features (int): The maximum number of features to detect with ORB.
            lowe_ratio_thresh (float): The threshold for Lowe's ratio test to filter
                                    for high-quality matches.
            min_good_matches (int): The minimum number of good matches required to even
                                    consider the images potentially similar.
            distance_threshold (float): The average match distance that corresponds to
                                        a high similarity. Used to normalize the score.

        Returns:
            ActionResult: A similarity score between 0.0 and 1.0.
        """
        try:
            max_width: int = 1200
            n_features: int = 3000
            lowe_ratio_thresh: float = 0.6
            min_good_matches: int = 20
            distance_threshold: float = 30.0

            if not os.path.exists(img1_path) or not os.path.exists(img2_path):
                # force it to look in the result folder
                print(f"Debugging: img1_path={img1_path}, img2_path={img2_path}")
                img1_path = config.result_folder + '/' + os.path.basename(img1_path)
                img2_path = config.result_folder + '/' + os.path.basename(img2_path)
                if not os.path.exists(img1_path) or not os.path.exists(img2_path):
                    raise FileNotFoundError(f"One or both image files do not exist: {img1_path}, {img2_path}")

            if img1_path == img2_path:
                raise ValueError("Image paths must be different. Same img?")
            
            def resize_for_processing(img):
                h, w = img.shape[:2]
                if w > max_width:
                    ratio = max_width / w
                    new_height = int(h * ratio)
                    return cv2.resize(img, (max_width, new_height), interpolation=cv2.INTER_AREA)
                return img

            def _compare_sync(path1: str, path2: str) -> str:
                img1_name = os.path.basename(path1)
                img2_name = os.path.basename(path2)
                print(f"Comparing images: {path1} and {path2}")
                # Load images
                img1_full = cv2.imread(path1, cv2.IMREAD_GRAYSCALE)
                img2_full = cv2.imread(path2, cv2.IMREAD_GRAYSCALE)
                img1 = resize_for_processing(img1_full)
                img2 = resize_for_processing(img2_full)

                # Initiate ORB detector
                orb = cv2.ORB.create(nfeatures=n_features)

                # Find the keypoints and descriptors with ORB
                kp1, des1 = orb.detectAndCompute(img1, None) # type: ignore
                kp2, des2 = orb.detectAndCompute(img2, None) # type: ignore
                if des1 is None or des2 is None or len(des1) < 2 or len(des2) < 2:
                    raise ValueError("Not enough features found in one or both images to compare.")
                
                # Match Features using Brute-Force Matcher
                bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)

                # Use knnMatch to get k=2 best matches for Lowe's ratio test
                all_matches = bf.knnMatch(des1, des2, k=2)
                good_matches = []
                try:
                    for m, n in all_matches:
                        if m.distance < lowe_ratio_thresh * n.distance:
                            good_matches.append(m)
                except ValueError:
                    # This can happen if not enough matches are found to unpack
                    raise ValueError("Not enough matches found to apply Lowe's ratio test.")
                if len(good_matches) > min_good_matches:
                    print(f"Found {len(good_matches)} good matches between the images.")
                    # Calculate the average distance of only the good matches
                    average_distance = np.mean([m.distance for m in good_matches])

                    # Normalize the score based on the distance threshold.
                    # A lower distance means higher similarity.
                    similarity_score = max(0.0, float(1.0 - (average_distance / distance_threshold)))
                    if similarity_score > 0.7:
                        return f"Two images {img1_name} and {img2_name} are similar, with ORB similarity score {similarity_score:.2f}"
                    else:
                        return f"Two images {img1_name} and {img2_name} are not similar, with a ORB similarity score {similarity_score:.2f}"
                else:
                    # Not enough good matches to be considered similar
                    return f"The two images {img1_name} and {img2_name} are totaly different, with a ORB similarity score 0.0."

            loop = asyncio.get_event_loop()
            message = await loop.run_in_executor(
                None, functools.partial(_compare_sync, img1_path, img2_path)
            )
            return ActionResult(extracted_content=message, long_term_memory=message)

        except FileNotFoundError as e:
            return ActionResult(error=f"Failed to compare images: File not found - {e.filename}")
        except Exception as e:
            return ActionResult(error=f"{e}")

    @controller.action("Find a file in the current directory by name and return its path.")
    async def find_file(dir: str, name: str) -> ActionResult:
        try:
            file_path = os.path.join(dir, name)
            if not os.path.exists(file_path):
                return ActionResult(error=f"File {name} not found in the current directory: {dir}")
            print(f"File {name} found at: {file_path}")
            return ActionResult(extracted_content=f"File {name} found at {file_path}",)
        except Exception as e:
            return ActionResult(error=f"Failed to find file {name}: {e}")
    
    @controller.action("Wait for a file to exist in the TestResults directory, with a timeout.")
    async def wait_for_file(file_name: str, timeout: int = 120) -> ActionResult:
        try:
            file_path = os.path.join(config.result_folder, file_name)
            start_time = time.time()
            print(f"Waiting for file '{file_name}' to be created (timeout: {timeout}s)...")
            while not os.path.exists(file_path):
                if time.time() - start_time > timeout:
                    error_message = f"Timeout: File '{file_name}' was not found within {timeout} seconds in directory {config.result_folder}."
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
            file_path = os.path.join(config.result_folder, file_name)
            page = await browser_session.get_current_page()
            await browser_session.remove_highlights()
            await page.evaluate("window.scrollTo(0, 0)")
            screenshot_bytes = await page.screenshot(full_page=full_page, animations="disabled")
            with Image.open(io.BytesIO(screenshot_bytes)) as img:
                img.convert("RGB").save(file_path)
            return ActionResult(extracted_content=f"{file_name} screenshot saved to {file_path}",
                                long_term_memory=f"{file_name} screenshot saved to {file_path}",)
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

    @controller.action("Wait for all images in the current viewport to load.")
    async def wait_for_images_loaded(browser_session: BrowserSession, timeout: float = 15.0) -> ActionResult:
        try:
            page = await browser_session.get_current_page()
            await asyncio.wait_for(
                page.evaluate("""
                    async () => {
                        // Function to check if an image is in the viewport
                        const isInViewport = (img) => {
                            const rect = img.getBoundingClientRect();
                            return (
                                rect.top >= 0 &&
                                rect.left >= 0 &&
                                rect.bottom <= (window.innerHeight || document.documentElement.clientHeight) &&
                                rect.right <= (window.innerWidth || document.documentElement.clientWidth)
                            );
                        };

                        // Filter images that are in the viewport
                        const imgs = Array.from(document.images).filter(img => isInViewport(img));

                        // Wait for all viewport images to load successfully or reject on failure
                        await Promise.all(imgs.map(img => {
                            if (img.complete) {
                                // Check if already loaded successfully
                                return img.naturalWidth > 0 && img.naturalHeight > 0
                                    ? Promise.resolve()
                                    : Promise.reject(`Image failed to load: ${img.src}`);
                            }
                            return new Promise((resolve, reject) => {
                                img.addEventListener('load', () => {
                                    if (img.naturalWidth > 0 && img.naturalHeight > 0) {
                                        resolve();
                                    } else {
                                        reject(`Image failed to load: ${img.src}`);
                                    }
                                }, { once: true });
                                img.addEventListener('error', () => {
                                    reject(`Image failed to load: ${img.src}`);
                                }, { once: true });
                            });
                        }));
                    }
                """),
                timeout=timeout
            )
            return ActionResult(extracted_content="All images in viewport loaded successfully")
        except Exception as e:
            error_msg = f"⚠️ Timeout or error waiting for images to load: {type(e).__name__}: {e}"
            print(error_msg)
            return ActionResult(error=error_msg)

    llm = ChatGoogle(api_key=config.llm_api_key, model=config.llm_model if config.llm_model else "gemini-2.5-flash", temperature=0)
    page_extraction_llm = ChatGoogle(api_key=config.llm_api_key, model="gemini-2.5-flash-lite", temperature=0)
    agent = Agent(
        task=task,
        llm=llm,
        page_extraction_llm=page_extraction_llm,
        flash_mode=True,
        browser_session=browser_session,
        controller=controller,
        calculate_cost=True,
        max_actions_per_step=config.max_actions_per_step,
        use_vision=True,
        vision_detail_level='low',
        # validate_output=True,
        llm_timeout=60,
        viewport_expansion=1,
    )
    return agent
 
async def run_agent_worker(work_item):
    test, args, agent_type = work_item

    # combine test parameters with args from cmd line
    params = test['TestParams']
    params['TestName'] = test['TestName']
    params.update(args)

    important_note = \
        '\n\n **Important**:\n' + \
        '1. Follow strictly the order of steps in the test case.\n'
        # '2. If the evaluation at the end of the test case fails, retry from the failed step. Max retry is 1\n'

    agent_result = None
    agent = None
    # create folder to save results
    sub_result_folder = os.path.join(RESULT_FOLDER, test['TestName'])
    os.makedirs(sub_result_folder, exist_ok=True)
    signature = inspect.signature(Agent.__init__)
    try:
        print(f"--- Running agent: TestID {test['TestID']} - {test['TestName']} - Type {agent_type} ---")
        if agent_type == 'PXY':
            steps_dict = test['TestStepsPXY']
            steps_string = \
                'Execute the test cases with the following steps:\n' + \
                '\n'.join(key + ': ' + value for key, value in steps_dict.items()).format(**params) + \
                important_note
            
            test_run_config = TestRunConfig(
                result_folder=sub_result_folder,
                proxy_username=params['proxy_username'],
                proxy_pwd=params['proxy_password'],
                proxy_host=params['proxy_url'],
                llm_api_key=GEMINI_API_KEY,
                llm_model="gemini-2.5-flash",
                task=steps_string,
                use_proxy=True,
                real_browser=params.get('use_real_browser', None),
                headless=params.get('headless', False),
                max_actions_per_step=params.get('apt', signature.parameters["max_actions_per_step"].default),
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
                result_folder=sub_result_folder,
                llm_api_key=GEMINI_API_KEY_2,
                llm_model="gemini-2.5-flash",
                task=steps_string,
                real_browser=params.get('use_real_browser', None),
                headless=params.get('headless', False),
                max_actions_per_step=params.get('apt', signature.parameters["max_actions_per_step"].default),
            )
            agent = await create_test_run_agent(test_run_config)
        
        else:
            raise ValueError(f"Unknown agent_type: {agent_type}")

        await agent.run()
        agent_result = generate_result(agent)

    except Exception as e:
        print(f"An error occurred in agent worker for TestID {test.get('TestID')}, Type {agent_type}: {e}")
        return (test.get('TestName', 'Unknown'), agent_type, None)
    finally:
        if agent:
            print(f"Closing browser agent for test {test['TestID']}, type {agent_type}...")
            await agent.close()
    
    result = (test['TestName'], agent_type, agent_result)
    print(f"--- Finished agent: TestID {test['TestID']} - {test['TestName']} - Type {agent_type} ---")
    return result

async def main():
    try:
        tests = load_test_from_yaml(TEST_FILE) # type: ignore
        if args['test_id']:
            tests = [
                test for test in tests if str(test['TestID']) == str(args['test_id'])
            ]
            if not tests:
                print(f"No test found with ID: {args['test_id']}")
                return
        for test in tests:
            # check if the test has a 'skip' tag
            if "skip" in test.get('Tag', []) and not args['test_id']: # ignore skip tag if test_id is provided
                print(f"Skipping test {test['TestName']} (ID: {test['TestID']}) due to 'skip' tag.")
                continue
            print(f"\n{'='*20} Starting Test: {test['TestName']} (ID: {test['TestID']}) {'='*20}")
            final_result = {
                "COST": .0,
                "TOKENS": 0,
                "SIMILARITY_SCORE": [],
            }
            test_name = test['TestName']
            work_items = []
            if 'TestStepsPXY' in test:
                work_items.append((test, args, 'PXY'))
            if test.get('TestSteps'):
                work_items.append((test, args, 'NO_PXY'))

            if not work_items:
                print(f"No steps found for test {test['TestName']}. Skipping.")
                continue

            num_agents = len(work_items)
            print(f"Running {num_agents} agents in parallel for test '{test['TestName']}'...")

            tasks = [run_agent_worker(item) for item in work_items]
            results = await asyncio.gather(*tasks)

            for item in results:
                if item is None: 
                    continue
                
                _, agent_type, agent_run_result = item
                
                if agent_run_result:
                    final_result[agent_type] = agent_run_result
                    final_result["COST"] += agent_run_result.get("TotalCost", 0)
                    final_result["TOKENS"] += agent_run_result.get("TotalTokens", 0)
                    if agent_type == 'PXY':
                        final_result["SIMILARITY_SCORE"] = agent_run_result.get("similarity_score", [])
                        if final_result["SIMILARITY_SCORE"]:
                            # we no longer need it here
                            final_result[agent_type].pop("similarity_score", None)
                    elif agent_type == 'NO_PXY':
                        final_result[agent_type].pop("similarity_score", None)
            
            if final_result and (final_result.get("PXY") or final_result.get("NO_PXY")):
                test_result_folder = os.path.join(RESULT_FOLDER, test_name)
                if not os.path.exists(test_result_folder):
                    os.makedirs(test_result_folder, exist_ok=True)
                result_file_path = os.path.join(test_result_folder, f"{test_name}_final_result.json")
                with open(result_file_path, "w") as f:
                    json.dump(final_result, f, indent=4)
                print(f"✅ Successfully wrote aggregated results to {result_file_path}")
            else:
                print(f"⚠️ No final result generated for {test_name}, skipping file write.")
            
            print(f"{'='*20} Finished Test: {test['TestName']} (ID: {test['TestID']}) {'='*20}")

        print("\nAll tests have been executed.")

    except Exception as e:
        print(f"An error occurred: {e}")


if __name__ == "__main__":
    asyncio.run(main())