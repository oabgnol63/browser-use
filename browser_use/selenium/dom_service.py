"""
Selenium-based DOM service for Firefox and Safari browsers.

This service uses Selenium's execute_script() with JavaScript injection to extract
DOM elements, reusing the same index.js script as PlaywrightDomService.

Enhanced iframe support:
- Full cross-origin iframe DOM extraction via frame context switching
- Selenium WebDriver bypasses Same-Origin Policy at the automation level
- Nested iframe traversal with automatic context management
"""

import asyncio
import logging
import time
from importlib import resources
from typing import TYPE_CHECKING

from browser_use.dom.views import (
    DOMRect,
    EnhancedAXNode,
    EnhancedDOMTreeNode,
    EnhancedSnapshotNode,
    NodeType,
    SerializedDOMState,
)
from browser_use.dom.serializer.serializer import DOMTreeSerializer
from browser_use.utils import time_execution_async

if TYPE_CHECKING:
    from selenium.webdriver.remote.webdriver import WebDriver

from browser_use.selenium.iframe_handler import SeleniumIframeHandler, IframeInfo


class SeleniumDomService:
    """
    DOM service for Firefox and Safari browsers using Selenium JavaScript evaluation.
    
    This service injects JavaScript into the page to extract DOM elements and their properties,
    then converts the results to EnhancedDOMTreeNode format for compatibility with the rest
    of the browser-use codebase.
    
    Uses the same index.js script as PlaywrightDomService for consistent DOM extraction.
    
    Enhanced iframe support:
    - Full DOM extraction from ALL iframes (including cross-origin)
    - Selenium WebDriver bypasses browser Same-Origin Policy
    - Automatic frame context switching and restoration
    """

    logger: logging.Logger

    def __init__(
        self,
        driver: 'WebDriver',
        logger: logging.Logger | None = None,
        paint_order_filtering: bool = True,
        skip_processing_iframes: bool = False,
        compact_mode: bool = True,  # Default True for Selenium to reduce data transfer
    ):
        self.driver = driver
        self.logger = logger or logging.getLogger(__name__)
        self.paint_order_filtering = paint_order_filtering
        self.skip_processing_iframes = skip_processing_iframes
        self.compact_mode = compact_mode
        
        # Initialize iframe handler for frame context management
        self.iframe_handler = SeleniumIframeHandler(driver, logger=self.logger)

        # Load the JavaScript code for DOM extraction (same as PlaywrightDomService)
        raw_js_code = resources.files('browser_use.dom').joinpath('dom_tree_js', 'index.js').read_text(encoding='utf-8').strip()
        if raw_js_code.startswith('﻿'):
            raw_js_code = raw_js_code[1:]  # Remove UTF-8 BOM if present
        if raw_js_code.endswith(';'):
            raw_js_code = raw_js_code[:-1]
        # Don't wrap with 'return' here - execute_script handles that
        self.js_code = raw_js_code
        self.logger.debug(f'JavaScript code loaded, length: {len(self.js_code)} chars')

        # Inject stealth JS once at initialization time
        # This only needs to be done once per browser session
        self._stealth_injected = False

    async def __aenter__(self):
        # Note: Stealth preferences are already applied at browser launch time
        # via FIREFOX_STEALTH_PREFS when stealth=True (the default).
        # No need to inject JS here - browser preferences handle it.
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        pass

    async def inject_stealth_js(self) -> None:
        """
        Inject JavaScript to hide automation flags at runtime.

        This complements browser preferences by patching navigator properties
        that may still be detectable after browser launch.

        Note: This is called once at initialization time via __aenter__.
        The injection persists across page navigations within the same session.
        """
        # Only inject once per session - stealth JS persists across navigations
        if getattr(self, '_stealth_injected', False):
            self.logger.debug('Stealth JS already injected, skipping')
            return

        self.logger.debug('Injecting stealth JavaScript...')
        try:
            self.driver.execute_script('''
                // Hide navigator.webdriver flag
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined,
                    configurable: true,
                    enumerable: true
                });

                // Remove from prototype chain as well
                try {
                    delete navigator.__proto__.webdriver;
                } catch (e) {
                    // May fail in some browsers, that's okay
                }

                // Add fake plugins to match real browser fingerprint
                Object.defineProperty(navigator, 'plugins', {
                    get: () => [1, 2, 3, 4, 5],
                    configurable: true
                });

                // Spoof MIME types
                Object.defineProperty(navigator, 'mimeTypes', {
                    get: () => ({
                        length: 3,
                        0: { type: 'application/pdf', suffixes: 'pdf', description: 'PDF Viewer' },
                        1: { type: 'application/x-shockwave-flash', suffixes: 'swf', description: 'Shockwave Flash' },
                        2: { type: 'text/html', suffixes: 'html', description: 'HTML Document' }
                    }),
                    configurable: true
                });
            ''')
            self._stealth_injected = True
            self.logger.debug('Stealth JavaScript injected successfully')
        except Exception as e:
            self.logger.warning(f'Failed to inject stealth JS: {e}')

    @time_execution_async('--selenium_get_dom_tree')
    async def get_dom_tree(
        self,
        highlight_elements: bool = True,
        focus_element: int = -1,
        viewport_expansion: int = 0,  # Keep at 0 - agent will scroll to find off-screen elements
        cross_origin_iframes: bool = True,
        max_iframe_depth: int = 5,
        max_iframes: int = 100,
        skip_processing_iframes: bool = False,
    ) -> tuple[EnhancedDOMTreeNode, dict[int, EnhancedDOMTreeNode], dict[str, float]]:
        """
        Get the DOM tree using Selenium JavaScript evaluation.

        Args:
            highlight_elements: Whether to highlight interactive elements
            focus_element: Index of element to focus highlight on (-1 for none)
            viewport_expansion: Pixels to expand viewport for element detection (default 500px)
            cross_origin_iframes: Include cross-origin iframes (marked as such)
            max_iframe_depth: Maximum depth for iframe recursion
            max_iframes: Maximum number of iframes to process
            skip_processing_iframes: Skip iframe discovery and DOM extraction from iframes,
                returning only the main page DOM

        Returns:
            Tuple of (root_node, selector_map, timing_info)
        """
        # Use instance-level setting as default if not explicitly provided
        if skip_processing_iframes is False and self.skip_processing_iframes:
            skip_processing_iframes = True
        timing_info: dict[str, float] = {}
        start_time = time.time()

        # Check for empty/new tab pages
        current_url = self.driver.current_url
        if self._is_new_tab_page(current_url):
            empty_root = self._create_empty_root_node()
            return empty_root, {}, {'total_ms': (time.time() - start_time) * 1000}

        # Execute the DOM extraction JavaScript
        # NOTE: We disable JS highlights here and draw them after serialization
        # using the actual selector_map indices to ensure visual indices match agent indices
        debug_mode = self.logger.getEffectiveLevel() == logging.DEBUG
        args = {
            'doHighlightElements': False,  # Draw highlights after serialization instead
            'focusHighlightIndex': focus_element,
            'viewportExpansion': viewport_expansion,
            'debugMode': debug_mode,
            'maxIframeDepth': max_iframe_depth,
            'maxIframes': max_iframes,
            'includeCrossOriginIframes': cross_origin_iframes,
            'compactMode': self.compact_mode,  # Reduce data transfer by only returning essential nodes
        }

        try:
            start_js = time.time()
            url_short = current_url[:50] + '...' if len(current_url) > 50 else current_url
            self.logger.debug(f'Starting Selenium JavaScript DOM analysis for {url_short}...')
            
            # Execute the JavaScript with arguments
            # self.js_code is an arrow function (args) => {...}
            # We wrap it in parentheses and invoke with arguments[0]
            # Note: args dict is passed as the second argument, accessible as arguments[0]
            self.logger.debug(f'Executing JS with args: {args}')
            self.logger.debug(f'JS code length: {len(self.js_code)} chars')


            # Execute the main DOM extraction script
            # The IIFE pattern needs 'return' prefix for Selenium execute_script to capture the result
            try:
                eval_result: dict = self.driver.execute_script(f'return ({self.js_code})(arguments[0])', args)
            except Exception as js_error:
                self.logger.warning(f'DOM extraction JS failed: {js_error}')
                return self._create_empty_root_node(), {}, {'total_ms': (time.time() - start_time) * 1000}
            timing_info['js_evaluation_ms'] = (time.time() - start_js) * 1000
            self.logger.debug('Selenium JavaScript DOM analysis completed')
        except Exception as e:
            self.logger.error(f'Error evaluating JavaScript: {e}')
            raise

        # Convert JavaScript result to EnhancedDOMTreeNode tree
        start_construct = time.time()
        root_node, selector_map = self._construct_dom_tree(eval_result or {})
        timing_info['tree_construction_ms'] = (time.time() - start_construct) * 1000

        # DIAGNOSTIC: Log selector map stats
        self.logger.debug(f'Selenium DOM: selector_map has {len(selector_map)} entries')
        if selector_map:
            max_key = max(selector_map.keys()) if selector_map else 0
            self.logger.debug(f'Selenium DOM: max selector_map key={max_key}')
            # Log sample entries
            sample_keys = list(selector_map.keys())[:5]
            for k in sample_keys:
                node = selector_map[k]
                self.logger.debug(f'  Selector map[{k}]: tag={node.tag_name} highlight_index={getattr(node, "highlight_index", None)}')

        timing_info['total_ms'] = (time.time() - start_time) * 1000
        return root_node, selector_map, timing_info

    async def get_serialized_dom_tree(
        self,
        highlight_elements: bool = True,
        previous_cached_state: SerializedDOMState | None = None,
        session_id: str | None = None,
        skip_processing_iframes: bool = False,
    ) -> tuple[SerializedDOMState, EnhancedDOMTreeNode, dict[int, EnhancedDOMTreeNode], dict[str, float]]:
        """
        Get the serialized DOM tree representation for LLM consumption.
        
        Args:
            highlight_elements: Whether to highlight interactive elements
            previous_cached_state: Previous DOM state for caching/diffing
            session_id: Optional session identifier for serialization
            skip_processing_iframes: Skip iframe discovery and DOM extraction from iframes
            
        Returns:
            Tuple of (serialized_dom_state, enhanced_dom_tree_root, timing_info)
        """
        timing_info: dict[str, float] = {}
        start_total = time.time()

        # Build DOM tree (js_selector_map comes from JavaScript's highlightIndex)
        enhanced_dom_tree, js_selector_map, dom_tree_timing = await self.get_dom_tree(
            highlight_elements=highlight_elements,
            skip_processing_iframes=skip_processing_iframes,
        )
        timing_info.update(dom_tree_timing)

        # Serialize DOM tree for LLM
        start_serialize = time.time()
        serialized_dom_state, serializer_timing = DOMTreeSerializer(
            enhanced_dom_tree,
            previous_cached_state,
            paint_order_filtering=self.paint_order_filtering,
            session_id=session_id,
            force_contiguous_indices=False,  # Don't use serializer indexing - JS already filtered correctly
        ).serialize_accessible_elements()

        # IMPORTANT: For Selenium, use JS selector_map directly!
        # The JavaScript already did correct filtering and assigned indices to innermost elements
        # The serializer's indexing adds back all parent elements, causing overlaps
        final_selector_map = js_selector_map
        
        # Debug: Compare JS selector map vs serializer's selector map
        if self.logger.getEffectiveLevel() == logging.DEBUG:
            self.logger.debug(f'==================== SELECTOR MAP COMPARISON ====================')
            self.logger.debug(f'JS selector_map: {len(js_selector_map)} elements (using this)')
            self.logger.debug(f'Serializer selector_map: {len(serialized_dom_state.selector_map)} elements (ignoring)')
            
            if len(js_selector_map) != len(serialized_dom_state.selector_map):
                self.logger.debug(f'⚠️  Serializer tried to add {len(serialized_dom_state.selector_map) - len(js_selector_map)} elements - using JS map instead')
            
            self.logger.debug(f'Using JS selector_map elements:')
            for idx in sorted(js_selector_map.keys()):  # Show first 20
                node = js_selector_map[idx]
                tag = node.tag_name if hasattr(node, 'tag_name') else node.node_name
                classes = node.attributes.get('class', '')[:30] if hasattr(node, 'attributes') else ''
                text = ''
                if hasattr(node, 'ax_node') and node.ax_node and node.ax_node.name:
                    text = node.ax_node.name[:50]
                elif hasattr(node, 'node_value') and node.node_value:
                    text = node.node_value[:50]
                self.logger.debug(f'  Index {idx}: {tag}.{classes} "{text}"')

        # Update the serialized state to use our JS selector map
        serialized_dom_state.selector_map = final_selector_map
        
        # Build node-to-selector-index mapping from the JS selector_map
        # This allows views.py to show correct indices in the serialized output
        serialized_dom_state._node_to_selector_index = {id(node): idx for idx, node in final_selector_map.items()}

        # Draw highlights with the same indices that the agent will use
        if highlight_elements:
            await self.draw_highlights(final_selector_map, focus_element=-1)

        # Add serializer sub-timings
        for key, value in serializer_timing.items():
            timing_info[f'{key}_ms'] = value * 1000

        timing_info['serialization_total_ms'] = (time.time() - start_serialize) * 1000
        timing_info['get_serialized_dom_tree_total_ms'] = (time.time() - start_total) * 1000

        # Return the serializer's selector_map (not js_selector_map) for consistency
        return serialized_dom_state, enhanced_dom_tree, final_selector_map, timing_info

    async def draw_highlights(
        self,
        selector_map: dict[int, EnhancedDOMTreeNode],
        focus_element: int = -1,
    ) -> None:
        """
        Draw highlight overlays on elements using the actual selector_map indices.
        
        This ensures visual indices match what the agent sees.
        Uses improved positioning logic similar to python_highlights.py.
        
        Args:
            selector_map: Map of selector indices to DOM nodes
            focus_element: Index of element to focus highlight on (-1 for none)
        """
        if not selector_map:
            return

        # Color scheme matching python_highlights.py
        element_colors = {
            'button': '#FF6B6B',
            'input': '#4ECDC4',
            'select': '#45B7D1',
            'a': '#96CEB4',
            'textarea': '#FF8C42',
            'default': '#DDA0DD',
        }

        # Build highlight data with correct indices
        highlights = []
        for index, node in selector_map.items():
            if node and node.snapshot_node and node.snapshot_node.bounds:
                bounds = node.snapshot_node.bounds
                is_focused = (focus_element == index)
                tag_name = node.tag_name.lower() if hasattr(node, 'tag_name') else 'div'
                
                # Get color based on element type
                color = element_colors.get(tag_name, element_colors['default'])
                
                highlights.append({
                    'index': index,
                    'x': bounds.x,
                    'y': bounds.y,
                    'width': bounds.width,
                    'height': bounds.height,
                    'isFocused': is_focused,
                    'color': color,
                    'tagName': tag_name,
                })

        if not highlights:
            return

        # Execute JavaScript to draw highlights with improved positioning
        try:
            self.driver.execute_script('''
                const containerId = 'browser-use-selenium-highlight-container';
                let container = document.getElementById(containerId);
                if (container) {
                    container.remove();
                }
                
                container = document.createElement('div');
                container.id = containerId;
                container.style.cssText = 'position:fixed;top:0;left:0;width:100%;height:100%;pointer-events:none;z-index:2147483647;';
                document.body.appendChild(container);
                
                const highlights = arguments[0];
                const viewportWidth = window.innerWidth;
                const viewportHeight = window.innerHeight;
                
                highlights.forEach(function(h) {
                    const el = document.createElement('div');
                    
                    // Use dashed border for better visibility
                    el.style.cssText = 'position:fixed;left:' + h.x + 'px;top:' + h.y + 'px;width:' + h.width + 'px;height:' + h.height + 'px;' +
                        'border:2px dashed ' + h.color + ';' +
                        'box-sizing:border-box;pointer-events:none;';
                    
// Create index label with improved positioning - smaller and less intrusive
                const label = document.createElement('span');
                const labelPadding = 2;
                const fontSize = 8;  // Fixed smaller font size
                
                // Base style for label - smaller and positioned at top-left corner
                let labelStyle = 'position:absolute;background-color:' + h.color + ';color:white;' +
                    'padding:' + labelPadding + 'px ' + (labelPadding + 2) + 'px;' +
                    'font-size:' + fontSize + 'px;font-family:monospace;font-weight:bold;' +
                    'border-radius:2px;white-space:nowrap;border:1px solid rgba(255,255,255,0.8);' +
                    'line-height:1;min-width:14px;text-align:center;';
                
                // Positioning logic - always place at top-left corner outside element
                const labelHeight = fontSize + labelPadding * 2 + 2;
                const labelWidth = (String(h.index).length * fontSize * 0.6) + labelPadding * 2 + 4;
                
                if (h.y > labelHeight + 2) {
                    // Place above element
                    labelStyle += 'top:-' + (labelHeight + 2) + 'px;left:-1px;';
                } else {
                    // Not enough space above, place inside
                        labelStyle += 'top:2px;left:2px;';
                    }
                    
                    label.style.cssText = labelStyle;
                    label.textContent = String(h.index);
                    el.appendChild(label);
                    
                    container.appendChild(el);
                });
            ''', highlights)
        except Exception as e:
            self.logger.warning(f'Failed to draw highlights: {e}')

    async def draw_highlights_in_iframe(
        self,
        iframe_selector: str,
        selector_map: dict[int, EnhancedDOMTreeNode],
        focus_element: int = -1,
    ) -> None:
        """
        Draw highlight overlays on elements inside an iframe.
        
        This method switches to the iframe context, draws highlights,
        then restores the original context.
        
        Args:
            iframe_selector: CSS selector for the iframe
            selector_map: Map of selector indices to DOM nodes within the iframe
            focus_element: Index of element to focus highlight on (-1 for none)
        """
        if not selector_map:
            return
        
        # Save current context
        saved_context = self.iframe_handler.get_current_context()
        
        try:
            # Switch to default content first, then to the iframe
            await self.iframe_handler.switch_to_default()
            if not await self.iframe_handler.switch_to_frame(iframe_selector):
                self.logger.warning(f'Could not switch to iframe for highlights: {iframe_selector}')
                return
            
            # Draw highlights within the iframe context
            await self.draw_highlights(selector_map, focus_element)
            
        except Exception as e:
            self.logger.warning(f'Failed to draw highlights in iframe {iframe_selector}: {e}')
        finally:
            await self.iframe_handler.restore_context(saved_context)

    async def clear_highlights_in_iframe(self, iframe_selector: str) -> None:
        """Clear all highlight overlays from a specific iframe."""
        saved_context = self.iframe_handler.get_current_context()
        
        try:
            await self.iframe_handler.switch_to_default()
            if not await self.iframe_handler.switch_to_frame(iframe_selector):
                return
            
            await self.clear_highlights()
            
        except Exception as e:
            self.logger.warning(f'Failed to clear highlights in iframe {iframe_selector}: {e}')
        finally:
            await self.iframe_handler.restore_context(saved_context)

    async def clear_all_highlights(self) -> None:
        """Clear highlight overlays from main page and all iframes."""
        # Clear main page
        await self.clear_highlights()
        
        # Get all iframes and clear highlights in each
        try:
            iframes = await self.iframe_handler.get_all_iframes(include_nested=True, max_depth=3)
            for iframe in iframes:
                await self.clear_highlights_in_iframe(iframe.selector)
        except Exception as e:
            self.logger.debug(f'Error clearing iframe highlights: {e}')

    async def clear_highlights(self) -> None:
        """Clear all highlight overlays from the page."""
        try:
            self.driver.execute_script('''
                const container = document.getElementById('browser-use-selenium-highlight-container');
                if (container) {
                    container.remove();
                }
            ''')
        except Exception as e:
            self.logger.warning(f'Failed to clear highlights: {e}')

    def _is_new_tab_page(self, url: str) -> bool:
        """Check if URL is a new/blank tab page."""
        if not url:
            return True
        new_tab_patterns = [
            'about:blank',
            'about:newtab',
            'chrome://newtab',
            'edge://newtab',
            'about:home',
            'data:',
        ]
        return any(url.startswith(pattern) for pattern in new_tab_patterns)

    def _create_empty_root_node(self) -> EnhancedDOMTreeNode:
        """Create an empty root node for new/blank pages."""
        return EnhancedDOMTreeNode(
            node_id=0,
            backend_node_id=0,
            node_type=NodeType.ELEMENT_NODE,
            node_name='BODY',
            node_value='',
            attributes={},
            is_scrollable=False,
            is_visible=False,
            absolute_position=None,
            target_id='',
            frame_id=None,
            session_id=None,
            content_document=None,
            shadow_root_type=None,
            shadow_roots=None,
            parent_node=None,
            children_nodes=[],
            ax_node=None,
            snapshot_node=None,
        )

    def _construct_dom_tree(
        self,
        eval_result: dict,
    ) -> tuple[EnhancedDOMTreeNode, dict[int, EnhancedDOMTreeNode]]:
        """
        Convert the JavaScript evaluation result to an EnhancedDOMTreeNode tree.
        
        Args:
            eval_result: The result from JavaScript DOM extraction containing 'map' and 'rootId'
            
        Returns:
            Tuple of (root_node, selector_map)
        """
        js_node_map = eval_result.get('map', {})
        js_root_id = eval_result.get('rootId')

        if not js_node_map or js_root_id is None:
            return self._create_empty_root_node(), {}

        selector_map: dict[int, EnhancedDOMTreeNode] = {}
        node_map: dict[str, EnhancedDOMTreeNode] = {}

        # First pass: create all nodes
        for node_id, node_data in js_node_map.items():
            if not node_data:
                continue

            node = self._parse_js_node(node_data, node_id)
            if node is not None:
                node_map[node_id] = node

                # Add to selector map if it has a highlight index
                highlight_index = node_data.get('highlightIndex')
                if highlight_index is not None and highlight_index >= 0:
                    selector_map[highlight_index] = node

        self.logger.debug(f'Built selector_map from JS with {len(selector_map)} elements')

        # Second pass: build parent-child relationships
        for node_id, node_data in js_node_map.items():
            if node_id not in node_map:
                continue

            node = node_map[node_id]
            children_ids = node_data.get('children', [])

            for child_id in children_ids:
                child_id_str = str(child_id)
                if child_id_str in node_map:
                    child_node = node_map[child_id_str]
                    child_node.parent_node = node
                    if node.children_nodes is None:
                        node.children_nodes = []
                    node.children_nodes.append(child_node)

        # Get root node
        root_id_str = str(js_root_id)
        if root_id_str not in node_map:
            self.logger.warning(f'Root node {js_root_id} not found in node map')
            return self._create_empty_root_node(), selector_map

        root_node = node_map[root_id_str]
        return root_node, selector_map

    def _parse_js_node(self, node_data: dict, node_id: str) -> EnhancedDOMTreeNode | None:
        """
        Parse a single node from the JavaScript result into an EnhancedDOMTreeNode.
        
        Args:
            node_data: The node data from JavaScript
            node_id: The node ID string
            
        Returns:
            EnhancedDOMTreeNode or None if the node should be skipped
        """
        if not node_data:
            return None

        # Handle text nodes
        if node_data.get('type') == 'TEXT_NODE':
            # Cap text node content to 100 chars to match CDP behavior
            text_content = node_data.get('text', '')
            if len(text_content) > 100:
                text_content = text_content[:100]
            return EnhancedDOMTreeNode(
                node_id=int(node_id) if node_id.isdigit() else hash(node_id) % (10**9),
                backend_node_id=int(node_id) if node_id.isdigit() else hash(node_id) % (10**9),
                node_type=NodeType.TEXT_NODE,
                node_name='#text',
                node_value=text_content,
                attributes={},
                is_scrollable=False,
                is_visible=node_data.get('isVisible', False),
                absolute_position=None,
                target_id='',
                frame_id=None,
                session_id=None,
                content_document=None,
                shadow_root_type=None,
                shadow_roots=None,
                parent_node=None,
                children_nodes=[],
                ax_node=None,
                snapshot_node=self._create_snapshot_node_from_js(node_data),
            )

        # Handle element nodes
        tag_name = node_data.get('tagName', 'div').upper()
        
        # Parse bounds/viewport info
        bounds = None
        if 'viewport' in node_data:
            viewport = node_data['viewport']
            bounds = DOMRect(
                x=viewport.get('x', 0),
                y=viewport.get('y', 0),
                width=viewport.get('width', 0),
                height=viewport.get('height', 0),
            )

        # Create snapshot node with computed properties
        snapshot_node = self._create_snapshot_node_from_js(node_data)

        # Ensure JS-generated xpath is preserved in attributes
        attributes = node_data.get('attributes', {})

        # In compact mode, filter out less important attributes to save tokens
        if self.compact_mode:
            # Keep only essential attributes + data attributes for testing/selection
            keep_attrs = {
                'id',
                'name',
                'type',
                'value',
                'placeholder',
                'aria-label',
                'role',
                'class',
                'title',
                'alt',
                'href',
                'src',
                'target',
                'checked',
                'disabled',
                'selected',
                'expanded',
                'aria-expanded',
                'aria-checked',
                'aria-selected',
                'readonly',
                'required',
                'min',
                'max',
                'step',
                'pattern',
                'accept',
                'multiple',
                'autocomplete',
                'for',
                'tabindex',
            }
            # Also keep data-testid, data-test, etc. as they are often used for selectors
            attributes = {
                k: v
                for k, v in attributes.items()
                if k in keep_attrs or k.startswith('data-test') or k.startswith('aria-')
            }

        # Always include xpath for reliable element selection - essential for Selenium clicks
        if 'xpath' in node_data:
            attributes['xpath'] = node_data['xpath']
        
        return EnhancedDOMTreeNode(
            node_id=int(node_id) if node_id.isdigit() else hash(node_id) % (10**9),
            backend_node_id=int(node_id) if node_id.isdigit() else hash(node_id) % (10**9),
            node_type=NodeType.ELEMENT_NODE,
            node_name=tag_name,
            node_value='',
            attributes=attributes,
            is_scrollable=node_data.get('isScrollable', False),
            is_visible=node_data.get('isVisible', False),
            absolute_position=bounds,
            target_id='',
            frame_id=None,
            session_id=None,
            content_document=None,
            shadow_root_type=None,
            shadow_roots=None,
            parent_node=None,
            children_nodes=[],
            ax_node=self._create_ax_node_from_js(node_data),
            snapshot_node=snapshot_node,
        )

    def _create_snapshot_node_from_js(self, node_data: dict) -> EnhancedSnapshotNode:
        """Create an EnhancedSnapshotNode from JavaScript node data."""
        bounds = None
        if 'viewport' in node_data:
            viewport = node_data['viewport']
            bounds = DOMRect(
                x=viewport.get('x', 0),
                y=viewport.get('y', 0),
                width=viewport.get('width', 0),
                height=viewport.get('height', 0),
            )

        return EnhancedSnapshotNode(
            is_clickable=node_data.get('isInteractive', False),
            cursor_style='pointer' if node_data.get('isInteractive', False) else None,
            bounds=bounds,
            clientRects=bounds,  # Use same bounds for client rects
            scrollRects=None,
            computed_styles=None,  # Not available from JS extraction
            paint_order=node_data.get('paintOrder', 0),
            stacking_contexts=None,
        )

    def _create_ax_node_from_js(self, node_data: dict) -> EnhancedAXNode | None:
        """Create an EnhancedAXNode from JavaScript node data if applicable."""
        if not node_data.get('isInteractive', False):
            return None

        role = node_data.get('role') or node_data.get('tagName', '').lower()
        name = node_data.get('ariaLabel') or node_data.get('title') or node_data.get('text', '')

        return EnhancedAXNode(
            ax_node_id='selenium-' + str(node_data.get('highlightIndex', 0)),
            ignored=False,
            role=role,
            name=name[:100] if name else None,  # Cap name length
            description=node_data.get('ariaDescription'),
            properties=None,
            child_ids=None,
        )

    # ==================== Iframe-Specific DOM Methods ====================

    async def get_iframe_dom_tree(
        self,
        iframe_selector: str,
        highlight_elements: bool = True,
    ) -> tuple[EnhancedDOMTreeNode | None, dict[int, EnhancedDOMTreeNode]]:
        """
        Get the DOM tree for a specific same-origin iframe.
        
        This method switches to the iframe context, extracts the DOM,
        and then restores the original context.
        
        Args:
            iframe_selector: CSS selector or XPath for the iframe
            highlight_elements: Whether to highlight interactive elements
            
        Returns:
            Tuple of (root_node, selector_map) or (None, {}) if extraction fails
        """
        # Save current context
        saved_context = self.iframe_handler.get_current_context()
        
        try:
            # Switch to default content first
            await self.iframe_handler.switch_to_default()
            
            # Switch to the target iframe
            if not await self.iframe_handler.switch_to_frame(iframe_selector):
                self.logger.warning(f'Could not switch to iframe: {iframe_selector}')
                return None, {}
            
            # Extract DOM within iframe context
            root_node, selector_map, timing = await self.get_dom_tree(
                highlight_elements=highlight_elements,
            )
            
            # Tag all nodes with iframe context info
            for idx, node in selector_map.items():
                node.attributes['data-iframe-selector'] = iframe_selector
                node.frame_id = f'iframe:{iframe_selector}'
            
            self.logger.debug(
                f'Extracted {len(selector_map)} elements from iframe {iframe_selector}'
            )
            
            return root_node, selector_map
            
        except Exception as e:
            self.logger.warning(f'Error extracting DOM from iframe {iframe_selector}: {e}')
            return None, {}
        finally:
            # Restore original context
            await self.iframe_handler.restore_context(saved_context)

    async def _quick_iframe_content_check(
        self,
        iframe_selector: str,
        timeout: float = 2.0,
    ) -> bool:
        """
        Quick probe to check if an iframe has any interactive elements.
        
        This is much faster than full DOM extraction - just counts interactive elements.
        Used to skip ad/tracking iframes that are visible but have no useful content.
        
        Args:
            iframe_selector: CSS selector for the iframe
            timeout: Maximum time to wait for the check
            
        Returns:
            True if iframe has interactive elements, False otherwise
        """
        saved_context = self.iframe_handler.get_current_context()
        
        try:
            # Switch to iframe
            await self.iframe_handler.switch_to_default()
            if not await self.iframe_handler.switch_to_frame(iframe_selector, timeout=timeout):
                return False
            
            # Quick count of interactive elements
            check_script = """
                return document.querySelectorAll(
                    'a[href], button, input, select, textarea, [role="button"], [role="link"], [onclick], [tabindex]'
                ).length;
            """
            
            count = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self.driver.execute_script(check_script)
            )
            
            return count > 0
            
        except Exception as e:
            self.logger.debug(f'Quick content check failed for {iframe_selector}: {e}')
            return False
        finally:
            await self.iframe_handler.restore_context(saved_context)

    async def _get_iframe_dom_optimized(
        self,
        iframe_selector: str,
        highlight_elements: bool = False,
    ) -> dict[int, EnhancedDOMTreeNode]:
        """
        Optimized iframe DOM extraction - single switch per iframe.
        
        Combines quick content check + DOM extraction in one frame switch,
        reducing WebDriver round-trips significantly for remote sessions.
        
        Args:
            iframe_selector: CSS selector for the iframe
            highlight_elements: Whether to highlight interactive elements
            
        Returns:
            selector_map dict (empty if no interactive elements or error)
        """
        saved_context = self.iframe_handler.get_current_context()
        
        try:
            # Single switch to iframe
            await self.iframe_handler.switch_to_default()
            if not await self.iframe_handler.switch_to_frame(iframe_selector, timeout=3.0):
                self.logger.debug(f'Could not switch to iframe: {iframe_selector}')
                return {}
            
            # Combined script: quick count + DOM extraction in one call
            # First check if there are interactive elements
            check_script = """
                return document.querySelectorAll(
                    'a[href], button, input, select, textarea, [role="button"], [role="link"], [onclick], [tabindex]'
                ).length;
            """
            
            count = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self.driver.execute_script(check_script)
            )
            
            if count == 0:
                self.logger.debug(f'  -> SKIP (no interactive elements in iframe)')
                return {}
            
            self.logger.debug(f'  -> Found {count} interactive elements, extracting DOM...')
            
            # Now extract full DOM (we're already in the iframe context)
            debug_mode = self.logger.getEffectiveLevel() == logging.DEBUG
            args = {
                'doHighlightElements': False,
                'focusHighlightIndex': -1,
                'viewportExpansion': 0,
                'debugMode': debug_mode,
                'maxIframeDepth': 1,  # Don't recurse into nested iframes
                'maxIframes': 0,
                'includeCrossOriginIframes': False,
                'compactMode': self.compact_mode,
            }
            
            try:
                eval_result: dict = self.driver.execute_script(f'return ({self.js_code})(arguments[0])', args)
            except Exception as js_error:
                self.logger.debug(f'DOM extraction JS failed in iframe: {js_error}')
                return {}
            
            # Convert to selector_map
            _, selector_map = self._construct_dom_tree(eval_result or {})
            
            # Tag all nodes with iframe context info
            for idx, node in selector_map.items():
                node.attributes['data-iframe-selector'] = iframe_selector
                node.frame_id = f'iframe:{iframe_selector}'
            
            self.logger.debug(f'  -> Extracted {len(selector_map)} elements from iframe')
            
            return selector_map
            
        except Exception as e:
            self.logger.debug(f'Error in optimized iframe DOM extraction for {iframe_selector}: {e}')
            return {}
        finally:
            # Restore original context
            await self.iframe_handler.restore_context(saved_context)

    async def get_merged_dom_with_iframes(
        self,
        highlight_elements: bool = True,
        max_iframes: int = 5,
        skip_processing_iframes: bool = False,
    ) -> tuple[EnhancedDOMTreeNode, dict[int, EnhancedDOMTreeNode], dict[str, IframeInfo]]:
        """
        Get a merged DOM tree that includes elements from ALL iframes (including cross-origin).
        
        This method:
        1. Extracts the main page DOM
        2. Identifies all iframes (Selenium can access cross-origin too)
        3. Extracts DOM from each iframe
        4. Merges selector maps with offset indices
        5. Redraws highlights with correct merged indices
        
        Args:
            highlight_elements: Whether to highlight interactive elements
            max_iframes: Maximum number of iframes to process
            skip_processing_iframes: Skip iframe discovery and DOM extraction from iframes,
                returning only the main page DOM
            
        Returns:
            Tuple of (main_root_node, merged_selector_map, iframe_info_map)
        """
        # Use instance-level setting as default if not explicitly provided
        if skip_processing_iframes is False and self.skip_processing_iframes:
            skip_processing_iframes = True
        
        # Get main page DOM (without highlights first - we'll draw them all at the end)
        await self.iframe_handler.switch_to_default()
        main_root, main_selector_map, _ = await self.get_dom_tree(
            highlight_elements=False,  # Draw highlights later with correct indices
            skip_processing_iframes=skip_processing_iframes,
        )
        
        merged_selector_map = dict(main_selector_map)
        iframe_info_map: dict[str, IframeInfo] = {}
        
        # Track which elements belong to which iframe for highlight drawing
        iframe_elements: dict[str, dict[int, EnhancedDOMTreeNode]] = {}
        
        # Skip iframe processing if requested
        if skip_processing_iframes:
            self.logger.debug('Skipping iframe processing as requested')
            # Still draw highlights for main page
            if highlight_elements:
                await self.draw_highlights(main_selector_map, focus_element=-1)
            return main_root, merged_selector_map, iframe_info_map
        
        # Get iframe info using optimized batch collection
        iframes = await self.iframe_handler.get_all_iframes(
            include_nested=False,  # Skip nested for performance - top-level is usually enough
            max_depth=1,
        )
        
        self.logger.debug(f'Found {len(iframes)} iframes, filtering...')
        
        # Smart filtering: visible + reasonable size
        processable_iframes: list = []
        for iframe in iframes:
            display_status = '✓' if iframe.is_displayed else '✗'
            size_str = f'{iframe.size.get("width", 0)}x{iframe.size.get("height", 0)}' if iframe.size else '?x?'
            src_preview = iframe.src[:60] if iframe.src else 'no-src'
            
            # Skip hidden iframes
            if not iframe.is_displayed:
                self.logger.debug(f'  {display_status} SKIP hidden: {iframe.selector}')
                continue
            
            # Skip tiny iframes (tracking pixels)
            width = iframe.size.get('width', 0) if iframe.size else 0
            height = iframe.size.get('height', 0) if iframe.size else 0
            if width < self.iframe_handler.min_iframe_width or height < self.iframe_handler.min_iframe_height:
                self.logger.debug(f'  {display_status} SKIP tiny ({size_str}): {iframe.selector}')
                continue
            
            self.logger.debug(f'  {display_status} OK ({size_str}): {iframe.selector} | {src_preview}')
            processable_iframes.append(iframe)
        
        self.logger.debug(f'Processing {len(processable_iframes)} of {len(iframes)} iframes')
        
        # Process iframes worth interacting with - OPTIMIZED: single switch per iframe
        next_index = max(merged_selector_map.keys(), default=-1) + 1
        
        for iframe in processable_iframes[:max_iframes]:
            iframe_info_map[iframe.selector] = iframe
            
            self.logger.debug(f'Extracting DOM from iframe: {iframe.selector}')
            
            try:
                # OPTIMIZED: Single switch per iframe - do quick check AND DOM extraction together
                iframe_timeout = 5.0  # seconds per iframe
                try:
                    iframe_selector_map = await asyncio.wait_for(
                        self._get_iframe_dom_optimized(
                            iframe.selector,
                            highlight_elements=False,
                        ),
                        timeout=iframe_timeout
                    )
                except asyncio.TimeoutError:
                    self.logger.debug(f'  -> TIMEOUT after {iframe_timeout}s extracting DOM from iframe')
                    continue
                
                if not iframe_selector_map:
                    self.logger.debug(f'  -> No interactive elements found in iframe')
                    continue
                
                # Track elements for this iframe with their NEW indices
                iframe_elements[iframe.selector] = {}
                
                # Merge with offset indices
                for old_idx, node in iframe_selector_map.items():
                    new_idx = next_index + old_idx
                    merged_selector_map[new_idx] = node
                    iframe_elements[iframe.selector][new_idx] = node
                
                next_index = max(merged_selector_map.keys(), default=next_index) + 1
                
                self.logger.debug(f'  -> Merged {len(iframe_selector_map)} elements (indices {min(iframe_elements[iframe.selector].keys())}-{max(iframe_elements[iframe.selector].keys())})')
                
            except Exception as e:
                self.logger.debug(f'  -> ERROR: Could not merge iframe {iframe.selector}: {e}')
        
        # Now draw highlights with the CORRECT merged indices
        if highlight_elements:
            # Draw main page highlights
            await self.iframe_handler.switch_to_default()
            await self.draw_highlights(main_selector_map, focus_element=-1)
            
            # Draw iframe highlights with correct merged indices
            for iframe_selector, elements in iframe_elements.items():
                if elements:
                    await self.draw_highlights_in_iframe(iframe_selector, elements, focus_element=-1)
        
        self.logger.info(
            f'Merged DOM: {len(main_selector_map)} main + '
            f'{len(merged_selector_map) - len(main_selector_map)} iframe elements'
        )
        
        # Debug: Print ALL merged selector map elements
        if self.logger.isEnabledFor(logging.DEBUG):
            self.logger.debug('==================== MERGED SELECTOR MAP (with iframes) ====================')
            for idx in sorted(merged_selector_map.keys()):
                node = merged_selector_map[idx]
                tag = node.tag_name if hasattr(node, 'tag_name') else node.node_name
                classes = node.attributes.get('class', '')[:40] if hasattr(node, 'attributes') else ''
                iframe_src = node.attributes.get('data-iframe-selector', 'main') if hasattr(node, 'attributes') else 'main'
                text = ''
                if hasattr(node, 'ax_node') and node.ax_node and node.ax_node.name:
                    text = node.ax_node.name[:50]
                elif hasattr(node, 'node_value') and node.node_value:
                    text = node.node_value[:50]
                
                # Mark iframe elements with a flag
                iframe_marker = f' [IFRAME: {iframe_src}]' if iframe_src != 'main' else ''
                self.logger.debug(f'  Index {idx}: {tag}.{classes} "{text}"{iframe_marker}')
            self.logger.debug('=' * 70)
        
        return main_root, merged_selector_map, iframe_info_map

