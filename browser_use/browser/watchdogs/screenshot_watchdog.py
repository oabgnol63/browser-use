"""Screenshot watchdog for handling screenshot requests using CDP."""

import asyncio
import base64
from io import BytesIO
from PIL import Image
from typing import TYPE_CHECKING, Any, ClassVar

from bubus import BaseEvent
from cdp_use.cdp.page import CaptureScreenshotParameters

from browser_use.browser.events import ScreenshotEvent
from browser_use.browser.views import BrowserError
from browser_use.browser.watchdog_base import BaseWatchdog
from browser_use.observability import observe_debug

if TYPE_CHECKING:
	pass


class ScreenshotWatchdog(BaseWatchdog):
	"""Handles screenshot requests using CDP."""

	# Events this watchdog listens to
	LISTENS_TO: ClassVar[list[type[BaseEvent[Any]]]] = [ScreenshotEvent]

	# Events this watchdog emits
	EMITS: ClassVar[list[type[BaseEvent[Any]]]] = []

	def _is_vision_only_mode(self) -> bool:
		return bool(getattr(self.browser_session, '_use_native_computer_use', False))

	async def _resolve_target_id(self, event: ScreenshotEvent) -> str:
		"""Resolve which target should be captured for this screenshot request."""
		if self._is_vision_only_mode():
			if not self.browser_session.session_manager:
				raise BrowserError('[ScreenshotWatchdog] Session manager unavailable for vision-only screenshot capture')

			focus_timeout = min(event.event_timeout or 15.0, 3.0)
			focus_valid = await self.browser_session.session_manager.ensure_valid_focus(timeout=focus_timeout)
			if not focus_valid or not self.browser_session.agent_focus_target_id:
				raise BrowserError('[ScreenshotWatchdog] No valid focused page available for vision-only screenshot capture')

			focused_target = self.browser_session.get_focused_target()
			if not focused_target or focused_target.target_type not in ('page', 'tab'):
				target_type_str = focused_target.target_type if focused_target else 'None'
				raise BrowserError(
					f'[ScreenshotWatchdog] Vision-only screenshot capture requires focused page/tab target, got {target_type_str}'
				)

			return focused_target.target_id

		# Validate focused target is a top-level page (not iframe/worker)
		# CDP Page.captureScreenshot only works on page/tab targets
		focused_target = self.browser_session.get_focused_target()
		if focused_target and focused_target.target_type in ('page', 'tab'):
			return focused_target.target_id

		# Focused target is iframe/worker/missing - fall back to any page target
		target_type_str = focused_target.target_type if focused_target else 'None'
		self.logger.warning(f'[ScreenshotWatchdog] Focused target is {target_type_str}, falling back to page target')
		page_targets = self.browser_session.get_page_targets()
		if not page_targets:
			raise BrowserError('[ScreenshotWatchdog] No page targets available for screenshot')
		return page_targets[-1].target_id

	@observe_debug(ignore_input=True, ignore_output=True, name='screenshot_event_handler')
	async def on_ScreenshotEvent(self, event: ScreenshotEvent) -> str:
		"""Handle screenshot request using CDP.

		Args:
			event: ScreenshotEvent with optional full_page and clip parameters

		Returns:
			Dict with 'screenshot' key containing base64-encoded screenshot or None
		"""
		self.logger.debug('[ScreenshotWatchdog] Handler START - on_ScreenshotEvent called')
		try:
			target_id = await self._resolve_target_id(event)
			cdp_session = await self.browser_session.get_or_create_cdp_session(target_id, focus=True)

			# Remove highlights BEFORE taking the screenshot so they don't appear in the image.
			# Done here (not in finally) so CancelledError is never swallowed — any await in a
			# finally block can suppress external task cancellation.
			# remove_highlights() has its own asyncio.timeout(3.0) internally so it won't block.
			try:
				await self.browser_session.remove_highlights()
			except Exception:
				pass

			# Prepare screenshot parameters
			params_dict: dict[str, Any] = {'format': 'png', 'captureBeyondViewport': event.full_page}
			if event.clip:
				params_dict['clip'] = {
					'x': event.clip['x'],
					'y': event.clip['y'],
					'width': event.clip['width'],
					'height': event.clip['height'],
					'scale': 1,
				}
			params = CaptureScreenshotParameters(**params_dict)

			# Take screenshot using CDP
			self.logger.debug(f'[ScreenshotWatchdog] Taking screenshot with params: {params}')
			capture_coro = cdp_session.cdp_client.send.Page.captureScreenshot(params=params, session_id=cdp_session.session_id)
			if self._is_vision_only_mode() and event.event_timeout is not None:
				result = await asyncio.wait_for(capture_coro, timeout=event.event_timeout)
			else:
				result = await capture_coro

			# Return base64-encoded screenshot data
			if result and 'data' in result:
				# Extract actual screenshot dimensions for coordinate conversion
				try:
					img = Image.open(BytesIO(base64.b64decode(result['data'])))
					self.browser_session._actual_screenshot_size = (img.width, img.height)
					self.logger.debug(f'[ScreenshotWatchdog] Screenshot captured: {img.width}x{img.height}')
				except Exception as e:
					self.logger.warning(f'[ScreenshotWatchdog] Failed to extract screenshot dimensions: {e}')
				return result['data']

			raise BrowserError('[ScreenshotWatchdog] Screenshot result missing data')
		except Exception as e:
			self.logger.error(f'[ScreenshotWatchdog] Screenshot failed: {e}')
			raise
