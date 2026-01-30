"""
Selenium-based DOM service for Firefox and Safari browsers.

This service uses Selenium's execute_script() with JavaScript injection to extract
DOM elements, reusing the same index.js script as PlaywrightDomService.
"""

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


class SeleniumDomService:
    """
    DOM service for Firefox and Safari browsers using Selenium JavaScript evaluation.
    
    This service injects JavaScript into the page to extract DOM elements and their properties,
    then converts the results to EnhancedDOMTreeNode format for compatibility with the rest
    of the browser-use codebase.
    
    Uses the same index.js script as PlaywrightDomService for consistent DOM extraction.
    """

    logger: logging.Logger

    def __init__(
        self,
        driver: 'WebDriver',
        logger: logging.Logger | None = None,
        paint_order_filtering: bool = True,
    ):
        self.driver = driver
        self.logger = logger or logging.getLogger(__name__)
        self.paint_order_filtering = paint_order_filtering

        # Load the JavaScript code for DOM extraction (same as PlaywrightDomService)
        raw_js_code = resources.files('browser_use.dom').joinpath('dom_tree_js', 'index.js').read_text(encoding='utf-8').strip()
        if raw_js_code.startswith('﻿'):
            raw_js_code = raw_js_code[1:]  # Remove UTF-8 BOM if present
        if raw_js_code.endswith(';'):
            raw_js_code = raw_js_code[:-1]
        # Don't wrap with 'return' here - execute_script handles that
        self.js_code = raw_js_code
        self.logger.debug(f'JavaScript code loaded, length: {len(self.js_code)} chars')

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        pass

    @time_execution_async('--selenium_get_dom_tree')
    async def get_dom_tree(
        self,
        highlight_elements: bool = True,
        focus_element: int = -1,
        viewport_expansion: int = 0,
    ) -> tuple[EnhancedDOMTreeNode, dict[int, EnhancedDOMTreeNode], dict[str, float]]:
        """
        Get the DOM tree using Selenium JavaScript evaluation.
        
        Args:
            highlight_elements: Whether to highlight interactive elements
            focus_element: Index of element to focus highlight on (-1 for none)
            viewport_expansion: Pixels to expand viewport for element detection
            
        Returns:
            Tuple of (root_node, selector_map, timing_info)
        """
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
        previous_cached_state: SerializedDOMState | None = None,
        session_id: str | None = None,
    ) -> tuple[SerializedDOMState, EnhancedDOMTreeNode, dict[int, EnhancedDOMTreeNode], dict[str, float]]:
        """
        Get the serialized DOM tree representation for LLM consumption.
        
        Returns:
            Tuple of (serialized_dom_state, enhanced_dom_tree_root, timing_info)
        """
        timing_info: dict[str, float] = {}
        start_total = time.time()

        # Build DOM tree
        enhanced_dom_tree, selector_map, dom_tree_timing = await self.get_dom_tree()
        timing_info.update(dom_tree_timing)

        # Serialize DOM tree for LLM
        start_serialize = time.time()
        serialized_dom_state, serializer_timing = DOMTreeSerializer(
            enhanced_dom_tree,
            previous_cached_state,
            paint_order_filtering=self.paint_order_filtering,
            session_id=session_id,
            force_contiguous_indices=True,  # Use contiguous indices for Selenium to avoid mixing with backend_node_id
        ).serialize_accessible_elements()

        # Build node-to-selector-index mapping from selector_map (maps contiguous index → node)
        # This allows views.py to show contiguous indices in the serialized output
        serialized_dom_state._node_to_selector_index = {id(node): idx for idx, node in serialized_dom_state.selector_map.items()}

        # Draw highlights with CORRECT indices (matching what the agent will use)
        await self.draw_highlights(serialized_dom_state.selector_map, focus_element=-1)

        # Add serializer sub-timings
        for key, value in serializer_timing.items():
            timing_info[f'{key}_ms'] = value * 1000

        timing_info['serialization_total_ms'] = (time.time() - start_serialize) * 1000
        timing_info['get_serialized_dom_tree_total_ms'] = (time.time() - start_total) * 1000

        return serialized_dom_state, enhanced_dom_tree, selector_map, timing_info

    async def draw_highlights(
        self,
        selector_map: dict[int, EnhancedDOMTreeNode],
        focus_element: int = -1,
    ) -> None:
        """
        Draw highlight overlays on elements using the actual selector_map indices.
        
        This ensures visual indices match what the agent sees.
        
        Args:
            selector_map: Map of selector indices to DOM nodes
            focus_element: Index of element to focus highlight on (-1 for none)
        """
        if not selector_map:
            return

        # Build highlight data with correct indices
        highlights = []
        for index, node in selector_map.items():
            if node and node.snapshot_node and node.snapshot_node.bounds:
                bounds = node.snapshot_node.bounds
                is_focused = (focus_element == index)
                highlights.append({
                    'index': index,
                    'x': bounds.x,
                    'y': bounds.y,
                    'width': bounds.width,
                    'height': bounds.height,
                    'isFocused': is_focused,
                })

        if not highlights:
            return

        # Execute JavaScript to draw highlights with correct indices
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
                
                highlights.forEach(function(h) {
                    const el = document.createElement('div');
                    el.style.cssText = 'position:fixed;left:' + h.x + 'px;top:' + h.y + 'px;width:' + h.width + 'px;height:' + h.height + 'px;background-color:' + (h.isFocused ? 'rgba(255, 127, 39, 0.5)' : 'rgba(255, 127, 39, 0.3)') + ';border:2px solid ' + (h.isFocused ? 'rgb(255, 127, 39)' : 'rgba(255, 127, 39, 0.8)') + ';box-sizing:border-box;pointer-events:none;';
                    
                    const label = document.createElement('span');
                    label.style.cssText = 'position:absolute;top:-18px;left:0;background-color:rgb(255, 127, 39);color:white;padding:2px 6px;font-size:11px;font-family:monospace;border-radius:3px;white-space:nowrap;';
                    label.textContent = String(h.index);
                    el.appendChild(label);
                    
                    container.appendChild(el);
                });
            ''', highlights)
        except Exception as e:
            self.logger.warning(f'Failed to draw highlights: {e}')

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
                if highlight_index is not None:
                    selector_map[highlight_index] = node

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
            return EnhancedDOMTreeNode(
                node_id=int(node_id) if node_id.isdigit() else hash(node_id) % (10**9),
                backend_node_id=int(node_id) if node_id.isdigit() else hash(node_id) % (10**9),
                node_type=NodeType.TEXT_NODE,
                node_name='#text',
                node_value=node_data.get('text', ''),
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

        return EnhancedDOMTreeNode(
            node_id=int(node_id) if node_id.isdigit() else hash(node_id) % (10**9),
            backend_node_id=int(node_id) if node_id.isdigit() else hash(node_id) % (10**9),
            node_type=NodeType.ELEMENT_NODE,
            node_name=tag_name,
            node_value='',
            attributes=node_data.get('attributes', {}),
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
