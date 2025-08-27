import requests
import time
import os
import dotenv

dotenv.load_dotenv()
SAUCELABS_USERNAME = os.getenv("SAUCELABS_USERNAME")
SAUCELABS_PRIVATEKEY = os.getenv("SAUCELABS_PRIVATEKEY")

from browser_use.browser.profile import CloudBrowserProfile

def saucelabs_session_creation(profile: CloudBrowserProfile) -> str:
    """Test actual SauceLabs session creation"""
    
    print("\n🌟 Testing SauceLabs Session Creation")
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
        'maxDuration': 600,
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


def main():
    # Create a sample CloudBrowserProfile for testing
    profile = CloudBrowserProfile(
        browser_name='chrome',
        browser_version='latest',
        platform_name='Windows 11'
    )
    
    # Create session
    cdp_url = saucelabs_session_creation(profile)
    print(f"CDP URL: {cdp_url}")
    
    if cdp_url:

            # Wait a bit (simulate some work)
            print("\n⏱️ Simulating browser work for 5 seconds...")
            time.sleep(5)
            
            # Close the session
            success = close_saucelabs_session(cdp_url)
            if success:
                print("🎉 Browser session closed successfully!")
            else:
                print("😞 Failed to close browser session")

if __name__ == "__main__":
    main()
