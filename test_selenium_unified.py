"""
Verification test for unified Agent with SeleniumBrowserSession.
"""

import asyncio
import logging
import os
from dotenv import load_dotenv

os.environ["BROWSER_USE_LOGGING_LEVEL"] = "debug"
os.environ["BROWSER_USE_CLOUD_SYNC"] = "false"
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
            model="qwen3-vl-plus",
            base_url="http://localhost:8899/v1",
            api_key="your-api-key-1",
            temperature=0.0,
            add_schema_to_system_prompt=True,  # Include JSON schema in prompt for proxy compatibility
            dont_force_structured_output=True,
            remove_min_items_from_schema=True,
            remove_defaults_from_schema=True,
        )
        
        agent = Agent(
            task="Go to https://google.com and search for 'browser-use github'. Tell me the first result title.",
            llm=llm,
            browser_session=browser_session
        )
        
        # 5. Run the agent!
        print("Running unified agent...")
        
        # Test basic JS execution first
        print("Testing basic JS execution...")
        test_result = selenium_session.driver.execute_script("return {test: 'hello', value: 42};")
        print(f"Basic JS test result: {test_result}")
        
        # Test the IIFE pattern with the actual DOM extraction code
        print("Testing IIFE pattern with DOM extraction code...")
        from importlib.resources import files as resources_files
        raw_js_code = resources_files('browser_use.dom').joinpath('dom_tree_js', 'index.js').read_text(encoding='utf-8').strip()
        if raw_js_code.startswith('﻿'):
            raw_js_code = raw_js_code[1:]
        if raw_js_code.endswith(';'):
            raw_js_code = raw_js_code[:-1]

        # Test the IIFE pattern
        test_args = {'doHighlightElements': True, 'focusHighlightIndex': -1, 'viewportExpansion': 0, 'debugMode': True}
        iife_result = selenium_session.driver.execute_script(f"return ({raw_js_code})(arguments[0])", test_args)
        print(f"IIFE result type: {type(iife_result)}")
        if iife_result:
            print(f"IIFE result keys: {list(iife_result.keys()) if isinstance(iife_result, dict) else 'not-a-dict'}")
        else:
            print("IIFE returned None - check browser console for errors!")

        # First, navigate to Google to ensure page is loaded
        print("\n--- Navigating to Google ---")
        try:
            await browser_session.navigate_to_url("https://google.com")
            print(f"After navigate - URL: {selenium_session.driver.current_url}")
        except Exception as e:
            print(f"Navigation error: {e}")
            # Try direct navigation via selenium driver
            print("Trying direct driver navigation...")
            selenium_session.driver.get("https://google.com")
            print(f"After direct get - URL: {selenium_session.driver.current_url}")
        
        # Wait a bit for page to load
        import time
        print("Waiting for page to load...")
        time.sleep(3)
        
        # Check page state after navigation
        print(f"\n--- Page State After Navigation ---")
        print(f"Current URL: {selenium_session.driver.current_url}")
        print(f"Page title: {selenium_session.driver.title}")
        
        # Check for common interactive elements
        search_box = selenium_session.driver.execute_script("return document.querySelector('input[name=\"q\"]') !== null")
        print(f"Google search box exists: {search_box}")
        
        # Now test via the actual DOM service to compare
        print("\n--- Testing via SeleniumDomService ---")
        dom_service = selenium_session.dom_service
        enhanced_dom_tree, selector_map, timing = await dom_service.get_dom_tree()
        print(f"DOM tree result: root_node={enhanced_dom_tree.node_name}, selector_map_size={len(selector_map)}")
        
        # Debug: Check what's in the DOM result
        if selector_map:
            print(f"Selector map has {len(selector_map)} entries:")
            for idx, node in list(selector_map.items())[:5]:
                print(f"  Index {idx}: {node.tag_name if hasattr(node, 'tag_name') else node.node_name}")
        else:
            print("WARNING: Selector map is empty!")
        
        # Debug: Check JS result directly
        print("\n--- Direct JS Result Debug ---")
        from importlib.resources import files as resources_files
        raw_js_code = resources_files('browser_use.dom').joinpath('dom_tree_js', 'index.js').read_text(encoding='utf-8').strip()
        if raw_js_code.startswith('﻿'):
            raw_js_code = raw_js_code[1:]
        if raw_js_code.endswith(';'):
            raw_js_code = raw_js_code[:-1]
        
        test_args = {'doHighlightElements': True, 'focusHighlightIndex': -1, 'viewportExpansion': 0, 'debugMode': True}
        js_result = selenium_session.driver.execute_script(f"return ({raw_js_code})(arguments[0])", test_args)
        
        if js_result and isinstance(js_result, dict):
            js_map = js_result.get('map', {})
            print(f"JS map has {len(js_map)} total nodes")
            
            # Count how many have highlightIndex
            nodes_with_index = {k: v for k, v in js_map.items() if isinstance(v, dict) and v.get('highlightIndex') is not None}
            print(f"Nodes with highlightIndex: {len(nodes_with_index)}")
            
            # Sample nodes
            print("\nSample nodes:")
            for node_id, node_data in list(js_map.items())[:5]:
                if isinstance(node_data, dict):
                    print(f"  Node {node_id}: tag={node_data.get('tagName')}, isInteractive={node_data.get('isInteractive')}, highlightIndex={node_data.get('highlightIndex')}")
        else:
            print("JS result is None or not a dict!")
        
        result = await agent.run(max_steps=10)
        
        print("\nAGENT RESULT:")
        print(result)
        
    finally:
        # Close the Selenium session
        await selenium_session.close()
        print("Done.")

if __name__ == "__main__":
    asyncio.run(main())
