"""
Iframe handling for Selenium-based browser sessions.

This module provides utilities for interacting with iframes in Firefox and Safari
using Selenium WebDriver's switch_to.frame() mechanism.

Key capabilities:
- Full cross-origin iframe support (Selenium bypasses Same-Origin Policy)
- DOM extraction from ALL iframes via frame context switching
- Element interaction in any iframe regardless of origin
- Frame context tracking and restoration
- Nested iframe support

Note: Unlike JavaScript which is restricted by the browser's Same-Origin Policy,
Selenium WebDriver controls the browser at the automation level, giving it full
access to cross-origin iframe content.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Union

from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
	NoSuchFrameException,
	StaleElementReferenceException,
	TimeoutException,
	WebDriverException,
)

if TYPE_CHECKING:
	from selenium.webdriver.remote.webdriver import WebDriver
	from selenium.webdriver.remote.webelement import WebElement


@dataclass
class IframeInfo:
	"""Information about an iframe element."""
	
	selector: str  # CSS selector or xpath used to find the iframe
	index: int  # Index in parent's iframe list
	src: str  # iframe src attribute
	name: str  # iframe name attribute
	id: str  # iframe id attribute
	is_cross_origin: bool  # Whether src is from different origin (informational only - Selenium can still interact)
	location: dict  # x, y coordinates relative to page
	size: dict  # width, height of the iframe
	is_displayed: bool  # Whether the iframe is visible
	depth: int = 0  # Nesting depth (0 = top-level iframe)
	parent_selector: str | None = None  # Selector path to parent iframe (if nested)


@dataclass
class FrameContext:
	"""Tracks the current frame context for restoration."""
	
	stack: list[str] = field(default_factory=list)  # Stack of frame selectors
	is_default: bool = True  # Whether we're in the default/top content
	
	def push(self, selector: str) -> None:
		"""Push a frame selector onto the stack."""
		self.stack.append(selector)
		self.is_default = False
	
	def pop(self) -> str | None:
		"""Pop the last frame selector from the stack."""
		if self.stack:
			frame = self.stack.pop()
			self.is_default = len(self.stack) == 0
			return frame
		return None
	
	def clear(self) -> None:
		"""Clear the stack (return to default content)."""
		self.stack.clear()
		self.is_default = True
	
	def copy(self) -> 'FrameContext':
		"""Create a copy of the current context."""
		ctx = FrameContext()
		ctx.stack = self.stack.copy()
		ctx.is_default = self.is_default
		return ctx


class SeleniumIframeHandler:
	"""
	Handles iframe interactions for Selenium WebDriver.
	
	This handler provides full iframe support including cross-origin iframes.
	Unlike JavaScript which is restricted by Same-Origin Policy, Selenium WebDriver
	operates at the browser automation level (via WebDriver protocol), allowing it
	to access and interact with ALL iframe content regardless of origin.
	
	Capabilities:
	- Frame context switching with automatic stack tracking
	- Full DOM extraction from any iframe (including cross-origin)
	- Element interaction in any iframe (click, type, etc.)
	- Nested iframe support (iframes within iframes)
	- Context restoration after operations
	
	Usage:
		handler = SeleniumIframeHandler(driver)
		
		# Switch to an iframe
		await handler.switch_to_frame('iframe#login')
		# ... interact with elements inside iframe ...
		await handler.switch_to_default()
		
		# Execute within frame context (auto-restores)
		async with handler.frame_context('iframe#content'):
			element = driver.find_element(By.ID, 'submit')
			element.click()
	"""
	
	def __init__(
		self,
		driver: 'WebDriver',
		logger: logging.Logger | None = None,
		default_timeout: float = 5.0,  # Reduced from 10s for faster iframe processing
	):
		self.driver = driver
		self.logger = logger or logging.getLogger(__name__)
		self.default_timeout = default_timeout
		self._context = FrameContext()
		self._iframe_cache: dict[str, IframeInfo] = {}
		# Minimum iframe size to process (skip tracking pixels)
		self.min_iframe_width = 50
		self.min_iframe_height = 50
	
	# ==================== Frame Switching ====================
	
	async def switch_to_frame(
		self,
		frame: Union[str, int, 'WebElement'],
		timeout: float | None = None,
	) -> bool:
		"""
		Switch to an iframe by selector, index, or WebElement.
		
		Args:
			frame: CSS selector, frame index, or WebElement
			timeout: Timeout in seconds (default: self.default_timeout)
			
		Returns:
			True if switch was successful, False otherwise
		"""
		timeout = timeout or self.default_timeout
		
		try:
			if isinstance(frame, int):
				# Switch by index
				await asyncio.get_event_loop().run_in_executor(
					None,
					lambda: self.driver.switch_to.frame(frame)
				)
				self._context.push(f'index:{frame}')
				self.logger.debug(f'Switched to iframe by index: {frame}')
				
			elif isinstance(frame, str):
				# Switch by selector (CSS or XPath)
				iframe_element = await self._find_frame_element(frame, timeout)
				if iframe_element is None:
					self.logger.warning(f'Could not find iframe: {frame}')
					return False
				
				await asyncio.get_event_loop().run_in_executor(
					None,
					lambda: self.driver.switch_to.frame(iframe_element)
				)
				self._context.push(frame)
				self.logger.debug(f'Switched to iframe: {frame}')
				
			else:
				# Assume it's a WebElement
				await asyncio.get_event_loop().run_in_executor(
					None,
					lambda: self.driver.switch_to.frame(frame)
				)
				# For WebElements, use a generic marker
				self._context.push(f'element:{id(frame)}')
				self.logger.debug('Switched to iframe by WebElement')
			
			return True
			
		except (NoSuchFrameException, TimeoutException, StaleElementReferenceException) as e:
			self.logger.warning(f'Failed to switch to frame {frame}: {e}')
			return False
		except Exception as e:
			self.logger.error(f'Unexpected error switching to frame {frame}: {e}')
			return False
	
	async def switch_to_parent(self) -> bool:
		"""
		Switch to the parent frame.
		
		Returns:
			True if switch was successful, False if already at top level
		"""
		if self._context.is_default:
			return False
		
		try:
			await asyncio.get_event_loop().run_in_executor(
				None,
				self.driver.switch_to.parent_frame
			)
			self._context.pop()
			self.logger.debug('Switched to parent frame')
			return True
		except Exception as e:
			self.logger.warning(f'Failed to switch to parent frame: {e}')
			return False
	
	async def switch_to_default(self) -> None:
		"""Switch to the default (top-level) content."""
		try:
			await asyncio.get_event_loop().run_in_executor(
				None,
				self.driver.switch_to.default_content
			)
			self._context.clear()
			self.logger.debug('Switched to default content')
		except Exception as e:
			self.logger.warning(f'Failed to switch to default content: {e}')
	
	async def restore_context(self, context: FrameContext) -> bool:
		"""
		Restore a previously saved frame context.
		
		Args:
			context: The FrameContext to restore
			
		Returns:
			True if restoration was successful
		"""
		await self.switch_to_default()
		
		for frame_selector in context.stack:
			if frame_selector.startswith('index:'):
				idx = int(frame_selector.split(':')[1])
				success = await self.switch_to_frame(idx)
			elif frame_selector.startswith('element:'):
				# Cannot restore WebElement-based context
				self.logger.warning('Cannot restore WebElement-based frame context')
				return False
			else:
				success = await self.switch_to_frame(frame_selector)
			
			if not success:
				self.logger.warning(f'Failed to restore frame context at: {frame_selector}')
				return False
		
		return True
	
	def get_current_context(self) -> FrameContext:
		"""Get a copy of the current frame context."""
		return self._context.copy()
	
	@property
	def is_in_frame(self) -> bool:
		"""Check if currently inside an iframe."""
		return not self._context.is_default
	
	@property
	def frame_depth(self) -> int:
		"""Get the current frame nesting depth."""
		return len(self._context.stack)
	
	# ==================== Iframe Discovery ====================
	
	async def get_all_iframes(
		self,
		include_nested: bool = True,
		max_depth: int = 5,
	) -> list[IframeInfo]:
		"""
		Get information about all iframes on the page.
		
		Uses optimized batch collection to minimize WebDriver round-trips.
		
		Args:
			include_nested: Whether to include nested iframes
			max_depth: Maximum nesting depth to traverse
			
		Returns:
			List of IframeInfo objects
		"""
		# Save current context
		saved_context = self.get_current_context()
		
		try:
			await self.switch_to_default()
			
			# Use fast batch collection for top-level iframes (single JS call)
			iframes = await self._collect_iframes_batch()
			
			# Only recursively collect nested iframes if requested and there are iframes
			if include_nested and max_depth > 1 and iframes:
				nested_iframes = await self._collect_nested_iframes_optimized(
					top_level_iframes=iframes,
					max_depth=max_depth,
				)
				iframes.extend(nested_iframes)
			
			return iframes
		finally:
			# Restore context
			await self.restore_context(saved_context)
	
	async def _collect_iframes_recursive(
		self,
		parent_selector: str | None,
		current_depth: int,
		max_depth: int,
	) -> list[IframeInfo]:
		"""Recursively collect iframe information from ALL iframes (including cross-origin)."""
		if current_depth >= max_depth:
			return []
		
		iframes: list[IframeInfo] = []
		
		try:
			# Find all iframes in current context
			iframe_elements = await asyncio.get_event_loop().run_in_executor(
				None,
				lambda: self.driver.find_elements(By.TAG_NAME, 'iframe')
			)
			
			for idx, iframe_elem in enumerate(iframe_elements):
				try:
					info = await self._get_iframe_info(
						iframe_elem,
						index=idx,
						depth=current_depth,
						parent_selector=parent_selector,
					)
					if info:
						iframes.append(info)
						
						# Recurse into ALL iframes - Selenium can access cross-origin frames
						# Build selector for this iframe
						selector = self._build_iframe_selector(info)
						if await self.switch_to_frame(iframe_elem):
							nested = await self._collect_iframes_recursive(
								parent_selector=selector,
								current_depth=current_depth + 1,
								max_depth=max_depth,
							)
							iframes.extend(nested)
							await self.switch_to_parent()
								
				except StaleElementReferenceException:
					self.logger.debug(f'Iframe {idx} became stale during collection')
					continue
					
		except Exception as e:
			self.logger.warning(f'Error collecting iframes at depth {current_depth}: {e}')
		
		return iframes

	async def _collect_iframes_batch(self) -> list[IframeInfo]:
		"""
		Batch-collect all top-level iframe metadata in a single JavaScript call.
		
		This is MUCH faster than iterating through iframes one by one, especially
		over remote connections like SauceLabs where each WebDriver call has latency.
		
		Returns:
			List of IframeInfo objects for all top-level iframes
		"""
		try:
			# Single JavaScript call to collect ALL iframe metadata at once
			batch_script = '''
				const iframes = document.querySelectorAll('iframe');
				const results = [];
				
				for (let i = 0; i < iframes.length; i++) {
					const iframe = iframes[i];
					const rect = iframe.getBoundingClientRect();
					
					// Get computed style to check visibility
					const style = window.getComputedStyle(iframe);
					const isVisible = style.display !== 'none' && 
					                  style.visibility !== 'hidden' && 
					                  rect.width > 0 && 
					                  rect.height > 0;
					
					results.push({
						index: i,
						src: iframe.src || '',
						name: iframe.name || '',
						id: iframe.id || '',
						className: iframe.className || '',
						title: iframe.title || '',
						x: Math.round(rect.x),
						y: Math.round(rect.y),
						width: Math.round(rect.width),
						height: Math.round(rect.height),
						isDisplayed: isVisible
					});
				}
				
				return results;
			'''
			
			iframe_data_list = await asyncio.get_event_loop().run_in_executor(
				None,
				lambda: self.driver.execute_script(batch_script)
			)
			
			if not iframe_data_list:
				return []
			
			# Convert to IframeInfo objects
			iframes: list[IframeInfo] = []
			current_url = self.driver.current_url
			
			for data in iframe_data_list:
				# Determine if cross-origin
				iframe_src = data.get('src', '')
				is_cross_origin = self._check_cross_origin_from_url(current_url, iframe_src)
				
				# Build selector
				attrs = {
					'id': data.get('id', ''),
					'name': data.get('name', ''),
					'title': data.get('title', ''),
					'class': data.get('className', ''),
					'src': iframe_src,
				}
				selector = self._build_selector_for_element(attrs, data.get('index', 0))
				
				info = IframeInfo(
					selector=selector,
					index=data.get('index', 0),
					src=iframe_src,
					name=data.get('name', ''),
					id=data.get('id', ''),
					is_cross_origin=is_cross_origin,
					location={'x': data.get('x', 0), 'y': data.get('y', 0)},
					size={'width': data.get('width', 0), 'height': data.get('height', 0)},
					is_displayed=data.get('isDisplayed', False),
					depth=0,
					parent_selector=None,
				)
				iframes.append(info)
			
			self.logger.debug(f'Batch-collected {len(iframes)} top-level iframes in single JS call')
			return iframes
			
		except Exception as e:
			self.logger.warning(f'Error in batch iframe collection: {e}')
			# Fallback to old method
			return await self._collect_iframes_recursive(
				parent_selector=None,
				current_depth=0,
				max_depth=1,
			)

	async def _collect_nested_iframes_optimized(
		self,
		top_level_iframes: list[IframeInfo],
		max_depth: int,
	) -> list[IframeInfo]:
		"""
		Collect nested iframes with optimized batch processing per level.
		
		Instead of switching in/out of each iframe individually, this method:
		1. Switches to each processable iframe once
		2. Batch-collects ALL nested iframes in that frame via JS
		3. Switches back and continues
		
		This reduces WebDriver round-trips significantly.
		
		Args:
			top_level_iframes: List of top-level IframeInfo objects
			max_depth: Maximum nesting depth to traverse
			
		Returns:
			List of nested IframeInfo objects (does not include top-level)
		"""
		all_nested: list[IframeInfo] = []
		
		# Filter to only processable iframes (visible, reasonable size)
		processable = [
			iframe for iframe in top_level_iframes
			if iframe.is_displayed
			and iframe.size.get('width', 0) >= self.min_iframe_width
			and iframe.size.get('height', 0) >= self.min_iframe_height
		]
		
		if not processable:
			return all_nested
		
		# Process each level
		current_level = processable
		current_depth = 1
		
		while current_level and current_depth < max_depth:
			next_level: list[IframeInfo] = []
			
			for iframe in current_level:
				try:
					# Switch to this iframe
					await self.switch_to_default()
					
					# Navigate to parent iframes first if nested
					if iframe.parent_selector:
						# This is a nested iframe, need to switch through parent chain
						parent_chain = self._get_parent_chain(iframe)
						for parent_selector in parent_chain:
							if not await self.switch_to_frame(parent_selector, timeout=2.0):
								self.logger.debug(f'Could not switch to parent {parent_selector}')
								continue
					
					if not await self.switch_to_frame(iframe.selector, timeout=2.0):
						self.logger.debug(f'Could not switch to iframe {iframe.selector} for nested collection')
						continue
					
					# Batch-collect nested iframes in this frame
					nested_in_frame = await self._collect_iframes_batch()
					
					# Update depth and parent info for nested iframes
					for nested in nested_in_frame:
						nested.depth = current_depth
						nested.parent_selector = self._build_iframe_selector(iframe)
						all_nested.append(nested)
						next_level.append(nested)
					
				except Exception as e:
					self.logger.debug(f'Error collecting nested iframes from {iframe.selector}: {e}')
					continue
			
			current_level = next_level
			current_depth += 1
		
		# Return to default content
		await self.switch_to_default()
		
		self.logger.debug(f'Collected {len(all_nested)} nested iframes up to depth {max_depth}')
		return all_nested

	def _get_parent_chain(self, iframe: IframeInfo) -> list[str]:
		"""Get the chain of parent iframe selectors for a nested iframe."""
		if not iframe.parent_selector:
			return []
		
		# Split the parent selector chain (e.g., "iframe#outer > iframe#inner")
		# This is a simplified approach - full implementation would track the actual chain
		parts = iframe.parent_selector.split(' > ')
		return parts

	def _check_cross_origin_from_url(self, current_url: str, iframe_src: str) -> bool:
		"""Check if iframe src is cross-origin based on URL comparison."""
		if not iframe_src or iframe_src.startswith('about:') or iframe_src.startswith('javascript:'):
			return False
		
		try:
			from urllib.parse import urlparse
			current_origin = urlparse(current_url)
			iframe_origin = urlparse(iframe_src)
			
			return (
				current_origin.scheme != iframe_origin.scheme or
				current_origin.netloc != iframe_origin.netloc
			)
		except Exception:
			return True

	async def _get_iframe_info(
		self,
		element: 'WebElement',
		index: int,
		depth: int,
		parent_selector: str | None,
	) -> IframeInfo | None:
		"""Get information about a single iframe element."""
		try:
			def get_attrs():
				return {
					'src': element.get_attribute('src') or '',
					'name': element.get_attribute('name') or '',
					'id': element.get_attribute('id') or '',
					'class': element.get_attribute('class') or '',
					'title': element.get_attribute('title') or '',
					'location': element.location,
					'size': element.size,
					'is_displayed': element.is_displayed(),
				}
			
			attrs = await asyncio.get_event_loop().run_in_executor(None, get_attrs)
			
			# Check if cross-origin by trying to access content
			is_cross_origin = await self._check_cross_origin(element)
			
			# Build a selector for this iframe
			selector = self._build_selector_for_element(attrs, index)
			
			return IframeInfo(
				selector=selector,
				index=index,
				src=attrs['src'],
				name=attrs['name'],
				id=attrs['id'],
				is_cross_origin=is_cross_origin,
				location=attrs['location'],
				size=attrs['size'],
				is_displayed=attrs['is_displayed'],
				depth=depth,
				parent_selector=parent_selector,
			)
			
		except Exception as e:
			self.logger.debug(f'Error getting iframe info: {e}')
			return None
	
	async def _check_cross_origin(self, iframe_element: 'WebElement') -> bool:
		"""
		Check if an iframe's src is from a different origin.
		
		Note: This is informational only. Selenium WebDriver can still fully interact
		with cross-origin iframes because it operates at the browser automation level,
		bypassing the Same-Origin Policy that restricts JavaScript.
		
		Returns:
			True if the iframe src is from a different origin, False if same-origin
		"""
		try:
			def check_origin():
				iframe_src = iframe_element.get_attribute('src') or ''
				if not iframe_src or iframe_src.startswith('about:') or iframe_src.startswith('javascript:'):
					return False  # No src or special protocol = same origin context
				
				current_url = self.driver.current_url
				
				# Parse origins
				from urllib.parse import urlparse
				current_origin = urlparse(current_url)
				iframe_origin = urlparse(iframe_src)
				
				# Compare scheme, host, and port
				return (
					current_origin.scheme != iframe_origin.scheme or
					current_origin.netloc != iframe_origin.netloc
				)
			
			return await asyncio.get_event_loop().run_in_executor(None, check_origin)
			
		except Exception:
			return True  # Assume cross-origin if we can't determine
	
	def _build_selector_for_element(self, attrs: dict, index: int = 0) -> str:
		"""Build a CSS selector for an iframe based on its attributes."""
		# Priority 1: ID (most reliable if present)
		if attrs.get('id'):
			iframe_id = attrs['id']
			# Check if ID contains characters that need escaping in CSS selectors
			special_chars = '.#[]>+~=^$*|/\\() '
			if any(c in iframe_id for c in special_chars):
				# Use attribute selector for IDs with special characters
				escaped_id = iframe_id.replace("'", "\\'")
				return f"iframe[id='{escaped_id}']"
			else:
				return f"iframe#{iframe_id}"
		
		# Priority 2: Name attribute
		elif attrs.get('name'):
			name = attrs['name'].replace("'", "\\'")
			return f"iframe[name='{name}']"
		
		# Priority 3: Title attribute
		elif attrs.get('title'):
			title = attrs['title'].replace("'", "\\'")
			return f"iframe[title='{title}']"
		
		# Priority 4: Unique class
		elif attrs.get('class'):
			cls = attrs['class'].strip()
			if cls and ' ' not in cls:  # Single class, more reliable
				return f"iframe.{cls}"
			elif cls:
				# Multiple classes - use first one with attribute selector
				first_class = cls.split()[0]
				return f"iframe.{first_class}"
		
		# Priority 5: Src-based selector (use domain only for reliability)
		elif attrs.get('src'):
			src = attrs['src']
			try:
				from urllib.parse import urlparse
				parsed = urlparse(src)
				if parsed.netloc:
					# Use domain-based partial match (more reliable than full URL)
					return f"iframe[src*='{parsed.netloc}']"
			except Exception:
				pass
			# Fallback: use first 60 chars of src path
			base_src = src.split('?')[0].split('#')[0][:60]
			escaped_src = base_src.replace("'", "\\'")
			return f"iframe[src*='{escaped_src}']"
		
		# Priority 6: Index-based (last resort, but always works)
		# Use CSS :nth-of-type selector
		return f"iframe:nth-of-type({index + 1})"
	
	def _build_iframe_selector(self, info: IframeInfo) -> str:
		"""Build a unique selector path for an iframe."""
		if info.parent_selector:
			return f"{info.parent_selector} > {info.selector}"
		return info.selector
	
	# ==================== Iframe Interaction ====================
	
	async def find_in_frame(
		self,
		frame_selector: str,
		element_selector: str,
		by: str = By.CSS_SELECTOR,
	) -> 'WebElement | None':
		"""
		Find an element within a specific iframe.
		
		Args:
			frame_selector: Selector for the iframe
			element_selector: Selector for the element within the iframe
			by: Locator strategy (default: CSS_SELECTOR)
			
		Returns:
			WebElement if found, None otherwise
		"""
		saved_context = self.get_current_context()
		
		try:
			await self.switch_to_default()
			
			if not await self.switch_to_frame(frame_selector):
				return None
			
			element = await asyncio.get_event_loop().run_in_executor(
				None,
				lambda: self.driver.find_element(by, element_selector)
			)
			return element
			
		except Exception as e:
			self.logger.debug(f'Error finding element in frame: {e}')
			return None
		finally:
			await self.restore_context(saved_context)
	
	async def click_in_frame(
		self,
		frame_selector: str,
		element_selector: str,
		by: str = By.CSS_SELECTOR,
	) -> bool:
		"""
		Click an element within a specific iframe.
		
		Args:
			frame_selector: Selector for the iframe
			element_selector: Selector for the element to click
			by: Locator strategy (default: CSS_SELECTOR)
			
		Returns:
			True if click was successful
		"""
		saved_context = self.get_current_context()
		
		try:
			await self.switch_to_default()
			
			if not await self.switch_to_frame(frame_selector):
				return False
			
			element = await asyncio.get_event_loop().run_in_executor(
				None,
				lambda: self.driver.find_element(by, element_selector)
			)
			
			await asyncio.get_event_loop().run_in_executor(
				None,
				element.click
			)
			
			self.logger.debug(f'Clicked element {element_selector} in frame {frame_selector}')
			return True
			
		except Exception as e:
			self.logger.warning(f'Error clicking in frame: {e}')
			return False
		finally:
			await self.restore_context(saved_context)
	
	async def type_in_frame(
		self,
		frame_selector: str,
		element_selector: str,
		text: str,
		clear_first: bool = True,
		by: str = By.CSS_SELECTOR,
	) -> bool:
		"""
		Type text into an element within a specific iframe.
		
		Args:
			frame_selector: Selector for the iframe
			element_selector: Selector for the input element
			text: Text to type
			clear_first: Whether to clear the field first
			by: Locator strategy (default: CSS_SELECTOR)
			
		Returns:
			True if typing was successful
		"""
		saved_context = self.get_current_context()
		
		try:
			await self.switch_to_default()
			
			if not await self.switch_to_frame(frame_selector):
				return False
			
			element = await asyncio.get_event_loop().run_in_executor(
				None,
				lambda: self.driver.find_element(by, element_selector)
			)
			
			def do_type():
				if clear_first:
					element.clear()
				element.send_keys(text)
			
			await asyncio.get_event_loop().run_in_executor(None, do_type)
			
			self.logger.debug(f'Typed into element {element_selector} in frame {frame_selector}')
			return True
			
		except Exception as e:
			self.logger.warning(f'Error typing in frame: {e}')
			return False
		finally:
			await self.restore_context(saved_context)
	
	async def execute_in_frame(
		self,
		frame_selector: str,
		script: str,
		*args,
	) -> Any:
		"""
		Execute JavaScript within a specific iframe.
		
		Selenium WebDriver can execute scripts in ANY iframe, including cross-origin
		iframes, because it operates at the browser automation level and bypasses
		the Same-Origin Policy.
		
		Args:
			frame_selector: Selector for the iframe
			script: JavaScript code to execute
			*args: Arguments to pass to the script
			
		Returns:
			Result of the script execution, or None on error
		"""
		saved_context = self.get_current_context()
		
		try:
			await self.switch_to_default()
			
			if not await self.switch_to_frame(frame_selector):
				return None
			
			result = await asyncio.get_event_loop().run_in_executor(
				None,
				lambda: self.driver.execute_script(script, *args)
			)
			return result
			
		except WebDriverException as e:
			self.logger.warning(f'Error executing script in frame: {e}')
			return None
		finally:
			await self.restore_context(saved_context)
	
	# ==================== Cross-Origin Iframe Handling ====================
	
	async def click_cross_origin_iframe(
		self,
		frame_selector: str,
		x_offset: int = 0,
		y_offset: int = 0,
	) -> bool:
		"""
		Click within a cross-origin iframe using coordinate-based clicking.
		
		Args:
			frame_selector: Selector for the iframe
			x_offset: X offset from iframe's top-left corner
			y_offset: Y offset from iframe's top-left corner
			
		Returns:
			True if click was performed
		"""
		try:
			await self.switch_to_default()
			
			iframe = await self._find_frame_element(frame_selector)
			if iframe is None:
				return False
			
			def do_click():
				actions = ActionChains(self.driver)
				actions.move_to_element_with_offset(iframe, x_offset, y_offset)
				actions.click()
				actions.perform()
			
			await asyncio.get_event_loop().run_in_executor(None, do_click)
			
			self.logger.debug(f'Clicked cross-origin iframe {frame_selector} at offset ({x_offset}, {y_offset})')
			return True
			
		except Exception as e:
			self.logger.warning(f'Error clicking cross-origin iframe: {e}')
			return False
	
	
	
	# ==================== Helper Methods ====================
	
	async def _find_frame_element(
		self,
		selector: str,
		timeout: float | None = None,
	) -> 'WebElement | None':
		"""Find an iframe element by selector with wait."""
		timeout = timeout or self.default_timeout
		
		try:
			wait = WebDriverWait(self.driver, timeout)
			
			# Determine if selector is CSS or XPath
			if selector.startswith('/') or selector.startswith('('):
				locator = (By.XPATH, selector)
			else:
				locator = (By.CSS_SELECTOR, selector)
			
			iframe = await asyncio.get_event_loop().run_in_executor(
				None,
				lambda: wait.until(EC.presence_of_element_located(locator))
			)
			return iframe
			
		except TimeoutException:
			self.logger.debug(f'Timeout waiting for iframe: {selector}')
			return None
		except Exception as e:
			self.logger.debug(f'Error finding iframe {selector}: {e}')
			return None
	
	# ==================== Context Manager ====================
	
	class FrameContextManager:
		"""Context manager for automatic frame switching and restoration."""
		
		def __init__(self, handler: 'SeleniumIframeHandler', frame_selector: str):
			self.handler = handler
			self.frame_selector = frame_selector
			self.saved_context: FrameContext | None = None
			self.switched = False
		
		async def __aenter__(self):
			self.saved_context = self.handler.get_current_context()
			self.switched = await self.handler.switch_to_frame(self.frame_selector)
			if not self.switched:
				raise ValueError(f'Failed to switch to frame: {self.frame_selector}')
			return self.handler
		
		async def __aexit__(self, exc_type, exc_val, exc_tb):
			if self.saved_context:
				await self.handler.restore_context(self.saved_context)
	
	def frame_context(self, frame_selector: str) -> 'FrameContextManager':
		"""
		Create a context manager for temporary frame switching.
		
		Usage:
			async with handler.frame_context('iframe#login'):
				# Operations inside iframe
				element = driver.find_element(By.ID, 'username')
				element.send_keys('user')
			# Automatically restored to previous context
		"""
		return self.FrameContextManager(self, frame_selector)
