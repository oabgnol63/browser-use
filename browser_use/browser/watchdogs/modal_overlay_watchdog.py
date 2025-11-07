"""Watchdog for handling DOM-based modal overlays and advertisement popups automatically.

This watchdog detects and closes HTML/CSS-based modal dialogs, newsletter popups,
and advertisement overlays that the JavaScript dialog watchdog cannot handle.
Examples include:
- BBC.com newsletter signup modals
- iPhone advertisement overlays
- Custom HTML modal dialogs
- Cookie consent banners (optional)
"""

import asyncio
from typing import ClassVar

from bubus import BaseEvent
from pydantic import PrivateAttr

from browser_use.browser.events import NavigateToUrlEvent
from browser_use.browser.watchdog_base import BaseWatchdog


class ModalOverlayWatchdog(BaseWatchdog):
	"""Detects and automatically closes DOM-based modal overlays and advertisement popups.

	This watchdog:
	1. Listens to NavigateToUrlEvent after page navigation
	2. Scans for modal overlays using role="dialog" and other modal indicators
	3. Finds close buttons using multiple strategies (aria-label, text, classes)
	4. Clicks close buttons to dismiss modals
	5. Waits for modal to disappear before returning

	This complements PopupsWatchdog which only handles JavaScript dialogs (alert, confirm, prompt).
	"""

	# Events this watchdog listens to and emits
	LISTENS_TO: ClassVar[list[type[BaseEvent]]] = [NavigateToUrlEvent]
	EMITS: ClassVar[list[type[BaseEvent]]] = []

	# Track recently closed modals to avoid repeated closure attempts
	_recently_closed_modals: set[str] = PrivateAttr(default_factory=set)
	_close_attempts_count: dict[str, int] = PrivateAttr(default_factory=dict)

	def __init__(self, **kwargs):
		super().__init__(**kwargs)
		self.logger.debug(f'🚀 ModalOverlayWatchdog initialized, ID={id(self)}')

	def _find_close_button_candidates(self, dom_state) -> list[int]:
		"""Find elements that look like close buttons for modals.

		Strategies:
		1. aria-label containing "close", "dismiss", "x", "accept", "agree"
		2. text content = "×" or "X", "close", "dismiss", "skip", "accept", "agree"
		3. class or id containing "close", "dismiss", "btn-close", "accept", "agree"
		4. data-testid containing "close", "accept", "agree"
		"""
		close_button_candidates = []

		if not dom_state or not dom_state.selector_map:
			return close_button_candidates

		# Keywords that indicate close/dismiss buttons
		close_keywords = ["close", "dismiss", "cancel", "exit", "skip"]
		# Keywords that indicate acceptance/agreement buttons (for consent)
		accept_keywords = ["accept", "agree", "confirm", "ok", "done", "continue"]

		for index, element in dom_state.selector_map.items():
			# Strategy 1: Check aria-label
			aria_label = element.attributes.get("aria-label", "").lower()
			if (
				aria_label == "x"
				or any(keyword in aria_label for keyword in close_keywords)
				or any(keyword in aria_label for keyword in accept_keywords)
			):
				close_button_candidates.append(index)
				self.logger.debug(
					f"Found close button candidate via aria-label at index {index}: '{aria_label}'"
				)
				continue

			# Strategy 2: Check text content
			text_content = (element.text or "").lower().strip()
			if (
				text_content in ["x", "×", "✕"]
				or any(keyword == text_content for keyword in close_keywords)
				or any(keyword == text_content for keyword in accept_keywords)
			):
				close_button_candidates.append(index)
				self.logger.debug(
					f"Found close button candidate via text content at index {index}: '{text_content}'"
				)
				continue

			# Strategy 3: Check class names and id
			class_names = element.attributes.get("class", "").lower()
			element_id = element.attributes.get("id", "").lower()
			combined = f"{class_names} {element_id}"

			class_keywords = close_keywords + ["btn-close", "modal-close"] + accept_keywords
			if any(keyword in combined for keyword in class_keywords):
				close_button_candidates.append(index)
				self.logger.debug(
					f"Found close button candidate via class/id at index {index}: '{combined}'"
				)
				continue

			# Strategy 4: Check data-testid
			data_testid = element.attributes.get("data-testid", "").lower()
			if any(keyword in data_testid for keyword in close_keywords) or any(
				keyword in data_testid for keyword in accept_keywords
			):
				close_button_candidates.append(index)
				self.logger.debug(
					f"Found close button candidate via data-testid at index {index}: '{data_testid}'"
				)

		return close_button_candidates

	def _find_modal_overlays(self, dom_state) -> list[tuple[int, str]]:
		"""Find modal overlay elements in the DOM.

		Returns list of (index, modal_type) tuples where modal_type can be:
		- "dialog": role="dialog" or role="alertdialog"
		- "overlay": fixed/absolute positioned overlay element
		- "modal": class or id containing "modal"
		"""
		modal_overlays = []

		if not dom_state or not dom_state.selector_map:
			return modal_overlays

		for index, element in dom_state.selector_map.items():
			# Strategy 1: Check role attribute
			role = element.attributes.get("role", "").lower()
			if role in ["dialog", "alertdialog"]:
				modal_overlays.append((index, "dialog"))
				self.logger.debug(f"Found modal overlay via role at index {index}: role='{role}'")
				continue

			# Strategy 2: Check class names and id for modal indicators
			class_names = (element.attributes.get("class", "") or "").lower()
			element_id = (element.attributes.get("id", "") or "").lower()
			combined = f"{class_names} {element_id}"

			if any(keyword in combined for keyword in ["modal", "popup", "overlay", "newsletter", "advertisement", "ad-"]):
				modal_overlays.append((index, "css-modal"))
				self.logger.debug(f"Found modal overlay via class/id at index {index}: '{combined}'")

		return modal_overlays

	async def _try_close_modal(self) -> bool:
		"""Try to find and close a modal overlay using direct browser access.

		Returns True if a modal was successfully closed, False otherwise.
		"""
		try:
			# Get the DOM state directly from the session without dispatching a new event
			if not self.browser_session.agent_focus:
				self.logger.debug("No agent focus session available for modal detection")
				return False

			cdp_session = self.browser_session.agent_focus

			# Get DOM snapshot directly
			try:
				result = await asyncio.wait_for(
					cdp_session.cdp_client.send.DOMSnapshot.captureSnapshot(
						params={'computedStyles': []},
						session_id=cdp_session.session_id,
					),
					timeout=5.0,
				)
			except asyncio.TimeoutError:
				self.logger.debug("DOMSnapshot capture timed out")
				return False
			except Exception as e:
				self.logger.debug(f"Failed to capture DOM snapshot: {e}")
				return False

			if not result or not result.get('strings'):
				return False

			# Build selector map from DOM snapshot (similar to DOMWatchdog)
			selector_map = {}
			try:
				# Parse the snapshot to find modal elements
				dom_nodes = result.get('documents', [])
				if not dom_nodes:
					return False

				# Simple DOM parsing to find modal indicators
				strings = result.get('strings', [])
				for node_info in dom_nodes:
					# Look for elements with role="dialog" or modal-like classes
					if isinstance(node_info, dict):
						# Check for modal indicators in node data
						node_str = str(node_info).lower()
						if 'dialog' in node_str or 'modal' in node_str:
							self.logger.debug("Found potential modal in DOM snapshot")
							# Try to close modals using JavaScript evaluation
							return await self._close_modal_via_js()

			except Exception as e:
				self.logger.debug(f"Error parsing DOM snapshot: {e}")
				# Fall back to JavaScript approach
				return await self._close_modal_via_js()

			return False

		except Exception as e:
			self.logger.error(f"❌ Error while trying to close modal: {type(e).__name__}: {e}")
			return False

	async def _close_modal_via_js(self) -> bool:
		"""Try to close modals using JavaScript evaluation.

		This is a fallback approach that:
		1. Finds visible modal/overlay elements
		2. Looks for close buttons
		3. Clicks them if found
		"""
		try:
			if not self.browser_session.agent_focus:
				return False

			cdp_session = self.browser_session.agent_focus

			# JavaScript to find and click close buttons on modals
			close_script = """
			(function() {
				// Find modal/overlay elements
				const modals = document.querySelectorAll('[role="dialog"], [role="alertdialog"], .modal, .popup, .overlay, [class*="modal"], [class*="popup"], [class*="overlay"]');
				if (modals.length === 0) return false;

				// Try to find and click close button
				for (const modal of modals) {
					if (modal.offsetHeight === 0 || modal.offsetWidth === 0) continue; // Skip hidden
					
					// Look for close button
					const closeBtn = modal.querySelector('[aria-label*="close" i], [aria-label*="dismiss" i], [class*="close"], [class*="dismiss"], button:contains("×"), button:contains("X"), button:contains("Close")');
					if (closeBtn && closeBtn.offsetHeight > 0) {
						closeBtn.click();
						return true;
					}

					// Try accept/agree buttons as fallback
					const acceptBtn = modal.querySelector('[aria-label*="accept" i], [aria-label*="agree" i], button:contains("Accept"), button:contains("Agree"), button:contains("OK")');
					if (acceptBtn && acceptBtn.offsetHeight > 0) {
						acceptBtn.click();
						return true;
					}
				}
				return false;
			})();
			"""

			try:
				result = await asyncio.wait_for(
					cdp_session.cdp_client.send.Runtime.evaluate(
						params={
							'expression': close_script,
							'returnByValue': True,
						},
						session_id=cdp_session.session_id,
					),
					timeout=3.0,
				)

				if result and result.get('result', {}).get('value') is True:
					self.logger.info("✅ Successfully closed modal via JavaScript")
					return True

			except Exception as e:
				self.logger.debug(f"JavaScript close attempt failed: {e}")

			return False

		except Exception as e:
			self.logger.error(f"Error in _close_modal_via_js: {e}")
			return False

	async def on_NavigateToUrlEvent(self, event: NavigateToUrlEvent) -> None:
		"""React to page navigation by attempting to close any modals that appear.

		This is called after navigation completes, allowing modals to appear and be closed.
		"""
		try:
			# Wait a bit for any modals to appear after navigation
			await asyncio.sleep(1.0)

			# Try to close modal if one is present
			closed = await self._try_close_modal()

			if closed:
				# Wait a moment for the modal to disappear from the DOM
				await asyncio.sleep(0.5)
				self.logger.info("Modal closed successfully after navigation")

		except Exception as e:
			self.logger.error(
				f"❌ Error in ModalOverlayWatchdog.on_NavigateToUrlEvent: {type(e).__name__}: {e}"
			)
