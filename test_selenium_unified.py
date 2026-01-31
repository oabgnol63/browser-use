"""
Verification test for unified Agent with SeleniumBrowserSession.
"""

import asyncio
import logging
import os
from dotenv import load_dotenv

os.environ["BROWSER_USE_LOGGING_LEVEL"] = "debug"
os.environ["BROWSER_USE_CLOUD_SYNC"] = "false"
os.environ["TIMEOUT_NavigateToUrlEvent"] = "60"
load_dotenv()

from browser_use.selenium import SeleniumSession
from browser_use.browser.selenium_session import SeleniumBrowserSession
from browser_use.agent.service import Agent
from browser_use import ChatOpenAI


async def main():
    # 1. Start a local Selenium session (Firefox)
    print("Starting Firefox via Selenium...")
    selenium_session = await SeleniumSession.new_local_session(
        browser='firefox',
        headless=False
    )
    
    # 2. Wrap it in the event-driven SeleniumBrowserSession
    browser_session = SeleniumBrowserSession(selenium_session=selenium_session)
    
    try:
        # 3. Start the browser session (this initializes event handlers)
        print("Starting browser session...")
        await browser_session.start()
        
        # 4. Create the standard Agent using the Selenium-backed session
        llm = ChatOpenAI(
            model="gemini-3-flash-preview",
            base_url="http://localhost:8899/v1",
            api_key="your-api-key-1",
            temperature=0.0,
            add_schema_to_system_prompt=True,  # Include JSON schema in prompt for proxy compatibility
            dont_force_structured_output=True,
            remove_min_items_from_schema=True,
            remove_defaults_from_schema=True,
        )
        task = """
Go to cnn.com.
Locate More Top Stories header on homepage. If scroll is needed, scroll one page each.
Click on the first article link under this header.
Navigate back to homepage.
Navigate forward to the article page.
"""
        agent = Agent(
            task=task,
            llm=llm,
            browser_session=browser_session,
            # flash_mode=True
        )
        
        # 5. Run the agent!
        print("Running unified agent...")
        
        result = await agent.run()
        
        print("\nAGENT RESULT:")
        print(result)
        
    finally:
        # Close the Selenium session
        await selenium_session.close()
        print("Done.")

if __name__ == "__main__":
    asyncio.run(main())
