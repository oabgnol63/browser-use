import os
import time
import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.remote.command import Command
from selenium.common.exceptions import WebDriverException, TimeoutException
from typing import Optional
import dotenv

dotenv.load_dotenv()

SAUCELABS_USERNAME = os.getenv("SAUCELABS_USERNAME")
SAUCELABS_PRIVATEKEY = os.getenv("SAUCELABS_PRIVATEKEY")


class SauceLabsSeleniumClient:
    """
    A Selenium client that can attach to an existing SauceLabs browser session
    created by saucelabs_session_creation function.
    """
    
    def __init__(self, session_id: str, hub_url: Optional[str] = None):
        """
        Initialize the Selenium client with an existing session ID.
        
        Args:
            session_id: The session ID from SauceLabs
            hub_url: The hub URL (optional, will use default if not provided)
        """
        self.session_id = session_id
        self.hub_url = hub_url or f"https://{SAUCELABS_USERNAME}:{SAUCELABS_PRIVATEKEY}@ondemand.us-west-1.saucelabs.com:443/wd/hub"
        self.driver: Optional[WebDriver] = None
        
    def attach_to_session(self) -> WebDriver:
        """
        Attach to the existing browser session using Selenium WebDriver.
        
        Returns:
            WebDriver: The attached Selenium WebDriver instance
        """
        print(f"🔗 Attaching Selenium client to session: {self.session_id}")
        
        try:
            # Create a new WebDriver instance that will attach to existing session
            self.driver = AttachedWebDriver(
                command_executor=self.hub_url,
                session_id=self.session_id
            )
            
            # Test the connection by getting current URL
            current_url = self.driver.current_url
            print(f"✅ Successfully attached to session. Current URL: {current_url}")
            
            return self.driver
            
        except Exception as e:
            print(f"❌ Failed to attach to session: {e}")
            raise
    
    def navigate_to(self, url: str) -> None:
        """Navigate to a specific URL."""
        if not self.driver:
            raise RuntimeError("Driver not attached. Call attach_to_session() first.")
        
        print(f"🌐 Navigating to: {url}")
        self.driver.get(url)
        
    def find_element_by_xpath(self, xpath: str, timeout: int = 10):
        """Find element by XPath with wait."""
        if not self.driver:
            raise RuntimeError("Driver not attached. Call attach_to_session() first.")
        
        wait = WebDriverWait(self.driver, timeout)
        return wait.until(EC.presence_of_element_located((By.XPATH, xpath)))
    
    def find_element_by_id(self, element_id: str, timeout: int = 10):
        """Find element by ID with wait."""
        if not self.driver:
            raise RuntimeError("Driver not attached. Call attach_to_session() first.")
        
        wait = WebDriverWait(self.driver, timeout)
        return wait.until(EC.presence_of_element_located((By.ID, element_id)))
    
    def click_element(self, xpath: str, timeout: int = 10) -> None:
        """Click an element by XPath."""
        element = self.find_element_by_xpath(xpath, timeout)
        element.click()
        print(f"🖱️ Clicked element: {xpath}")
    
    def type_text(self, xpath: str, text: str, timeout: int = 10) -> None:
        """Type text into an element."""
        element = self.find_element_by_xpath(xpath, timeout)
        element.clear()
        element.send_keys(text)
        print(f"⌨️ Typed text into element: {xpath}")
    
    def get_page_title(self) -> str:
        """Get the current page title."""
        if not self.driver:
            raise RuntimeError("Driver not attached. Call attach_to_session() first.")
        
        return self.driver.title
    
    def get_current_url(self) -> str:
        """Get the current URL."""
        if not self.driver:
            raise RuntimeError("Driver not attached. Call attach_to_session() first.")
        
        return self.driver.current_url
    
    def execute_javascript(self, script: str):
        """Execute JavaScript in the browser."""
        if not self.driver:
            raise RuntimeError("Driver not attached. Call attach_to_session() first.")
        
        return self.driver.execute_script(script)
    
    def take_screenshot(self, filename: Optional[str] = None) -> str:
        """Take a screenshot and save it."""
        if not self.driver:
            raise RuntimeError("Driver not attached. Call attach_to_session() first.")
        
        if not filename:
            filename = f"screenshot_{int(time.time())}.png"
        
        self.driver.save_screenshot(filename)
        print(f"📸 Screenshot saved: {filename}")
        return filename
    
    def wait_for_element(self, xpath: str, timeout: int = 10):
        """Wait for an element to be present."""
        return self.find_element_by_xpath(xpath, timeout)
    
    def quit(self):
        """Close the driver connection (but don't close the browser session)."""
        if self.driver:
            try:
                self.driver.quit()
                print("🔌 Selenium client disconnected")
            except:
                pass
            self.driver = None


class AttachedWebDriver(webdriver.Remote):
    """
    A custom WebDriver class that attaches to an existing session
    instead of creating a new one.
    """
    
    def __init__(self, command_executor: str, session_id: str):
        """
        Initialize the driver with an existing session.
        
        Args:
            command_executor: The hub URL
            session_id: The existing session ID to attach to
        """
        # Create minimal Chrome options for Selenium 4.x compatibility
        chrome_options = Options()
        
        # Initialize the parent class without starting a new session
        super().__init__(command_executor=command_executor, options=chrome_options)
        
        # Override the session_id with the existing one
        self.session_id = session_id
        
        # Test the connection
        try:
            # Try to get current URL to verify the session is active
            self.current_url
        except WebDriverException as e:
            raise RuntimeError(f"Failed to attach to session {session_id}: {e}")
    
    def start_session(self, capabilities=None, browser_profile=None):
        """Override to prevent creating a new session."""
        # Don't create a new session, we're attaching to an existing one
        pass


def extract_session_id_from_cdp_url(cdp_url: str) -> str:
    """
    Extract session ID from CDP URL.
    
    Args:
        cdp_url: CDP WebSocket URL from SauceLabs
        
    Returns:
        str: Extracted session ID, or empty string if extraction fails
    """
    try:
        # CDP URL format: wss://ondemand.us-west-1.saucelabs.com/cdp/SESSION_ID
        # or wss://ws.us-west-4-i3er.saucelabs.com/selenium/session/SESSION_ID/se/cdp
        
        if '/cdp/' in cdp_url:
            # Format: .../cdp/SESSION_ID
            session_id = cdp_url.split('/cdp/')[-1]
        elif '/session/' in cdp_url and '/se/cdp' in cdp_url:
            # Format: .../session/SESSION_ID/se/cdp
            parts = cdp_url.split('/session/')[-1]
            session_id = parts.split('/se/cdp')[0]
        else:
            print(f"⚠️ Unknown CDP URL format: {cdp_url}")
            return ""
            
        print(f"📋 Extracted session ID: {session_id}")
        return session_id
        
    except Exception as e:
        print(f"❌ Error extracting session ID from CDP URL: {e}")
        return ""


def create_selenium_client_from_cdp_url(cdp_url: str) -> SauceLabsSeleniumClient:
    """
    Create a Selenium client from a CDP URL.
    
    Args:
        cdp_url: The CDP URL returned by saucelabs_session_creation
        
    Returns:
        SauceLabsSeleniumClient: Configured Selenium client
    """
    session_id = extract_session_id_from_cdp_url(cdp_url)
    if not session_id:
        raise ValueError("Could not extract session ID from CDP URL")
    
    return SauceLabsSeleniumClient(session_id)


# Example usage and testing
if __name__ == "__main__":
    # This is just for testing - in practice you'd get the CDP URL from saucelabs_session_creation
    
    # Example CDP URL (replace with actual one from your session)
    # cdp_url = "wss://ondemand.us-west-1.saucelabs.com/cdp/your-session-id-here"
    
    print("🧪 Selenium Client Demo")
    print("=" * 40)
    print("To use this client:")
    print("1. Create a session with saucelabs_session_creation()")
    print("2. Use create_selenium_client_from_cdp_url(cdp_url)")
    print("3. Call attach_to_session() to connect")
    print("4. Use standard Selenium operations")
    
    # Example of how to use:
    """
    from sauce_manager import saucelabs_session_creation
    from browser_use.browser.profile import CloudBrowserProfile
    
    # Create session
    profile = CloudBrowserProfile(browser_name='chrome', browser_version='latest', platform_name='Windows 10')
    cdp_url = saucelabs_session_creation(profile)
    
    # Create Selenium client
    selenium_client = create_selenium_client_from_cdp_url(cdp_url)
    driver = selenium_client.attach_to_session()
    
    # Use Selenium operations
    selenium_client.navigate_to("https://www.google.com")
    title = selenium_client.get_page_title()
    print(f"Page title: {title}")
    
    # Take screenshot
    selenium_client.take_screenshot("google_homepage.png")
    
    # Clean up
    selenium_client.quit()
    """
