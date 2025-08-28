import requests
import time
import os
import dotenv
import asyncio
import json as _json
import aiohttp

dotenv.load_dotenv()
SAUCELABS_USERNAME = os.getenv("SAUCELABS_USERNAME")
SAUCELABS_PRIVATEKEY = os.getenv("SAUCELABS_PRIVATEKEY")
PROXY_URL = os.getenv("PROXY_URL")
PROXY_USERNAME = os.getenv("PROXY_USERNAME", "msc@capp.com")
PROXY_PASSWORD = os.getenv("PROXY_PASSWORD", "Exploit99*")

from browser_use.browser.profile import CloudBrowserProfile
from browser_use.browser import ProxySettings

def saucelabs_session_creation(profile: CloudBrowserProfile) -> str:
    """Test actual SauceLabs session creation"""
    
    print("\n🌟 SauceLabs Session Creation")
    print("=" * 40)

    username = SAUCELABS_USERNAME
    access_key = SAUCELABS_PRIVATEKEY
    hub_url = f"https://{username}:{access_key}@ondemand.us-west-1.saucelabs.com:443/wd/hub"

    cloud_profile = profile
    
    capabilities = cloud_profile.to_saucelabs_capabilities()
    
    # Add test-specific sauce options
    capabilities['pageLoadStrategy'] = 'normal'
    # Merge test-specific overrides without wiping defaults from profile
    capabilities.setdefault('sauce:options', {}).update({
        'experimental': True,
        'maxDuration': 900,
        'commandTimeout': 600,
        'idleTimeout': 600,
    })

    session_id = None
    try:
        import json
        print(f"🚀 Creating SauceLabs session with CloudBrowserProfile capabilities...")
        
        # Create WebDriver session with W3C format
        session_data = {
            "capabilities": {
                "alwaysMatch": capabilities,
                "firstMatch": [{}],
            }
        }
        response = requests.post(hub_url + "/session", json=session_data, timeout=60)
        
        if response.status_code == 200:
            session_info = response.json()
            session_id = session_info["value"]["sessionId"]
            print(f"✅ SauceLabs session created: {session_id}")
            print("\n📋 Capabilities returned by SauceLabs response:")
            returned_capabilities = session_info.get("value", {}).get("capabilities", {})
            print(json.dumps(returned_capabilities, indent=2))
            
            
            # Get CDP URL from SauceLabs response (se:cdp capability)
            cdp_url_from_response = returned_capabilities.get('se:cdp')
            if cdp_url_from_response:
                print(f"🔗 CDP URL from se:cdp capability: {cdp_url_from_response}")
                cdp_url = cdp_url_from_response
            else:
                # Fallback to manual construction if se:cdp not available
                cdp_url = f"wss://ondemand.us-west-1.saucelabs.com/cdp/{session_id}"
                print(f"🔗 CDP URL (manual construction): {cdp_url}")
                print("⚠️  WARNING: se:cdp capability not found in response!")
            return cdp_url
        else:
            print(f"❌ Failed to create session: {response.status_code} - {response.text}")
            return ""
            
    except Exception as e:
        print(f"❌ Error creating session: {e}")
        return "" 
        

def close_saucelabs_session(cdp_url: str) -> bool:
    """
    Close a SauceLabs browser session
    
    Args:
        session_id: The session ID to close
        username: SauceLabs username (optional, uses default)
        access_key: SauceLabs access key (optional, uses default)
        
    Returns:
        bool: True if session was closed successfully, False otherwise
    """
    session_id = extract_session_id_from_cdp_url(cdp_url)
    print(f"\n🧹 Closing SauceLabs Session: {session_id}")
    print("=" * 40)

    hub_url = f"https://{SAUCELABS_USERNAME}:{SAUCELABS_PRIVATEKEY}@ondemand.us-west-1.saucelabs.com:443/wd/hub"

    try:
        print(f"🔄 Sending DELETE request to close session...")
        response = requests.delete(f"{hub_url}/session/{session_id}", timeout=30)
        
        if response.status_code in [200, 204]:
            print(f"✅ Session {session_id} closed successfully")
            print(f"📊 Response status: {response.status_code}")
            return True
        else:
            print(f"⚠️ Unexpected response when closing session: {response.status_code}")
            print(f"📝 Response text: {response.text}")
            return False
            
    except requests.exceptions.Timeout:
        print(f"⏰ Timeout while closing session {session_id}")
        return False
    except requests.exceptions.RequestException as e:
        print(f"❌ Network error while closing session: {e}")
        return False
    except Exception as e:
        print(f"❌ Unexpected error while closing session: {e}")
        return False


def extract_session_id_from_cdp_url(cdp_url: str) -> str:
    """
    Extract session ID from CDP URL
    
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


async def _cdp_send(ws: aiohttp.ClientWebSocketResponse, method: str, params: dict | None, _id: list[int], session_id: str | None = None) -> dict:
    """Send a CDP command and await the response with the same id.
    If session_id is provided, include it to address the attached target session.
    """
    _id[0] += 1
    msg = {"id": _id[0], "method": method, "params": params or {}}
    if session_id:
        msg["sessionId"] = session_id
    await ws.send_str(_json.dumps(msg))
    while True:
        m = await ws.receive()
        if m.type == aiohttp.WSMsgType.TEXT:
            try:
                data = _json.loads(m.data)
            except Exception:
                continue
            # Auto-dismiss blocking JS dialogs so they don't interrupt typing
            if isinstance(data, dict) and data.get("method") == "Page.javascriptDialogOpening":
                try:
                    await ws.send_str(_json.dumps({
                        "id": _id[0] + 5000,
                        "method": "Page.handleJavaScriptDialog",
                        "params": {"accept": True},
                        **({"sessionId": session_id} if session_id else {})
                    }))
                except Exception:
                    pass
                # continue waiting for our response id
            if data.get("id") == _id[0]:
                return data
            # ignore other events
        elif m.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
            raise RuntimeError(f"WebSocket closed or error during {method}: {m.type}")


def _extract_eval_value(resp: dict):
    """Extract value from Runtime.evaluate response using returnByValue."""
    try:
        return resp["result"]["result"].get("value")
    except Exception:
        return None


async def _do_login_cdp_async(cdp_ws_url: str, login_url: str, username: str, password: str, timeout: float = 20.0) -> bool:
    """Use CDP to navigate to login_url, fill credentials, and submit."""
    login_start_time = time.time()  # Track total execution time
    print(f"🕐 Starting login process at {time.strftime('%H:%M:%S', time.localtime(login_start_time))}")
    
    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(cdp_ws_url, heartbeat=15) as ws:
            seq = [0]

            # Discover targets and attach to a page
            await _cdp_send(ws, "Target.setDiscoverTargets", {"discover": True}, seq)
            targets = await _cdp_send(ws, "Target.getTargets", None, seq)
            target_infos = (targets.get("result", {}) or {}).get("targetInfos", [])
            page_target_id = None
            for info in target_infos:
                if info.get("type") == "page":
                    page_target_id = info.get("targetId")
                    break
            if not page_target_id and target_infos:
                page_target_id = target_infos[0].get("targetId")
            if not page_target_id:
                created = await _cdp_send(ws, "Target.createTarget", {"url": login_url}, seq)
                page_target_id = (created.get("result", {}) or {}).get("targetId")
                if not page_target_id:
                    raise RuntimeError("No CDP targets available to attach and failed to create one")

            attach = await _cdp_send(ws, "Target.attachToTarget", {"targetId": page_target_id, "flatten": True}, seq)
            session_id = (attach.get("result", {}) or {}).get("sessionId")
            if not session_id:
                raise RuntimeError("Failed to attach to target: no sessionId returned")

            # Enable domains on the attached session
            await _cdp_send(ws, "Page.enable", None, seq, session_id=session_id)
            await _cdp_send(ws, "Runtime.enable", None, seq, session_id=session_id)

            # Enable auto-attach to catch new tabs
            await _cdp_send(ws, "Target.setAutoAttach", {"autoAttach": True, "waitForDebuggerOnStart": False, "flatten": True}, seq)

            # Navigate to login URL
            print(f"🌐 Navigating to: {login_url}")
            await _cdp_send(ws, "Page.navigate", {"url": login_url}, seq, session_id=session_id)
            
            navigation_time = time.time() - login_start_time
            print(f"⏱️ Navigation completed in {navigation_time:.2f} seconds")

            # Wait for page to load and check for new tabs/targets
            start = time.time()
            new_target_found = False
            while time.time() - start < timeout:
                ready = await _cdp_send(ws, "Runtime.evaluate", {
                    "expression": "document.readyState",
                    "returnByValue": True
                }, seq, session_id=session_id)
                state = _extract_eval_value(ready)
                if state in ("interactive", "complete"):
                    # Check current URL to see where we landed
                    current_url = await _cdp_send(ws, "Runtime.evaluate", {
                        "expression": "window.location.href",
                        "returnByValue": True
                    }, seq, session_id=session_id)
                    url = _extract_eval_value(current_url)
                    print(f"📍 Current URL after navigation: {url}")
                    
                    # Check for new targets (tabs) that may have been created
                    targets = await _cdp_send(ws, "Target.getTargets", None, seq)
                    target_infos = (targets.get("result", {}) or {}).get("targetInfos", [])
                    
                    # Look for new page targets
                    new_targets = [t for t in target_infos if t.get("type") == "page" and t.get("targetId") != page_target_id]
                    
                    if new_targets:
                        print(f"🔄 Found {len(new_targets)} new tabs. Checking for login page...")
                        
                        # Find the best target (preferably one with login-related URL or opened by current target)
                        login_target = None
                        for target in new_targets:
                            target_url = target.get("url", "")
                            opener_id = target.get("openerId")
                            
                            # Prefer targets opened by our current page or with login-related URLs
                            if (opener_id == page_target_id or 
                                any(keyword in target_url.lower() for keyword in ["login", "auth", "account", "saml", "sso"])):
                                login_target = target
                                break
                        
                        # If no specific login target found, use the first new target
                        if not login_target and new_targets:
                            login_target = new_targets[0]
                        
                        if login_target:
                            new_target_id = login_target.get("targetId")
                            new_url = login_target.get("url", "")
                            print(f"🎯 Switching to new tab: {new_target_id} ({new_url})")
                            
                            # Attach to the new target
                            attach = await _cdp_send(ws, "Target.attachToTarget", {"targetId": new_target_id, "flatten": True}, seq)
                            new_session_id = (attach.get("result", {}) or {}).get("sessionId")
                            
                            if new_session_id:
                                # Update our session to the new tab
                                page_target_id = new_target_id
                                session_id = new_session_id
                                
                                # Enable domains on the new session
                                await _cdp_send(ws, "Page.enable", None, seq, session_id=session_id)
                                await _cdp_send(ws, "Runtime.enable", None, seq, session_id=session_id)
                                
                                # Activate and bring to front
                                await _cdp_send(ws, "Target.activateTarget", {"targetId": page_target_id}, seq)
                                await _cdp_send(ws, "Page.bringToFront", None, seq, session_id=session_id)
                                
                                new_target_found = True
                                print(f"✅ Successfully switched to new tab with login page")
                                break
                    
                    break
                await asyncio.sleep(0.5)
            
            # If we found a new target, wait for it to fully load
            if new_target_found:
                print("⏳ Waiting for new tab to fully load...")
                start = time.time()
                while time.time() - start < 10:
                    ready = await _cdp_send(ws, "Runtime.evaluate", {
                        "expression": "document.readyState",
                        "returnByValue": True
                    }, seq, session_id=session_id)
                    state = _extract_eval_value(ready)
                    if state in ("interactive", "complete"):
                        break
                    await asyncio.sleep(0.5)

            # Wait for the login form to appear and get current page content
            print("🔍 Checking page content...")
            await asyncio.sleep(2)  # Give page time to fully load
            
            # Get page title and URL to debug
            page_info = await _cdp_send(ws, "Runtime.evaluate", {
                "expression": """
                ({
                    title: document.title,
                    url: window.location.href,
                    hasEmailField: !!document.getElementById('login_username'),
                    hasPasswordField: !!document.getElementById('password'),
                    bodyText: document.body ? document.body.innerText.substring(0, 500) : 'No body'
                })
                """,
                "returnByValue": True
            }, seq, session_id=session_id)
            
            info = _extract_eval_value(page_info)
            print(f"📄 Page Info: {info}")

            # Wait for email input field to be available
            print("📧 Waiting for email input field...")
            start = time.time()
            email_found = False
            while time.time() - start < timeout:
                email_present = await _cdp_send(ws, "Runtime.evaluate", {
                    "expression": """
                    (() => {
                        const emailField = document.getElementById('login_username');
                        const loginNameSection = document.getElementById('login_name');
                        return emailField && loginNameSection && 
                               loginNameSection.style.display !== 'none' &&
                               !emailField.disabled;
                    })()
                    """,
                    "returnByValue": True
                }, seq, session_id=session_id)
                if bool(_extract_eval_value(email_present)):
                    email_found = True
                    break
                await asyncio.sleep(0.5)

            if not email_found:
                total_time = time.time() - login_start_time
                print(f"⏱️ Total execution time: {total_time:.2f} seconds")
                print("❌ Email field not found or not visible")
                return False

            # Step 1: Fill email and click Next
            print(f"✍️ Entering email: {username}")
            js_enter_email = f"""
            (function() {{
                const email = {_json.dumps(username)};
                const emailInput = document.getElementById('login_username');
                if (!emailInput) return 'EMAIL_FIELD_NOT_FOUND';
                
                // Focus and clear the field
                emailInput.focus();
                emailInput.value = '';
                
                // Type email character by character to trigger events
                for (const char of email) {{
                    emailInput.value += char;
                    emailInput.dispatchEvent(new InputEvent('input', {{bubbles: true, inputType: 'insertText', data: char}}));
                }}
                
                // Trigger change event
                emailInput.dispatchEvent(new Event('change', {{bubbles: true}}));
                emailInput.blur();
                
                // Find and click the Next button
                const nextButton = document.querySelector('form[name="saml_external"] input[type="submit"]');
                if (!nextButton) return 'NEXT_BUTTON_NOT_FOUND';
                
                // Wait a moment then click
                setTimeout(() => {{
                    nextButton.click();
                }}, 100);
                
                return 'EMAIL_SUBMITTED';
            }})()
            """

            result = await _cdp_send(ws, "Runtime.evaluate", {
                "expression": js_enter_email,
                "returnByValue": True
            }, seq, session_id=session_id)
            
            email_result = _extract_eval_value(result)
            email_submit_time = time.time() - login_start_time
            print(f"📧 Email step result: {email_result} (completed in {email_submit_time:.2f}s total)")

            # Wait for password field to appear (indicating successful email submission)
            print("🔒 Waiting for password field to appear...")
            start = time.time()
            password_found = False
            while time.time() - start < timeout:
                password_visible = await _cdp_send(ws, "Runtime.evaluate", {
                    "expression": """
                    (() => {
                        const passwordSection = document.getElementById('login_password');
                        const passwordInput = document.getElementById('password');
                        const emailSection = document.getElementById('login_name');
                        
                        // Password section should be visible and email section should be hidden
                        const passwordReady = passwordSection && passwordInput && 
                                            passwordSection.style.display !== 'none' && 
                                            !passwordInput.disabled;
                        const emailHidden = emailSection && emailSection.style.display === 'none';
                        
                        return passwordReady && emailHidden;
                    })()
                    """,
                    "returnByValue": True
                }, seq, session_id=session_id)
                if bool(_extract_eval_value(password_visible)):
                    password_found = True
                    break
                await asyncio.sleep(0.5)

            if not password_found:
                print("❌ Password field not found or email submission failed")
                # Let's check what happened
                status = await _cdp_send(ws, "Runtime.evaluate", {
                    "expression": """
                    ({
                        emailSectionDisplay: document.getElementById('login_name') ? document.getElementById('login_name').style.display : 'not found',
                        passwordSectionDisplay: document.getElementById('login_password') ? document.getElementById('login_password').style.display : 'not found',
                        currentUrl: window.location.href,
                        errorText: document.querySelector('.error') ? document.querySelector('.error').textContent : 'no error'
                    })
                    """,
                    "returnByValue": True
                }, seq, session_id=session_id)
                print(f"🔍 Status after email submission: {_extract_eval_value(status)}")
                total_time = time.time() - login_start_time
                print(f"⏱️ Total execution time: {total_time:.2f} seconds")
                return False

            # Step 2: Fill password and click Log In
            print(f"🔐 Entering password...")
            js_enter_password = f"""
            (function() {{
                const password = {_json.dumps(password)};
                const passwordInput = document.getElementById('password');
                if (!passwordInput) return 'PASSWORD_FIELD_NOT_FOUND';
                
                // Focus and clear the field
                passwordInput.focus();
                passwordInput.value = '';
                
                // Type password character by character to trigger events
                for (const char of password) {{
                    passwordInput.value += char;
                    passwordInput.dispatchEvent(new InputEvent('input', {{bubbles: true, inputType: 'insertText', data: char}}));
                }}
                
                // Trigger change event
                passwordInput.dispatchEvent(new Event('change', {{bubbles: true}}));
                passwordInput.blur();
                
                // Find and click the Log In button
                const loginButton = document.getElementById('password_submit');
                if (!loginButton) return 'LOGIN_BUTTON_NOT_FOUND';
                
                // Wait a moment then click
                setTimeout(() => {{
                    loginButton.click();
                }}, 100);
                
                return 'PASSWORD_SUBMITTED';
            }})()
            """

            result = await _cdp_send(ws, "Runtime.evaluate", {
                "expression": js_enter_password,
                "returnByValue": True
            }, seq, session_id=session_id)
            
            password_result = _extract_eval_value(result)
            password_submit_time = time.time() - login_start_time
            print(f"🔐 Password step result: {password_result} (completed in {password_submit_time:.2f}s total)")

            # Wait for login to complete (URL returns to login_url)
            print(f"⏳ Waiting for URL to return to: {login_url}")
            start = time.time()
            check_interval = 0.5  # Check every 0.5 seconds for faster response
            
            while time.time() - start < timeout:
                current_url_result = await _cdp_send(ws, "Runtime.evaluate", {
                    "expression": "window.location.href",
                    "returnByValue": True
                }, seq, session_id=session_id)
                
                current_url = _extract_eval_value(current_url_result)
                print(f"🔍 Current URL: {current_url}")
                
                # Normalize URLs by removing trailing slashes for comparison
                normalized_current = current_url.rstrip('/') if current_url else ''
                normalized_login = login_url.rstrip('/')
                
                if current_url and normalized_current == normalized_login:
                    print("✅ Login complete - URL returned to login page!")
                    break
                    
                await asyncio.sleep(check_interval)

            # Get final URL to confirm login status
            final_url = await _cdp_send(ws, "Runtime.evaluate", {
                "expression": "window.location.href",
                "returnByValue": True
            }, seq, session_id=session_id)
            
            current_url = _extract_eval_value(final_url)
            print(f"🌐 Final URL: {current_url}")
            
            # Calculate and print total execution time
            total_time = time.time() - login_start_time
            print(f"⏱️ Total login execution time: {total_time:.2f} seconds")
            
            # Normalize URLs by removing trailing slashes for comparison
            normalized_current = current_url.rstrip('/') if current_url else ''
            normalized_login = login_url.rstrip('/')
            
            if current_url and normalized_current == normalized_login:
                print("🎉 Login successful - URL returned to login page!")
                return True
            else:
                print("⚠️ Login may have failed - URL did not return to login page")
                print(f"🔍 Expected: {normalized_login}, Got: {normalized_current}")
                return False


def do_login(cdp_ws_url: str, login_url: str, username: str, password: str, timeout: float = 20.0) -> None:
    """Synchronous wrapper for CDP login."""
    asyncio.run(_do_login_cdp_async(cdp_ws_url, login_url, username, password, timeout))



def main():
    # Create a sample CloudBrowserProfile for testing
    profile = CloudBrowserProfile(
        browser_name='chrome',
        browser_version='latest',
        platform_name='Windows 11',
        proxy=ProxySettings(
            server=PROXY_URL,
            username=PROXY_USERNAME,
            password=PROXY_PASSWORD
        )
    )
    
    # Create session
    cdp_url = saucelabs_session_creation(profile)
    
    if cdp_url:

            # Navigate and login in the real browser via CDP
            login_url = "https://example.com"
            print(f"\n🌐 Navigating to login page via CDP: {login_url}")
            if do_login(cdp_url, login_url, PROXY_USERNAME or "", PROXY_PASSWORD or ""):
                print("✅ Login attempt via CDP complete")
            time.sleep(2)
            
            # Close the session
            success = close_saucelabs_session(cdp_url)
            if success:
                print("🎉 Browser session closed successfully!")
            else:
                print("😞 Failed to close browser session")

if __name__ == "__main__":
    main()
