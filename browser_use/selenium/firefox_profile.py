"""
Firefox browser profile configuration for Selenium WebDriver.

This module contains Firefox-specific preferences and command-line arguments
for automation, similar to how profile.py handles Chrome configuration.

Based on geckodriver defaults: https://searchfox.org/mozilla-central/source/testing/geckodriver/src/prefs.rs
and Playwright/Puppeteer Firefox configurations.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
	from selenium import webdriver


# Firefox command-line arguments
FIREFOX_HEADLESS_ARGS = [
	'-headless',
]

FIREFOX_DOCKER_ARGS = [
	# Firefox doesn't need as many Docker-specific args as Chrome
	# but these help with stability in containerized environments
]

FIREFOX_DISABLE_SECURITY_ARGS = [
	# Firefox security settings are primarily controlled via preferences, not CLI args
	# See FIREFOX_DISABLE_SECURITY_PREFS below
]

# Firefox preferences for automation (set via about:config or FirefoxOptions)
# Based on geckodriver defaults: https://searchfox.org/mozilla-central/source/testing/geckodriver/src/prefs.rs
# and Playwright/Puppeteer Firefox configurations

FIREFOX_DEFAULT_PREFS: dict[str, bool | int | str] = {
	# === Disable updates and telemetry ===
	'app.normandy.api_url': '',  # Disable Shield/Normandy
	'app.update.checkInstallTime': False,  # Disable build age check
	'app.update.disabledForTesting': True,  # Disable auto-updates
	'app.update.enabled': False,  # Disable application updates
	'app.update.staging.enabled': False,
	
	# === Browser startup and session ===
	'browser.sessionstore.resume_from_crash': False,  # Don't restore tabs after crash
	'browser.shell.checkDefaultBrowser': False,  # Skip default browser check
	'browser.startup.homepage_override.mstone': 'ignore',  # Skip upgrade page
	'browser.startup.page': 0,  # Start with blank page (about:blank)
	'browser.uitour.enabled': False,  # Disable UI tour
	'browser.warnOnQuit': False,  # Don't warn on quit
	'browser.tabs.warnOnClose': False,  # Don't warn when closing tabs
	'browser.tabs.warnOnCloseOtherTabs': False,
	'browser.aboutConfig.showWarning': False,  # Skip about:config warning
	'browser.pagethumbnails.capturing_disabled': True,  # Disable page thumbnails
	
	# === Disable data reporting and telemetry ===
	'datareporting.healthreport.documentServerURI': 'http://%(server)s/dummy/healthreport/',
	'datareporting.healthreport.logging.consoleEnabled': False,
	'datareporting.healthreport.service.enabled': False,
	'datareporting.healthreport.service.firstRun': False,
	'datareporting.healthreport.uploadEnabled': False,
	'datareporting.policy.dataSubmissionEnabled': False,
	'datareporting.policy.dataSubmissionPolicyBypassNotification': True,
	'toolkit.telemetry.archive.enabled': False,
	'toolkit.telemetry.bhrPing.enabled': False,
	'toolkit.telemetry.enabled': False,
	'toolkit.telemetry.firstShutdownPing.enabled': False,
	'toolkit.telemetry.hybridContent.enabled': False,
	'toolkit.telemetry.newProfilePing.enabled': False,
	'toolkit.telemetry.reportingpolicy.firstRun': False,
	'toolkit.telemetry.server': '',
	'toolkit.telemetry.shutdownPingSender.enabled': False,
	'toolkit.telemetry.unified': False,
	'toolkit.telemetry.updatePing.enabled': False,
	
	# === Process and hang monitoring ===
	'dom.ipc.reportProcessHangs': False,  # Disable ProcessHangMonitor
	'hangmonitor.timeout': 0,  # No hang monitor timeout
	
	# === Extensions ===
	'extensions.autoDisableScopes': 0,  # Don't auto-disable extensions
	'extensions.enabledScopes': 5,  # SCOPE_PROFILE + SCOPE_APPLICATION
	'extensions.installDistroAddons': False,  # No distribution extensions
	'extensions.update.enabled': False,  # Disable extension updates
	'extensions.update.notifyUser': False,
	'extensions.blocklist.enabled': False,  # Disable blocklist
	'extensions.getAddons.cache.enabled': False,
	
	# === Focus and window management ===
	'focusmanager.testmode': True,  # Allow focus in background
	
	# === User agent and geolocation ===
	'general.useragent.updates.enabled': False,  # Disable UA updates
	'geo.provider.testing': True,  # Use network provider for geolocation
	'geo.wifi.scan': False,  # Don't scan WiFi for geolocation
	'geo.enabled': False,  # Disable geolocation by default
	
	# === Media and plugins ===
	'media.gmp-manager.updateEnabled': False,  # Disable OpenH264/Widevine updates
	'media.sanity-test.disabled': True,  # Disable GFX sanity test
	'media.autoplay.default': 0,  # Allow autoplay (0=allow, 1=block-audible, 5=block-all)
	'media.block-autoplay-until-in-foreground': False,
	
	# === Network ===
	'network.manage-offline-status': False,  # Don't auto-switch offline/online
	'network.sntp.pools': '%(server)s',  # Disable SNTP requests
	'network.captive-portal-service.enabled': False,  # Disable captive portal detection
	'network.connectivity-service.enabled': False,
	'network.dns.disablePrefetch': True,  # Disable DNS prefetch
	'network.http.speculative-parallel-limit': 0,  # Disable speculative connections
	'network.predictor.enabled': False,  # Disable network predictor
	'network.prefetch-next': False,  # Disable link prefetch
	
	# === Security ===
	'security.certerrors.mitm.priming.enabled': False,  # No MITM priming
	'security.fileuri.strict_origin_policy': False,  # Allow file:// cross-origin
	'security.notification_enable_delay': 0,  # No notification delay
	
	# === Services and remote settings ===
	'services.settings.server': 'data:,#remote-settings-dummy/v1',  # Disable remote settings
	
	# === First run and welcome pages ===
	'startup.homepage_welcome_url': 'about:blank',
	'startup.homepage_welcome_url.additional': '',
	'browser.newtabpage.activity-stream.asrouter.providers.cfr': 'null',
	'browser.newtabpage.activity-stream.asrouter.providers.cfr-fxa': 'null',
	'browser.newtabpage.activity-stream.asrouter.providers.snippets': 'null',
	'browser.newtabpage.activity-stream.asrouter.providers.message-groups': 'null',
	'browser.newtabpage.activity-stream.asrouter.providers.whats-new-panel': 'null',
	'browser.newtabpage.activity-stream.asrouter.providers.messaging-experiments': 'null',
	'browser.newtabpage.activity-stream.feeds.system.topstories': False,
	'browser.newtabpage.activity-stream.feeds.snippets': False,
	'browser.newtabpage.activity-stream.tippyTop.service.endpoint': '',
	'browser.newtabpage.activity-stream.discoverystream.config': '[]',
	'browser.newtabpage.activity-stream.fxaccounts.endpoint': '',
	'browser.newtabpage.enabled': False,
	
	# === Crash prevention ===
	'toolkit.startup.max_resumed_crashes': -1,  # Prevent safe mode after crashes
	
	# === Webapp updates ===
	'browser.webapps.checkForUpdates': 0,
	
	# === Console and debugging ===
	'browser.dom.window.dump.enabled': True,  # Enable dump() for debugging
	'devtools.console.stdout.chrome': True,
	'devtools.console.stdout.content': True,
	
	# === Popups and dialogs ===
	'dom.disable_beforeunload': True,  # Disable beforeunload dialogs
	'dom.disable_open_during_load': False,  # Allow popups during load
	'prompts.tab_modal.enabled': False,  # Disable tab-modal prompts
	'browser.link.open_newwindow': 3,  # Open new windows in tabs (3=new tab)
	'browser.link.open_newwindow.restriction': 0,  # No restrictions
	
	# === Download behavior ===
	'browser.download.folderList': 2,  # Use custom download folder (2=custom)
	'browser.download.manager.showWhenStarting': False,
	'browser.download.panel.shown': True,
	'browser.download.useDownloadDir': True,
	'browser.helperApps.alwaysAsk.force': False,
	'browser.helperApps.neverAsk.saveToDisk': 'application/pdf,application/octet-stream,application/x-pdf,application/zip,text/csv,text/plain,application/json',
	
	# === PDF handling ===
	'pdfjs.disabled': True,  # Disable built-in PDF viewer (download instead)
	
	# === Privacy and tracking - STRICT mode ===
	# Enhanced Tracking Protection (ETP) in Strict mode blocks cross-site tracking
	'browser.contentblocking.category': 'strict',  # Use strict content blocking
	'privacy.trackingprotection.enabled': True,  # Enable tracking protection
	'privacy.trackingprotection.pbmode.enabled': True,  # Enable in private browsing too
	'privacy.trackingprotection.socialtracking.enabled': True,  # Block social trackers
	'privacy.trackingprotection.cryptomining.enabled': True,  # Block cryptominers
	'privacy.trackingprotection.fingerprinting.enabled': True,  # Block fingerprinting
	
	# Block cross-site tracking cookies
	'network.cookie.cookieBehavior': 5,  # 5=reject cross-site and social media trackers (Strict)
	'network.cookie.cookieBehavior.pbmode': 5,
	
	# Isolate cookies and storage by first-party domain
	'privacy.firstparty.isolate': True,  # First-party isolation (breaks some sites but blocks tracking)
	'privacy.partition.network_state': True,
	'privacy.partition.serviceWorkers': True,
	'privacy.partition.always_partition_third_party_non_cookie_storage': True,
	'privacy.partition.always_partition_third_party_non_cookie_storage.exempt_sessionstorage': False,
	
	# === Safe browsing ===
	'browser.safebrowsing.enabled': False,
	'browser.safebrowsing.malware.enabled': False,
	'browser.safebrowsing.phishing.enabled': False,
	'browser.safebrowsing.downloads.enabled': False,
	'browser.safebrowsing.downloads.remote.enabled': False,
	
	# === Sync ===
	'services.sync.engine.addons': False,
	'services.sync.engine.bookmarks': False,
	'services.sync.engine.history': False,
	'services.sync.engine.passwords': False,
	'services.sync.engine.prefs': False,
	'services.sync.engine.tabs': False,
	
	# === Memory and performance ===
	'browser.cache.disk.enable': False,  # Disable disk cache for automation
	'browser.cache.memory.enable': True,
	'browser.cache.offline.enable': False,
	
	# === Accessibility ===
	'accessibility.force_disabled': 1,  # Disable accessibility (1=off, improves performance)
	
	# === Signon/Password manager ===
	'signon.rememberSignons': False,  # Don't remember passwords
	'signon.autofillForms': False,
	'signon.generation.enabled': False,
	
	# === Disable Credential Management ===
	'dom.security.credentialmanagement.enabled': False,  # Disable Credential Management API
	'identity.fxaccounts.enabled': False,  # Disable Firefox Accounts integration
	'permissions.default.desktop-notification': 2,  # Block notification prompts (2=block)
	'dom.push.enabled': False,  # Disable push notifications
	'dom.webnotifications.enabled': False,  # Disable web notifications
	'dom.webnotifications.serviceworker.enabled': False,
	
	# Disable search suggestions
	'browser.newtabpage.activity-stream.improvesearch.handoffToAwesomebar': False,
	'browser.urlbar.suggest.engines': False,
}

# Firefox stealth preferences to avoid bot detection
FIREFOX_STEALTH_PREFS: dict[str, bool | int | str] = {
	'dom.webdriver.enabled': False,  # Hide webdriver flag (CRITICAL for stealth)
	'useAutomationExtension': False,
	'marionette.enabled': False,  # Hide marionette (when not needed)
	'privacy.resistFingerprinting': False,  # Disabled - can cause issues with automation
	'webgl.disabled': False,  # Keep WebGL enabled (disabling is suspicious)
	'media.peerconnection.enabled': True,  # Keep WebRTC enabled (disabling is suspicious)
	
	# Navigator properties
	'general.platform.override': '',  # Use default platform
	'general.appversion.override': '',  # Use default app version
	
	# Disable automation-revealing features but keep them working
	'devtools.selfxss.count': 100,  # Avoid self-XSS warning
}

# Firefox security-disabled preferences (use with caution)
FIREFOX_DISABLE_SECURITY_PREFS: dict[str, bool | int | str] = {
	'security.fileuri.strict_origin_policy': False,
	'security.mixed_content.block_active_content': False,
	'security.mixed_content.block_display_content': False,
	'security.insecure_field_warning.contextual.enabled': False,
	'security.insecure_password.ui.enabled': False,
	'network.stricttransportsecurity.preloadlist': False,
	'security.cert_pinning.enforcement_level': 0,  # Disable certificate pinning
	'security.ssl.enable_ocsp_stapling': False,
	'network.http.referer.XOriginPolicy': 0,  # Allow cross-origin referrers
}

# Firefox deterministic rendering preferences (for consistent screenshots)
FIREFOX_DETERMINISTIC_RENDERING_PREFS: dict[str, bool | int | str] = {
	'gfx.color_management.mode': 0,  # Disable color management
	'gfx.color_management.rendering_intent': 3,  # Use perceptual rendering
	'gfx.font_rendering.graphite.enabled': False,  # Disable Graphite font rendering
	'ui.prefersReducedMotion': 1,  # Prefer reduced motion
}


def get_firefox_preferences(
	include_default: bool = True,
	include_stealth: bool = True,
	disable_security: bool = False,
	deterministic_rendering: bool = False,
	download_dir: str | None = None,
	additional_prefs: dict[str, bool | int | str] | None = None,
) -> dict[str, bool | int | str]:
	"""
	Get a combined dictionary of Firefox preferences for automation.
	
	This helper function combines various Firefox preference sets based on
	the use case requirements.
	
	Args:
		include_default: Include standard automation preferences (recommended True)
		include_stealth: Include stealth preferences to avoid bot detection
		disable_security: Include security-disabling preferences (use with caution!)
		deterministic_rendering: Include preferences for consistent rendering/screenshots
		download_dir: Custom download directory path (will set browser.download.dir)
		additional_prefs: Additional custom preferences to merge in
		
	Returns:
		Combined dictionary of Firefox preferences
		
	Example:
		>>> from selenium import webdriver
		>>> from browser_use.selenium.firefox_profile import get_firefox_preferences
		>>> 
		>>> options = webdriver.FirefoxOptions()
		>>> prefs = get_firefox_preferences(include_stealth=True, download_dir='/tmp/downloads')
		>>> for name, value in prefs.items():
		...     options.set_preference(name, value)
	"""
	prefs: dict[str, bool | int | str] = {}
	
	if include_default:
		prefs.update(FIREFOX_DEFAULT_PREFS)
	
	if include_stealth:
		prefs.update(FIREFOX_STEALTH_PREFS)
	
	if disable_security:
		prefs.update(FIREFOX_DISABLE_SECURITY_PREFS)
	
	if deterministic_rendering:
		prefs.update(FIREFOX_DETERMINISTIC_RENDERING_PREFS)
	
	if download_dir:
		prefs['browser.download.dir'] = download_dir
		prefs['browser.download.folderList'] = 2  # Use custom directory
	
	if additional_prefs:
		prefs.update(additional_prefs)
	
	return prefs


def apply_firefox_preferences(
	options: 'webdriver.FirefoxOptions',  # type: ignore[name-defined]
	include_default: bool = True,
	include_stealth: bool = True,
	disable_security: bool = False,
	deterministic_rendering: bool = False,
	download_dir: str | None = None,
	additional_prefs: dict[str, bool | int | str] | None = None,
) -> None:
	"""
	Apply Firefox preferences to a FirefoxOptions object.
	
	This is a convenience function that gets preferences using get_firefox_preferences()
	and applies them to the given FirefoxOptions.
	
	Args:
		options: Selenium FirefoxOptions object to configure
		include_default: Include standard automation preferences (recommended True)
		include_stealth: Include stealth preferences to avoid bot detection
		disable_security: Include security-disabling preferences (use with caution!)
		deterministic_rendering: Include preferences for consistent rendering/screenshots
		download_dir: Custom download directory path
		additional_prefs: Additional custom preferences to merge in
		
	Example:
		>>> from selenium import webdriver
		>>> from browser_use.selenium.firefox_profile import apply_firefox_preferences
		>>> 
		>>> options = webdriver.FirefoxOptions()
		>>> apply_firefox_preferences(options, include_stealth=True)
		>>> driver = webdriver.Firefox(options=options)
	"""
	prefs = get_firefox_preferences(
		include_default=include_default,
		include_stealth=include_stealth,
		disable_security=disable_security,
		deterministic_rendering=deterministic_rendering,
		download_dir=download_dir,
		additional_prefs=additional_prefs,
	)
	
	for name, value in prefs.items():
		options.set_preference(name, value)
