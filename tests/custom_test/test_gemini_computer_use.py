import asyncio
import os

from dotenv import load_dotenv

load_dotenv()
os.environ['BROWSER_USE_LOGGING_LEVEL'] = 'debug'
os.environ['BROWSER_USE_CLOUD_SYNC'] = 'false'
os.environ['TIMEOUT_NavigationCompleteEvent'] = '60'
os.environ['TIMEOUT_ScreenshotEvent'] = '30'
os.environ['BROWSER_USE_PRINT_LLM_MESSAGES'] = 'true'  # print full LLM input each step


from browser_use import Browser, BrowserProfile
from browser_use.agent.service import Agent
from browser_use.llm.google.chat import ChatGoogle


async def main():
    # Make sure you have your API key set
    # os.environ["GEMINI_API_KEY"] = "your-api-key"
    
    browser = Browser(
        browser_profile=BrowserProfile(
            headless=False,  # Set to False so we can watch it interact
            minimum_wait_page_load_time=5,
        )
    )
    
    # Use a model that supports computer use (e.g., gemini-3-flash-preview)
    # The computer-use feature requires a compatible Gemini model and API key.
    llm = ChatGoogle(model="gemini-3-flash-preview")

    agent = Agent(
        task="Go to https://cnn.com. Click on the hamburger menu button. Search Football. Click the first result. Scroll down 5 pages. Scroll up 2 pages. Go back.",
        llm=llm,
        browser=browser,
        use_native_computer_use=True, # Enable our new mode
    )

    print("Starting agent with Gemini Computer Use...")
    result = await agent.run() 
    
    print("\nResult:")
    print(result)

if __name__ == '__main__':
    asyncio.run(main())

