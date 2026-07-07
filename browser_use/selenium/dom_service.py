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
import json
import logging
import os
import time
from pathlib import Path
from typing import TYPE_CHECKING

from browser_use.dom.serializer.serializer import DOMTreeSerializer
from browser_use.dom.views import (
    DOMRect,
    EnhancedAXNode,
    EnhancedDOMTreeNode,
    EnhancedSnapshotNode,
    NodeType,
    SerializedDOMState,
)
from browser_use.utils import time_execution_async

if TYPE_CHECKING:
    from selenium.webdriver.remote.webdriver import WebDriver

from browser_use.selenium.iframe_handler import IframeInfo, SeleniumIframeHandler


DOM_TREE_JS_PATH = Path(__file__).resolve().parents[1] / 'dom' / 'dom_tree_js' / 'index.js'


def _read_dom_tree_js_from_disk() -> str:
    return DOM_TREE_JS_PATH.read_text(encoding='utf-8')


def _load_dom_tree_js() -> str:
    """Load the shared DOM extraction script from embedded code or source checkout."""
    if os.environ.get('BROWSER_USE_DEV_ENV') == '1' and DOM_TREE_JS_PATH.exists():
        return _read_dom_tree_js_from_disk()

    if not INDEX_JS:
        raise RuntimeError(
            'INDEX_JS is empty. This usually means the embedding script '
            '(scripts/embed_external.py) was not run before building or the development '
            'environment is not configured correctly.'
        )
    return INDEX_JS


# BEGIN GENERATED DOM TREE JS
INDEX_JS = '\ufeff/**\n * DOM Tree Extraction Script for Browser-Use\n * \n * This script is injected into pages via Playwright\'s page.evaluate() to extract\n * DOM elements and their properties for Firefox and WebKit (Safari) browsers.\n * \n * For Chromium browsers, the CDP-based approach in service.py is used instead.\n * \n * @param {Object} args - Configuration arguments\n * @param {boolean} args.doHighlightElements - Whether to add visual highlights\n * @param {number} args.focusHighlightIndex - Element index to focus (-1 for none)\n * @param {number} args.viewportExpansion - Pixels to expand viewport detection\n * @param {boolean} args.debugMode - Enable debug logging\n * @returns {Object} - DOM tree data with map, rootId, and perfMetrics\n */\n(function (args) {\n\t\'use strict\';\n\n\tconst {\n\t\tdoHighlightElements = true,\n\t\tfocusHighlightIndex = -1,\n\t\tviewportExpansion = 0,\n\t\tdebugMode = false,\n\t\tmaxIframeDepth = 5,\n\t\tmaxIframes = 100,\n\t\tincludeCrossOriginIframes = true,\n\t\tcompactMode = false  // When true, only return interactive nodes + ancestors\n\t} = args || {};\n\n\t// Track parent relationships for compact mode\n\tconst nodeParentMap = {};  // nodeId -> parentId\n\n\t// Performance tracking\n\tconst perfMetrics = {\n\t\tstartTime: performance.now(),\n\t\tnodeMetrics: {\n\t\t\ttotalNodes: 0,\n\t\t\tprocessedNodes: 0,\n\t\t\tinteractiveNodes: 0,\n\t\t\tvisibleNodes: 0,\n\t\t\tfilteredEmptyInteractive: 0\n\t\t}\n\t};\n\n\t// Node map to store extracted data\n\tconst nodeMap = {};\n\tlet nodeIdCounter = 1;\n\tlet highlightIndex = 0;\n\n\t// Highlight container for visual elements\n\tlet highlightContainer = null;\n\n\t// Track interactive elements for sorted index assignment\n\tconst interactiveElements = [];\n\n\t// Iframe tracking\n\tlet iframeCount = 0;\n\tconst iframeNodes = [];\n\n\t// Iframe coordinate offset tracking\n\t// When processing elements inside same-origin iframes, getBoundingClientRect()\n\t// returns coordinates relative to the iframe viewport, not the main document.\n\t// These offsets accumulate the iframe position to convert to main document coordinates.\n\tlet iframeOffsetX = 0;\n\tlet iframeOffsetY = 0;\n\n\t// Interactive element selectors\n\tconst INTERACTIVE_SELECTORS = [\n\t\t\'a[href]\',\n\t\t\'a[role]\',  // Links with roles even without href\n\t\t\'button\',\n\t\t\'input\',\n\t\t\'select\',\n\t\t\'textarea\',\n\t\t\'[role="button"]\',\n\t\t\'[role="link"]\',\n\t\t\'[role="checkbox"]\',\n\t\t\'[role="radio"]\',\n\t\t\'[role="tab"]\',\n\t\t\'[role="menuitem"]\',\n\t\t\'[role="option"]\',\n\t\t\'[role="switch"]\',\n\t\t\'[role="slider"]\',\n\t\t\'[role="spinbutton"]\',\n\t\t\'[role="combobox"]\',\n\t\t\'[role="listbox"]\',\n\t\t\'[role="searchbox"]\',\n\t\t\'[role="textbox"]\',\n\t\t\'[role="dialog"]\',\n\t\t\'[role="alertdialog"]\',\n\t\t\'[tabindex]\',\n\t\t\'[onclick]\',\n\t\t\'[contenteditable="true"]\',\n\t\t\'summary\',\n\t\t\'details\',\n\t\t\'label[for]\',\n\t\t\'[draggable="true"]\',\n\t\t// Additional patterns for styled buttons/links\n\t\t\'[data-testid*="button"]\',\n\t\t\'[data-testid*="btn"]\',\n\t\t\'[class*="button"]\',\n\t\t\'[class*="btn"]\',\n\t\t// Generic popup/modal selectors\n\t\t\'[class*="popup"]\',\n\t\t\'[class*="modal"]\',\n\t\t\'[class*="dialog"]\',\n\t\t\'[class*="overlay"]\',\n\t\t\'[aria-modal="true"]\',\n\t];\n\n\t// Elements to skip completely\n\tconst SKIP_TAGS = new Set([\n\t\t\'SCRIPT\', \'STYLE\', \'NOSCRIPT\', \'META\', \'LINK\', \'HEAD\', \'BR\', \'HR\'\n\t]);\n\n\t// Inline elements that shouldn\'t break text flow\n\tconst INLINE_TAGS = new Set([\n\t\t\'A\', \'ABBR\', \'ACRONYM\', \'B\', \'BDO\', \'BIG\', \'BR\', \'BUTTON\', \'CITE\', \'CODE\',\n\t\t\'DFN\', \'EM\', \'I\', \'IMG\', \'INPUT\', \'KBD\', \'LABEL\', \'MAP\', \'OBJECT\', \'Q\',\n\t\t\'SAMP\', \'SCRIPT\', \'SELECT\', \'SMALL\', \'SPAN\', \'STRONG\', \'SUB\', \'SUP\',\n\t\t\'TEXTAREA\', \'TIME\', \'TT\', \'VAR\'\n\t]);\n\n\t/**\n\t * Check if an element is visible in the viewport\n\t * Enhanced to detect elements hidden via offsetParent, pointer-events, and visibility:collapse\n\t */\n\tfunction isElementVisible(element) {\n\t\tif (!element || !element.getBoundingClientRect) return false;\n\n\t\t// Use modern checkVisibility API if available (checks ancestors too)\n\t\tif (typeof element.checkVisibility === \'function\') {\n\t\t\tif (!element.checkVisibility({ opacityProperty: true, visibilityProperty: true })) {\n\t\t\t\treturn false;\n\t\t\t}\n\t\t}\n\n\t\tconst style = window.getComputedStyle(element);\n\t\tif (style.display === \'none\' ||\n\t\t\tstyle.visibility === \'hidden\' ||\n\t\t\tstyle.visibility === \'collapse\' ||\n\t\t\tstyle.opacity === \'0\') {\n\t\t\treturn false;\n\t\t}\n\n\t\t// Fallback for older browsers: check ancestors for opacity 0\n\t\tif (typeof element.checkVisibility !== \'function\') {\n\t\t\tlet curr = element.parentElement;\n\t\t\twhile (curr && curr !== document.body) {\n\t\t\t\tconst parentStyle = window.getComputedStyle(curr);\n\t\t\t\tif (parentStyle.opacity === \'0\' || parentStyle.display === \'none\' || parentStyle.visibility === \'hidden\') {\n\t\t\t\t\treturn false;\n\t\t\t\t}\n\t\t\t\tcurr = curr.parentElement;\n\t\t\t}\n\t\t}\n\n\t\tconst rect = element.getBoundingClientRect();\n\t\tif (rect.width === 0 || rect.height === 0) {\n\t\t\treturn false;\n\t\t}\n\n\t\t// Check if the center point is clipped by an overflow: hidden/scroll/auto ancestor\n\t\tconst centerX = rect.left + rect.width / 2;\n\t\tconst centerY = rect.top + rect.height / 2;\n\t\tlet clipCurr = element.parentElement;\n\t\twhile (clipCurr && clipCurr !== document.body && clipCurr !== document.documentElement) {\n\t\t\tconst style = window.getComputedStyle(clipCurr);\n\t\t\tif (style.display === \'contents\') {\n\t\t\t\tclipCurr = clipCurr.parentElement;\n\t\t\t\tcontinue;\n\t\t\t}\n\t\t\tif (style.overflow !== \'visible\' || style.overflowX !== \'visible\' || style.overflowY !== \'visible\') {\n\t\t\t\tconst parentRect = clipCurr.getBoundingClientRect();\n\t\t\t\tif (centerX < parentRect.left || centerX > parentRect.right ||\n\t\t\t\t\tcenterY < parentRect.top || centerY > parentRect.bottom) {\n\t\t\t\t\treturn false;\n\t\t\t\t}\n\t\t\t}\n\t\t\tclipCurr = clipCurr.parentElement;\n\t\t}\n\n\t\t// Check offsetParent - if null, element is not in layout\n\t\t// Exception: body, html, and fixed/sticky positioned elements can have null offsetParent\n\t\tif (element.offsetParent === null &&\n\t\t\telement !== document.body &&\n\t\t\telement !== document.documentElement) {\n\t\t\tconst position = style.position;\n\t\t\tif (position !== \'fixed\' && position !== \'sticky\') {\n\t\t\t\treturn false;\n\t\t\t}\n\t\t}\n\n\t\t// Check pointer-events - elements with pointer-events:none are not truly interactive\n\t\tif (style.pointerEvents === \'none\') {\n\t\t\treturn false;\n\t\t}\n\n\t\treturn true;\n\t}\n\n\t/**\n\t * Check if an element is in the viewport (with expansion)\n\t */\n\tfunction isInViewport(element, expansion = 0) {\n\t\tif (!element || !element.getBoundingClientRect) return false;\n\n\t\tconst rect = element.getBoundingClientRect();\n\t\tconst viewportHeight = window.innerHeight || document.documentElement.clientHeight;\n\t\tconst viewportWidth = window.innerWidth || document.documentElement.clientWidth;\n\n\t\treturn (\n\t\t\trect.bottom >= -expansion &&\n\t\t\trect.top <= viewportHeight + expansion &&\n\t\t\trect.right >= -expansion &&\n\t\t\trect.left <= viewportWidth + expansion\n\t\t);\n\t}\n\n\t/**\n\t * Check if an element is interactive\n\t */\n\tfunction isElementInteractive(element) {\n\t\tif (!element || element.nodeType !== Node.ELEMENT_NODE) return false;\n\n\t\t// Check if element matches interactive selectors\n\t\tfor (const selector of INTERACTIVE_SELECTORS) {\n\t\t\ttry {\n\t\t\t\tif (element.matches(selector)) {\n\t\t\t\t\t// Filter out empty anchor tags\n\t\t\t\t\tif (element.tagName === \'A\') {\n\t\t\t\t\t\tconst text = (element.textContent || \'\').trim();\n\t\t\t\t\t\tconst ariaLabel = element.getAttribute(\'aria-label\')?.trim();\n\t\t\t\t\t\tconst title = element.getAttribute(\'title\')?.trim();\n\t\t\t\t\t\tconst hasImage = element.querySelector(\'img, svg, [role="img"]\');\n\t\t\t\t\t\tif (!text && !ariaLabel && !title && !hasImage) {\n\t\t\t\t\t\t\treturn false;  // Skip empty anchors\n\t\t\t\t\t\t}\n\t\t\t\t\t}\n\t\t\t\t\treturn true;\n\t\t\t\t}\n\t\t\t} catch (e) {\n\t\t\t\t// Invalid selector, skip\n\t\t\t}\n\t\t}\n\n\t\t// Check for click event listeners (heuristic)\n\t\tconst tagName = element.tagName.toUpperCase();\n\t\tif (tagName === \'DIV\' || tagName === \'SPAN\') {\n\t\t\tconst style = window.getComputedStyle(element);\n\t\t\tif (style.cursor === \'pointer\') return true;\n\t\t}\n\n\t\treturn false;\n\t}\n\n\t/**\n\t * Check if element is the topmost element at its position - enhanced version\n\t * that handles z-index, CSS positioning, and complex overlap scenarios\n\t */\n\tfunction isTopElement(element) {\n\t\tif (!element || !element.getBoundingClientRect) return false;\n\n\t\tconst rect = element.getBoundingClientRect();\n\n\t\t// Skip if element has zero dimensions\n\t\tif (rect.width === 0 || rect.height === 0) return false;\n\n\t\tconst centerX = rect.left + rect.width / 2;\n\t\tconst centerY = rect.top + rect.height / 2;\n\n\t\t// Check if center point is within viewport\n\t\tif (centerX < 0 || centerY < 0 ||\n\t\t\tcenterX > window.innerWidth || centerY > window.innerHeight) {\n\t\t\treturn false;\n\t\t}\n\n\t\ttry {\n\t\t\tconst topElement = document.elementFromPoint(centerX, centerY);\n\t\t\tif (topElement === element) return true;\n\t\t\tif (element.contains(topElement)) return true;\n\n\t\t\t// Handle pointer-events: none wrappers: if the top element is an\n\t\t\t// ancestor of our element, the element is effectively visible and\n\t\t\t// clickable through the parent.\n\t\t\tif (topElement && topElement.contains(element)) return true;\n\n\t\t\t// Additional check: element might still be visible under a positioned sibling\n\t\t\t// Check for overlapping elements with higher stacking priority\n\t\t\treturn !hasOverlappingHigherElement(element, rect);\n\t\t} catch (e) {\n\t\t\treturn false;\n\t\t}\n\t}\n\n\t/**\n\t * Check if there\'s any overlapping element that should be on top\n\t * based on z-index stacking context and positioning\n\t */\n\tfunction hasOverlappingHigherElement(element, elementRect) {\n\t\tconst elementStyle = window.getComputedStyle(element);\n\t\tconst elementZIndex = getZIndex(elementStyle);\n\t\tconst elementPosition = elementStyle.position;\n\t\tconst elementOpacity = parseFloat(elementStyle.opacity) || 1;\n\n\t\t// Get parent stacking context\n\t\tconst parentStackingContext = getStackingContext(element);\n\t\tconst parentZIndex = parentStackingContext ? getZIndex(window.getComputedStyle(parentStackingContext)) : \'auto\';\n\n\t\t// Check siblings and cousins for overlapping elements with higher z-index\n\t\tlet current = element;\n\t\twhile (current && current !== document.body) {\n\t\t\tconst siblings = getVisibleSiblings(current);\n\t\t\tfor (const sibling of siblings) {\n\t\t\t\tif (sibling === element) continue;\n\n\t\t\t\tconst siblingStyle = window.getComputedStyle(sibling);\n\t\t\t\tconst siblingZIndex = getZIndex(siblingStyle);\n\t\t\t\tconst siblingPosition = siblingStyle.position;\n\t\t\t\tconst siblingOpacity = parseFloat(siblingStyle.opacity) || 1;\n\n\t\t\t\t// Skip invisible siblings\n\t\t\t\tif (siblingOpacity < 0.1) continue;\n\t\t\t\tif (siblingStyle.display === \'none\') continue;\n\t\t\t\tif (siblingStyle.visibility === \'hidden\') continue;\n\n\t\t\t\t// Check visual overlap\n\t\t\t\tconst siblingRect = sibling.getBoundingClientRect();\n\t\t\t\tif (!rectsOverlap(elementRect, siblingRect)) continue;\n\n\t\t\t\t// Compare stacking priority:\n\t\t\t\t// 1. Elements with explicit z-index > auto\n\t\t\t\t// 2. Positioned elements (absolute/fixed) > non-positioned\n\t\t\t\t// 3. Higher z-index value wins\n\t\t\t\tconst elementPriority = getStackingPriority(elementZIndex, elementPosition, parentZIndex);\n\t\t\t\tconst siblingPriority = getStackingPriority(siblingZIndex, siblingPosition, parentZIndex);\n\n\t\t\t\tif (siblingPriority > elementPriority) {\n\t\t\t\t\treturn true;\n\t\t\t\t}\n\t\t\t}\n\t\t\tcurrent = current.parentElement;\n\t\t}\n\n\t\treturn false;\n\t}\n\n\t/**\n\t * Parse z-index to numeric value for comparison\n\t */\n\tfunction getZIndex(style) {\n\t\tconst zIndex = style.zIndex;\n\t\tif (zIndex === \'auto\') return -Infinity;\n\t\tconst parsed = parseInt(zIndex, 10);\n\t\treturn isNaN(parsed) ? -Infinity : parsed;\n\t}\n\n\t/**\n\t * Calculate stacking priority for comparison\n\t * Returns a tuple [base, zIndex, isPositioned] for lexicographic comparison\n\t */\n\tfunction getStackingPriority(elementZIndex, elementPosition, parentZIndex) {\n\t\tconst isPositioned = elementPosition === \'absolute\' || elementPosition === \'fixed\' ||\n\t\t\telementPosition === \'relative\' || elementPosition === \'sticky\';\n\t\tconst hasExplicitZIndex = elementZIndex > -Infinity;\n\n\t\t// Base priority: positioned elements have higher base priority\n\t\t// Within same base, compare z-index values\n\t\t// If z-index is \'auto\' or negative, use parent context\n\t\tconst effectiveZIndex = hasExplicitZIndex ? elementZIndex : (parentZIndex > -Infinity ? parentZIndex : 0);\n\n\t\treturn [isPositioned ? 1 : 0, effectiveZIndex, isPositioned ? 1 : 0];\n\t}\n\n\t/**\n\t * Get visible siblings of an element (considering parent context)\n\t */\n\tfunction getVisibleSiblings(element) {\n\t\tif (!element.parentElement) return [];\n\n\t\tconst siblings = [];\n\t\tconst parent = element.parentElement;\n\n\t\t// Get parent\'s children\n\t\tfor (const child of parent.children) {\n\t\t\tif (child === element) continue;\n\n\t\t\tconst style = window.getComputedStyle(child);\n\t\t\tif (style.display === \'none\') continue;\n\t\t\tif (parseFloat(style.opacity) < 0.1) continue;\n\n\t\t\tsiblings.push(child);\n\t\t}\n\n\t\t// Also check parent\'s cousins (siblings of parent) for fixed/absolute positioned elements\n\t\tif (parent.parentElement && parent.parentElement !== document.body) {\n\t\t\tfor (const uncle of parent.parentElement.children) {\n\t\t\t\tif (uncle === parent) continue;\n\t\t\t\tif (uncle.tagName === \'SCRIPT\' || uncle.tagName === \'STYLE\') continue;\n\n\t\t\t\tconst uncleStyle = window.getComputedStyle(uncle);\n\t\t\t\tconst unclePosition = uncleStyle.position;\n\t\t\t\tconst uncleOpacity = parseFloat(uncleStyle.opacity) || 1;\n\n\t\t\t\t// Only consider positioned siblings\n\t\t\t\tif (unclePosition === \'fixed\' || unclePosition === \'absolute\') {\n\t\t\t\t\tif (uncleOpacity >= 0.1 && uncleStyle.display !== \'none\') {\n\t\t\t\t\t\t// Add children of positioned uncle that might overlap\n\t\t\t\t\t\tfor (const cousin of uncle.children) {\n\t\t\t\t\t\t\tconst cousinStyle = window.getComputedStyle(cousin);\n\t\t\t\t\t\t\tconst cousinOpacity = parseFloat(cousinStyle.opacity) || 1;\n\t\t\t\t\t\t\tif (cousinOpacity >= 0.1 && cousinStyle.display !== \'none\') {\n\t\t\t\t\t\t\t\tsiblings.push(cousin);\n\t\t\t\t\t\t\t}\n\t\t\t\t\t\t}\n\t\t\t\t\t}\n\t\t\t\t}\n\t\t\t}\n\t\t}\n\n\t\treturn siblings;\n\t}\n\n\t/**\n\t * Find the nearest ancestor that creates a stacking context\n\t */\n\tfunction getStackingContext(element) {\n\t\tlet current = element.parentElement;\n\t\twhile (current && current !== document.documentElement) {\n\t\t\tconst style = window.getComputedStyle(current);\n\t\t\tconst zIndex = style.zIndex;\n\t\t\tconst position = style.position;\n\t\t\tconst opacity = parseFloat(style.opacity) || 1;\n\n\t\t\t// Elements that create stacking contexts\n\t\t\tif (opacity < 1) return current;\n\t\t\tif (zIndex !== \'auto\') return current;\n\t\t\tif (position === \'fixed\') return current;\n\t\t\tif (position === \'absolute\' && zIndex !== \'auto\') return current;\n\t\t\tif (style.transform !== \'none\' && style.transform !== \'matrix(1, 0, 0, 1, 0, 0)\') return current;\n\t\t\tif (style.filter !== \'none\') return current;\n\t\t\tif (style.perspective !== \'none\') return current;\n\t\t\tif (style.clipPath !== \'none\') return current;\n\n\t\t\tcurrent = current.parentElement;\n\t\t}\n\t\treturn null;\n\t}\n\n\t/**\n\t * Check if two rectangles overlap (with small tolerance for rounding)\n\t */\n\tfunction rectsOverlap(rect1, rect2) {\n\t\tconst tolerance = 1;\n\t\treturn !(rect1.right + tolerance < rect2.left ||\n\t\t\trect2.right + tolerance < rect1.left ||\n\t\t\trect1.bottom + tolerance < rect2.top ||\n\t\t\trect2.bottom + tolerance < rect1.top);\n\t}\n\n\t/**\n\t * Get element attributes as a clean object\n\t */\n\tfunction getElementAttributes(element) {\n\t\tconst attrs = {};\n\t\tif (!element.attributes) return attrs;\n\n\t\tfor (const attr of element.attributes) {\n\t\t\t// Skip internal/noisy attributes\n\t\t\tif (attr.name.startsWith(\'data-reactid\') ||\n\t\t\t\tattr.name.startsWith(\'data-reactroot\') ||\n\t\t\t\tattr.name.startsWith(\'ng-\') ||\n\t\t\t\tattr.name === \'style\') {\n\t\t\t\tcontinue;\n\t\t\t}\n\t\t\tattrs[attr.name] = attr.value;\n\t\t}\n\n\t\treturn attrs;\n\t}\n\n\t/**\n\t * Get text content for a node\n\t */\n\tfunction getNodeText(node) {\n\t\tif (node.nodeType === Node.TEXT_NODE) {\n\t\t\treturn node.textContent.trim();\n\t\t}\n\t\tif (node.nodeType === Node.ELEMENT_NODE) {\n\t\t\t// For input elements, get value\n\t\t\tif (node.tagName === \'INPUT\' || node.tagName === \'TEXTAREA\') {\n\t\t\t\treturn node.value || node.placeholder || \'\';\n\t\t\t}\n\t\t\t// For select elements, get selected option text\n\t\t\tif (node.tagName === \'SELECT\' && node.selectedOptions && node.selectedOptions.length > 0) {\n\t\t\t\treturn node.selectedOptions[0].textContent.trim();\n\t\t\t}\n\t\t}\n\t\treturn \'\';\n\t}\n\n\t/**\n\t * Create highlight overlay for an element\n\t * @param {Element} element - The DOM element to highlight\n\t * @param {number} index - The highlight index\n\t * @param {boolean} isFocused - Whether the element is focused\n\t * @param {boolean} isTopElement - Whether the element is topmost\n\t * @param {Object} adjustedRect - Pre-adjusted rect with iframe offsets applied\n\t */\n\tfunction createHighlight(element, index, isFocused, isTopElement, adjustedRect) {\n\t\t// Skip creating highlights for hidden elements (covered by other elements)\n\t\tif (isTopElement === false) {\n\t\t\treturn;\n\t\t}\n\n\t\tif (!highlightContainer) {\n\t\t\thighlightContainer = document.createElement(\'div\');\n\t\t\thighlightContainer.id = \'browser-use-highlight-container\';\n\t\t\thighlightContainer.style.cssText = `\n\t\t\t\tposition: fixed;\n\t\t\t\ttop: 0;\n\t\t\t\tleft: 0;\n\t\t\t\twidth: 100%;\n\t\t\t\theight: 100%;\n\t\t\t\tpointer-events: none;\n\t\t\t\tz-index: 2147483647;\n\t\t\t`;\n\t\t\tdocument.body.appendChild(highlightContainer);\n\t\t}\n\n\t\t// Use pre-adjusted rect (already has iframe offsets applied)\n\t\tconst rect = adjustedRect || element.getBoundingClientRect();\n\t\tconst highlight = document.createElement(\'div\');\n\t\thighlight.className = \'browser-use-highlight\';\n\t\thighlight.setAttribute(\'data-highlight-index\', index);\n\n\t\tconst color = isFocused ? \'rgba(255, 127, 39, 0.5)\' : \'rgba(255, 127, 39, 0.3)\';\n\t\tconst borderColor = isFocused ? \'rgb(255, 127, 39)\' : \'rgba(255, 127, 39, 0.8)\';\n\n\t\thighlight.style.cssText = `\n\t\t\tposition: fixed;\n\t\t\tleft: ${rect.left}px;\n\t\t\ttop: ${rect.top}px;\n\t\t\twidth: ${rect.width}px;\n\t\t\theight: ${rect.height}px;\n\t\t\tbackground-color: ${color};\n\t\t\tborder: 2px solid ${borderColor};\n\t\t\tbox-sizing: border-box;\n\t\t\tpointer-events: none;\n\t\t`;\n\n\t\t// Add index label\n\t\tconst label = document.createElement(\'span\');\n\t\tlabel.style.cssText = `\n\t\t\tposition: absolute;\n\t\t\ttop: -18px;\n\t\t\tleft: 0;\n\t\t\tbackground-color: rgb(255, 127, 39);\n\t\t\tcolor: white;\n\t\t\tpadding: 2px 6px;\n\t\t\tfont-size: 11px;\n\t\t\tfont-family: monospace;\n\t\t\tborder-radius: 3px;\n\t\t\twhite-space: nowrap;\n\t\t`;\n\t\tlabel.textContent = String(index);\n\t\thighlight.appendChild(label);\n\n\t\thighlightContainer.appendChild(highlight);\n\t}\n\n\t/**\n\t * Process a single DOM node\n\t */\n\tfunction processNode(node, parentId) {\n\t\tconst nodeId = nodeIdCounter++;\n\t\tperfMetrics.nodeMetrics.totalNodes++;\n\n\t\t// Handle text nodes\n\t\tif (node.nodeType === Node.TEXT_NODE) {\n\t\t\tlet text = node.textContent.trim();\n\t\t\tif (!text) return null;\n\n\t\t\t// Cap text node content to 100 chars to match CDP behavior\n\t\t\tif (text.length > 100) {\n\t\t\t\ttext = text.substring(0, 100);\n\t\t\t}\n\n\t\t\tconst isVisible = node.parentElement ? isElementVisible(node.parentElement) : false;\n\t\t\tif (isVisible) perfMetrics.nodeMetrics.visibleNodes++;\n\n\t\t\tnodeMap[nodeId] = {\n\t\t\t\ttype: \'TEXT_NODE\',\n\t\t\t\ttext: text,\n\t\t\t\tisVisible: isVisible,\n\t\t\t\tchildren: []\n\t\t\t};\n\t\t\tnodeParentMap[nodeId] = parentId;\n\n\t\t\tperfMetrics.nodeMetrics.processedNodes++;\n\t\t\treturn nodeId;\n\t\t}\n\n\t\t// Skip non-element nodes\n\t\tif (node.nodeType !== Node.ELEMENT_NODE) {\n\t\t\treturn null;\n\t\t}\n\n\t\t// Skip certain tags\n\t\tif (SKIP_TAGS.has(node.tagName)) {\n\t\t\treturn null;\n\t\t}\n\n\t\tconst isVisible = isElementVisible(node);\n\t\tconst inViewport = isInViewport(node, viewportExpansion);\n\t\tconst isInteractive = isElementInteractive(node);\n\t\tconst isTop = isTopElement(node);\n\n\t\tif (isVisible) perfMetrics.nodeMetrics.visibleNodes++;\n\n\t\t// Get element bounds\n\t\tconst rect = node.getBoundingClientRect();\n\t\t// Apply iframe offset to convert iframe-relative coords to main document coords\n\t\tconst viewport = {\n\t\t\tx: rect.left + iframeOffsetX,\n\t\t\ty: rect.top + iframeOffsetY,\n\t\t\twidth: rect.width,\n\t\t\theight: rect.height\n\t\t};\n\n\t\t// Collect interactive elements for later sorted index assignment\n\t\tlet currentHighlightIndex = null;\n\n\t\tif (isInteractive && isVisible && (inViewport || viewportExpansion > 0)) {\n\t\t\tperfMetrics.nodeMetrics.interactiveNodes++;\n\t\t\t// Create adjusted rect with iframe offsets for correct sorting and highlighting\n\t\t\tconst adjustedRect = {\n\t\t\t\tleft: rect.left + iframeOffsetX,\n\t\t\t\ttop: rect.top + iframeOffsetY,\n\t\t\t\tright: rect.right + iframeOffsetX,\n\t\t\t\tbottom: rect.bottom + iframeOffsetY,\n\t\t\t\twidth: rect.width,\n\t\t\t\theight: rect.height\n\t\t\t};\n\t\t\t// Store for later sorting by visual position\n\t\t\tinteractiveElements.push({\n\t\t\t\tnodeId: nodeId,\n\t\t\t\telement: node,\n\t\t\t\trect: adjustedRect,\n\t\t\t\tisTop: isTop\n\t\t\t});\n\t\t\t// Assign a temporary placeholder (will be updated after sorting)\n\t\t\tcurrentHighlightIndex = -1;\n\t\t}\n\n\t\t// Process children\n\t\tconst childIds = [];\n\t\tfor (const child of node.childNodes) {\n\t\t\tconst childId = processNode(child, nodeId);\n\t\t\tif (childId !== null) {\n\t\t\t\tchildIds.push(childId);\n\t\t\t}\n\t\t}\n\n\t\t// Get node text (direct text, not from children)\n\t\tlet directText = \'\';\n\t\tfor (const child of node.childNodes) {\n\t\t\tif (child.nodeType === Node.TEXT_NODE) {\n\t\t\t\tconst text = child.textContent.trim();\n\t\t\t\tif (text) directText += text + \' \';\n\t\t\t}\n\t\t}\n\t\tdirectText = directText.trim();\n\n\t\t// Build node data\n\t\t// Cap text length to 100 chars to match CDP accessibility tree behavior and reduce token usage\n\t\tlet nodeText = isInteractive ? (node.innerText || node.textContent || \'\').trim() : (directText || getNodeText(node));\n\t\tif (nodeText && nodeText.length > 100) {\n\t\t\tnodeText = nodeText.substring(0, 100);\n\t\t}\n\n\t\t// Check if element is actually scrollable (has overflow content AND CSS allows scrolling)\n\t\tlet isActuallyScrollable = false;\n\t\tconst hasOverflowContent = node.scrollHeight > node.clientHeight + 1 || node.scrollWidth > node.clientWidth + 1;\n\t\tif (hasOverflowContent) {\n\t\t\tconst style = window.getComputedStyle(node);\n\t\t\tconst overflow = style.overflow.toLowerCase();\n\t\t\tconst overflowX = style.overflowX.toLowerCase();\n\t\t\tconst overflowY = style.overflowY.toLowerCase();\n\t\t\t// Only mark as scrollable if CSS explicitly allows scrolling\n\t\t\tconst allowsScroll = [\'auto\', \'scroll\', \'overlay\'].some(v =>\n\t\t\t\toverflow === v || overflowX === v || overflowY === v\n\t\t\t);\n\t\t\t// For body/html, also consider them scrollable if they have overflow content\n\t\t\tconst isRootElement = node.tagName.toLowerCase() === \'body\' || node.tagName.toLowerCase() === \'html\';\n\t\t\tisActuallyScrollable = allowsScroll || isRootElement;\n\t\t}\n\n\t\t// Always include xpath for interactive elements (needed for reliable Selenium clicks)\n\t\t// In compact mode, only generate xpath for elements that will get a highlightIndex\n\t\t// Note: currentHighlightIndex is -1 at this point (temporary placeholder),\n\t\t// it gets updated after sorting. Use isInteractive check instead.\n\t\tconst shouldIncludeXpath = !compactMode || (compactMode && isInteractive && isVisible);\n\n\t\tconst nodeData = {\n\t\t\ttagName: node.tagName.toLowerCase(),\n\t\t\tattributes: getElementAttributes(node),\n\t\t\txpath: shouldIncludeXpath ? getXPath(node) : undefined,\n\t\t\tisVisible: isVisible,\n\t\t\tisInteractive: isInteractive,\n\t\t\tisTopElement: isTop,\n\t\t\tisInViewport: inViewport,\n\t\t\thighlightIndex: currentHighlightIndex,\n\t\t\tshadowRoot: !!node.shadowRoot,\n\t\t\tviewport: viewport,\n\t\t\tchildren: childIds,\n\t\t\ttext: nodeText,\n\t\t\tariaLabel: node.getAttribute(\'aria-label\'),\n\t\t\tariaDescription: node.getAttribute(\'aria-describedby\'),\n\t\t\ttitle: node.getAttribute(\'title\'),\n\t\t\trole: node.getAttribute(\'role\'),\n\t\t\tisScrollable: isActuallyScrollable\n\t\t};\n\n\t\tnodeMap[nodeId] = nodeData;\n\t\tnodeParentMap[nodeId] = parentId;\n\t\tperfMetrics.nodeMetrics.processedNodes++;\n\n\t\treturn nodeId;\n\t}\n\n\t/**\n\t * Generate XPath for an element\n\t */\n\tfunction getXPath(element) {\n\t\tif (!element) return \'\';\n\t\tif (element.id) return `//*[@id="${element.id}"]`;\n\n\t\tconst parts = [];\n\t\tlet current = element;\n\n\t\twhile (current && current.nodeType === Node.ELEMENT_NODE) {\n\t\t\tlet index = 1;\n\t\t\tlet hasSameTagSiblings = false;\n\t\t\tconst tagName = current.tagName.toLowerCase();\n\n\t\t\t// Count previous siblings of same tag\n\t\t\tlet sibling = current.previousSibling;\n\t\t\twhile (sibling) {\n\t\t\t\tif (sibling.nodeType === Node.ELEMENT_NODE && sibling.tagName.toLowerCase() === tagName) {\n\t\t\t\t\tindex++;\n\t\t\t\t\thasSameTagSiblings = true;\n\t\t\t\t}\n\t\t\t\tsibling = sibling.previousSibling;\n\t\t\t}\n\n\t\t\t// Check if there are next siblings of same tag\n\t\t\tsibling = current.nextSibling;\n\t\t\twhile (sibling && !hasSameTagSiblings) {\n\t\t\t\tif (sibling.nodeType === Node.ELEMENT_NODE && sibling.tagName.toLowerCase() === tagName) {\n\t\t\t\t\thasSameTagSiblings = true;\n\t\t\t\t}\n\t\t\t\tsibling = sibling.nextSibling;\n\t\t\t}\n\n\t\t\tconst part = hasSameTagSiblings ? `${tagName}[${index}]` : tagName;\n\t\t\tparts.unshift(part);\n\n\t\t\tcurrent = current.parentNode;\n\t\t}\n\n\t\treturn \'/\' + parts.join(\'/\');\n\t}\n\n\t/**\n\t * Process shadow DOM roots\n\t */\n\tfunction processShadowRoots(element, parentId) {\n\t\tif (!element.shadowRoot) return;\n\n\t\tfor (const child of element.shadowRoot.childNodes) {\n\t\t\tprocessNode(child, parentId);\n\t\t}\n\t}\n\n\n\t/**\n\t * Create an iframe node for the node map\n\t */\n\tfunction createIframeNode(iframe, type) {\n\t\tconst rect = iframe.getBoundingClientRect();\n\t\tconst nodeId = nodeIdCounter++;\n\n\t\tif (debugMode) {\n\t\t\tconsole.log(`[Browser-Use DOM] Creating iframe node ${nodeId} (${type}): ${iframe.src.substring(0, 50)}...`);\n\t\t}\n\n\t\tconst iframeNode = {\n\t\t\tnodeId: nodeId,\n\t\t\ttagName: \'iframe\',\n\t\t\tattributes: {\n\t\t\t\tsrc: iframe.src.substring(0, 200),  // Truncate long URLs\n\t\t\t\t\'data-iframe-type\': type,\n\t\t\t\ttitle: iframe.title || \'\',\n\t\t\t\t\'aria-label\': iframe.getAttribute(\'aria-label\') || \'\',\n\t\t\t\tname: iframe.name || \'\',\n\t\t\t\tid: iframe.id || \'\'\n\t\t\t},\n\t\t\tisVisible: rect.width > 0 && rect.height > 0,\n\t\t\tisInteractive: true,\n\t\t\tisTopElement: true,\n\t\t\tisInViewport: isInViewport(iframe),\n\t\t\thighlightIndex: -1,\n\t\t\tviewport: {\n\t\t\t\tx: rect.left + window.scrollX,\n\t\t\t\ty: rect.top + window.scrollY,\n\t\t\t\twidth: rect.width,\n\t\t\t\theight: rect.height\n\t\t\t},\n\t\t\ttext: \'\',\n\t\t\tchildren: [],\n\t\t\tiframeContent: type === \'same-origin\' ? \'extractable\' : \'cross-origin-blocked\',\n\t\t\tiframeDepth: 0\n\t\t};\n\n\t\treturn iframeNode;\n\t}\n\n\tfunction processIframe(iframe, parentId, depth) {\n\t\tif (iframeCount >= maxIframes) {\n\t\t\tif (debugMode) {\n\t\t\t\tconsole.log(`[Browser-Use DOM] Skipping iframe - max iframes (${maxIframes}) reached`);\n\t\t\t}\n\t\t\treturn;\n\t\t}\n\n\t\tif (depth >= maxIframeDepth) {\n\t\t\tif (debugMode) {\n\t\t\t\tconsole.log(`[Browser-Use DOM] Skipping iframe at depth ${depth} - max depth (${maxIframeDepth}) exceeded`);\n\t\t\t}\n\t\t\treturn;\n\t\t}\n\n\t\t// Skip iframes that are not visible or not the top element from the parent document.\n\t\t// This filters out hidden ad iframes, iframes behind overlays, off-screen iframes, etc.\n\t\t// without relying on fragile pattern matching.\n\t\tif (!isElementVisible(iframe) || !isTopElement(iframe)) {\n\t\t\tif (debugMode) {\n\t\t\t\tconsole.log(`[Browser-Use DOM] Skipping non-visible/obstructed iframe: ${iframe.id || iframe.src?.substring(0, 60) || \'unknown\'}`);\n\t\t\t}\n\t\t\treturn;\n\t\t}\n\n\t\ttry {\n\t\t\t// Try to access same-origin iframe content\n\t\t\tconst iframeDoc = iframe.contentDocument || iframe.contentWindow.document;\n\n\t\t\tif (iframeDoc && iframeDoc.body) {\n\t\t\t\tconst type = \'same-origin\';\n\t\t\t\tconst iframeNode = createIframeNode(iframe, type);\n\t\t\t\tiframeNode.iframeDepth = depth;\n\t\t\t\tnodeMap[iframeNode.nodeId] = iframeNode;\n\t\t\t\tiframeNodes.push(iframeNode);\n\t\t\t\tiframeCount++;\n\n\t\t\t\t// Save current iframe offset and accumulate this iframe\'s position\n\t\t\t\tconst iframeRect = iframe.getBoundingClientRect();\n\t\t\t\tconst prevOffsetX = iframeOffsetX;\n\t\t\t\tconst prevOffsetY = iframeOffsetY;\n\t\t\t\tiframeOffsetX += iframeRect.left;\n\t\t\t\tiframeOffsetY += iframeRect.top;\n\n\t\t\t\t// Recursively process iframe contents (coordinates will be adjusted by offsets)\n\t\t\t\tconst iframeRootId = processNode(iframeDoc.body, iframeNode.nodeId);\n\t\t\t\tiframeNode.children = [iframeRootId];\n\n\t\t\t\t// Restore previous iframe offset\n\t\t\t\tiframeOffsetX = prevOffsetX;\n\t\t\t\tiframeOffsetY = prevOffsetY;\n\n\t\t\t\tperfMetrics.nodeMetrics.filteredEmptyInteractive++;\n\t\t\t\tif (debugMode) {\n\t\t\t\t\tconsole.log(`[Browser-Use DOM] Processed same-origin iframe at depth ${depth}`);\n\t\t\t\t}\n\t\t\t}\n\t\t} catch (e) {\n\t\t\t// Cross-origin iframe - can\'t access content\n\t\t\tif (includeCrossOriginIframes) {\n\t\t\t\tconst iframeNode = createIframeNode(iframe, \'cross-origin\');\n\t\t\t\tiframeNode.iframeDepth = depth;\n\t\t\t\tiframeNode.iframeContent = \'cross-origin-blocked\';\n\t\t\t\tnodeMap[iframeNode.nodeId] = iframeNode;\n\t\t\t\tiframeNodes.push(iframeNode);\n\t\t\t\tiframeCount++;\n\n\t\t\t\tif (debugMode) {\n\t\t\t\t\tconsole.log(`[Browser-Use DOM] Recorded cross-origin iframe at depth ${depth}: ${iframe.src.substring(0, 50)}...`);\n\t\t\t\t}\n\t\t\t}\n\t\t}\n\t}\n\n\t/**\n\t * Find and process all iframes in a document\n\t */\n\tfunction processAllIframes(rootElement, depth) {\n\t\tif (depth >= maxIframeDepth) return;\n\n\t\tconst iframes = rootElement.querySelectorAll(\'iframe\');\n\t\tfor (const iframe of iframes) {\n\t\t\tprocessIframe(iframe, null, depth);\n\t\t\t// Process nested iframes within this iframe if same-origin\n\t\t\ttry {\n\t\t\t\tconst iframeDoc = iframe.contentDocument || iframe.contentWindow.document;\n\t\t\t\tif (iframeDoc) {\n\t\t\t\t\tprocessAllIframes(iframeDoc.documentElement || iframeDoc.body, depth + 1);\n\t\t\t\t}\n\t\t\t} catch (e) {\n\t\t\t\t// Cross-origin - skip nested processing\n\t\t\t}\n\t\t}\n\t}\n\n\t/**\n\t * Detect and process high-z-index popup/overlay containers\n\t * These are often used for modals, login popups, cookie banners, etc.\n\t */\n\tfunction processPopupContainers() {\n\t\tconst popupContainers = [];\n\n\t\t// Find all elements with high z-index that might be popups\n\t\tconst allElements = document.querySelectorAll(\'*\');\n\n\t\tfor (const element of allElements) {\n\t\t\tif (SKIP_TAGS.has(element.tagName)) continue;\n\n\t\t\tconst style = window.getComputedStyle(element);\n\t\t\tconst zIndex = parseInt(style.zIndex, 10);\n\t\t\tconst position = style.position;\n\n\t\t\t// Look for elements with:\n\t\t\t// 1. High z-index (> 9000, common for overlays)\n\t\t\t// 2. Fixed or absolute positioning\n\t\t\t// 3. Visible and has dimensions\n\t\t\tif (zIndex > 9000 &&\n\t\t\t\t(position === \'fixed\' || position === \'absolute\') &&\n\t\t\t\tstyle.display !== \'none\' &&\n\t\t\t\tstyle.visibility !== \'hidden\') {\n\n\t\t\t\tconst rect = element.getBoundingClientRect();\n\t\t\t\tif (rect.width > 50 && rect.height > 50) {\n\t\t\t\t\t// Check if this looks like a popup container\n\t\t\t\t\tconst classes = element.className || \'\';\n\t\t\t\t\tconst id = element.id || \'\';\n\t\t\t\t\tconst combined = (classes + \' \' + id).toLowerCase();\n\n\t\t\t\t\tconst isLikelyPopup =\n\t\t\t\t\t\tcombined.includes(\'modal\') ||\n\t\t\t\t\t\tcombined.includes(\'popup\') ||\n\t\t\t\t\t\tcombined.includes(\'dialog\') ||\n\t\t\t\t\t\tcombined.includes(\'overlay\') ||\n\t\t\t\t\t\tcombined.includes(\'signin\') ||\n\t\t\t\t\t\tcombined.includes(\'login\') ||\n\t\t\t\t\t\tcombined.includes(\'consent\') ||\n\t\t\t\t\t\tcombined.includes(\'cookie\') ||\n\t\t\t\t\t\tcombined.includes(\'banner\') ||\n\t\t\t\t\t\telement.getAttribute(\'role\') === \'dialog\' ||\n\t\t\t\t\t\telement.getAttribute(\'role\') === \'alertdialog\' ||\n\t\t\t\t\t\telement.getAttribute(\'aria-modal\') === \'true\';\n\n\t\t\t\t\tif (isLikelyPopup) {\n\t\t\t\t\t\tpopupContainers.push({\n\t\t\t\t\t\t\telement: element,\n\t\t\t\t\t\t\trect: rect,\n\t\t\t\t\t\t\tzIndex: zIndex,\n\t\t\t\t\t\t\ttype: \'popup-container\'\n\t\t\t\t\t\t});\n\n\t\t\t\t\t\tif (debugMode) {\n\t\t\t\t\t\t\tconsole.log(`[Browser-Use DOM] Detected popup container: ${element.tagName}#${id}.${classes.substring(0, 50)} z-index=${zIndex}`);\n\t\t\t\t\t\t}\n\t\t\t\t\t}\n\t\t\t\t}\n\t\t\t}\n\t\t}\n\n\t\treturn popupContainers;\n\t}\n\n\t// Main execution\n\ttry {\n\t\t// Start from document body\n\t\tconst rootId = processNode(document.body, null);\n\n\t\t// Process all iframes (same-origin and cross-origin)\n\t\tif (maxIframes > 0) {\n\t\t\tprocessAllIframes(document.documentElement, 0);\n\t\t\tif (debugMode) {\n\t\t\t\tconsole.log(`[Browser-Use DOM] Processed ${iframeCount} iframes (max depth: ${maxIframeDepth})`);\n\t\t\t}\n\t\t}\n\n\t\t// Detect popup containers that might be overlaying page content\n\t\tconst popupContainers = processPopupContainers();\n\t\tif (debugMode && popupContainers.length > 0) {\n\t\t\tconsole.log(`[Browser-Use DOM] Detected ${popupContainers.length} popup containers`);\n\t\t}\n\n\t\tif (debugMode) {\n\t\t\tconsole.log(`[Browser-Use DOM] ==================== INTERACTIVE ELEMENTS DEBUG ====================`);\n\t\t\tconsole.log(`[Browser-Use DOM] Total interactive elements found: ${interactiveElements.length}`);\n\t\t\tinteractiveElements.forEach((item, idx) => {\n\t\t\t\tconst el = item.element;\n\t\t\t\tconst rect = item.rect;\n\t\t\t\tconst text = el.textContent?.trim().substring(0, 30) || \'\';\n\t\t\t\tconst classes = el.className || \'\';\n\t\t\t\tconsole.log(`[Browser-Use DOM]   ${idx}: ${el.tagName} class="${classes}" text="${text}" pos=(${Math.round(rect.left)},${Math.round(rect.top)}) size=${Math.round(rect.width)}x${Math.round(rect.height)}`);\n\t\t\t});\n\t\t}\n\n\t\t// Aggressively filter out nested/overlapping interactive elements\n\t\t// Strategy: For each element, check if it has ANY interactive descendant - if so, skip it\n\t\t// This keeps only the innermost interactive elements\n\t\t// Enhanced to also filter out visually overlapping elements (not just DOM containment)\n\t\tconst filteredInteractive = [];\n\t\tconst filteredOutParents = [];\n\t\tconst filteredOutOverlaps = [];\n\n\t\tfor (let i = 0; i < interactiveElements.length; i++) {\n\t\t\tconst current = interactiveElements[i];\n\t\t\tlet shouldFilter = false;\n\t\t\tlet filterReason = null;\n\n\t\t\tfor (let j = 0; j < interactiveElements.length; j++) {\n\t\t\t\tif (i === j) continue;\n\t\t\t\tconst other = interactiveElements[j];\n\n\t\t\t\t// Check if this element contains ANY other interactive element\n\t\t\t\t// (Innermost rule: parents usually filter themselves out if they have interactive children)\n\t\t\t\tif (current.element.contains(other.element) && current.element !== other.element) {\n\t\t\t\t\t// EXCEPTION: If I am a link or button and the child is NOT a link/button, \n\t\t\t\t\t// I am the primary target, so keep me.\n\t\t\t\t\tconst currentIsTarget = current.element.tagName === \'A\' || current.element.tagName === \'BUTTON\' || current.element.getAttribute(\'role\') === \'button\';\n\t\t\t\t\tconst otherIsTarget = other.element.tagName === \'A\' || other.element.tagName === \'BUTTON\' || other.element.getAttribute(\'role\') === \'button\';\n\n\t\t\t\t\tif (currentIsTarget && !otherIsTarget) {\n\t\t\t\t\t\t// Don\'t filter parent link/button when child is just a generic interactive element\n\t\t\t\t\t\tcontinue;\n\t\t\t\t\t}\n\n\t\t\t\t\tshouldFilter = true;\n\t\t\t\t\tfilterReason = \'contains\';\n\t\t\t\t\tif (debugMode) {\n\t\t\t\t\t\tfilteredOutParents.push({\n\t\t\t\t\t\t\tparent: current,\n\t\t\t\t\t\t\tchild: other\n\t\t\t\t\t\t});\n\t\t\t\t\t}\n\t\t\t\t\tbreak;\n\t\t\t\t}\n\n\t\t\t\t// Check if this element is CONTAINED by another interactive element\n\t\t\t\tif (other.element.contains(current.element) && other.element !== current.element) {\n\t\t\t\t\t// If my parent is a link or button and I am NOT a link/button, \n\t\t\t\t\t// the link/button is the primary target, so filter me out.\n\t\t\t\t\tconst otherIsTarget = other.element.tagName === \'A\' || other.element.tagName === \'BUTTON\' || other.element.getAttribute(\'role\') === \'button\';\n\t\t\t\t\tconst currentIsTarget = current.element.tagName === \'A\' || current.element.tagName === \'BUTTON\' || current.element.getAttribute(\'role\') === \'button\';\n\n\t\t\t\t\tif (otherIsTarget && !currentIsTarget) {\n\t\t\t\t\t\t// Don\'t filter if there\'s an intermediate button/interactive element\n\t\t\t\t\t\t// between the target and this element. E.g. <a><button><span>Sign In</span></button></a>\n\t\t\t\t\t\t// The span shouldn\'t be filtered by the distant <a> when <button> is in between.\n\t\t\t\t\t\tlet hasIntermediateButton = false;\n\t\t\t\t\t\tlet p = current.element.parentElement;\n\t\t\t\t\t\twhile (p && p !== other.element) {\n\t\t\t\t\t\t\tif (p.tagName === \'BUTTON\' || p.getAttribute(\'role\') === \'button\') {\n\t\t\t\t\t\t\t\thasIntermediateButton = true;\n\t\t\t\t\t\t\t\tbreak;\n\t\t\t\t\t\t\t}\n\t\t\t\t\t\t\tp = p.parentElement;\n\t\t\t\t\t\t}\n\t\t\t\t\t\tif (!hasIntermediateButton) {\n\t\t\t\t\t\t\tshouldFilter = true;\n\t\t\t\t\t\t\tfilterReason = \'contained-by-link\';\n\t\t\t\t\t\t\tbreak;\n\t\t\t\t\t\t}\n\t\t\t\t\t}\n\t\t\t\t}\n\n\t\t\t\t// Check for visual overlap between non-ancestor elements\n\t\t\t\t// This handles positioned siblings, modals, tooltips, etc.\n\t\t\t\tif (!shouldFilter) {\n\t\t\t\t\tconst currentRect = current.rect;\n\t\t\t\t\tconst otherRect = other.rect;\n\n\t\t\t\t\t// Check bounding box overlap with tolerance\n\t\t\t\t\tif (rectsOverlap(currentRect, otherRect)) {\n\t\t\t\t\t\t// Elements overlap visually - keep the one that should be on top\n\t\t\t\t\t\t// Priority: element with smaller area is likely the intended target (button inside container)\n\t\t\t\t\t\t// OR if one is marked as top element, keep that one\n\t\t\t\t\t\tconst currentArea = currentRect.width * currentRect.height;\n\t\t\t\t\t\tconst otherArea = otherRect.width * otherRect.height;\n\n\t\t\t\t\t\t// Keep the smaller element (usually the button/link, not the container)\n\t\t\t\t\t\t// UNLESS the current element is specifically marked as top\n\t\t\t\t\t\tif (currentArea > otherArea && !current.isTop) {\n\t\t\t\t\t\t\tshouldFilter = true;\n\t\t\t\t\t\t\tfilterReason = \'overlap\';\n\t\t\t\t\t\t\tif (debugMode) {\n\t\t\t\t\t\t\t\tfilteredOutOverlaps.push({\n\t\t\t\t\t\t\t\t\tfiltered: current,\n\t\t\t\t\t\t\t\t\tkept: other,\n\t\t\t\t\t\t\t\t\treason: \'larger element overlapped by smaller\'\n\t\t\t\t\t\t\t\t});\n\t\t\t\t\t\t\t}\n\t\t\t\t\t\t\tbreak;\n\t\t\t\t\t\t}\n\t\t\t\t\t}\n\t\t\t\t}\n\t\t\t}\n\n\t\t\tif (!shouldFilter) {\n\t\t\t\tfilteredInteractive.push(current);\n\t\t\t}\n\t\t}\n\n\t\tif (debugMode) {\n\t\t\tconsole.log(`[Browser-Use DOM] ==================== FILTERING RESULTS ====================`);\n\t\t\tconsole.log(`[Browser-Use DOM] Filtered out ${interactiveElements.length - filteredInteractive.length} parent elements`);\n\t\t\tfilteredOutParents.forEach(({ parent, child }) => {\n\t\t\t\tconst pEl = parent.element;\n\t\t\t\tconst cEl = child.element;\n\t\t\t\tconsole.log(`[Browser-Use DOM]   ❌ ${pEl.tagName}.${pEl.className || \'no-class\'} (contains ${cEl.tagName}.${cEl.className || \'no-class\'})`);\n\t\t\t});\n\t\t\tfilteredOutOverlaps.forEach(({ filtered, kept, reason }) => {\n\t\t\t\tconst fEl = filtered.element;\n\t\t\t\tconst kEl = kept.element;\n\t\t\t\tconsole.log(`[Browser-Use DOM]   ❌ ${fEl.tagName}.${fEl.className || \'no-class\'} (overlap: ${reason}, kept ${kEl.tagName})`);\n\t\t\t});\n\t\t\tconsole.log(`[Browser-Use DOM] Kept ${filteredInteractive.length} innermost elements:`);\n\t\t\tfilteredInteractive.forEach((item, idx) => {\n\t\t\t\tconst el = item.element;\n\t\t\t\tconst rect = item.rect;\n\t\t\t\tconst text = el.textContent?.trim().substring(0, 30) || \'\';\n\t\t\t\tconsole.log(`[Browser-Use DOM]   ✓ ${idx}: ${el.tagName}.${el.className || \'no-class\'} "${text}" pos=(${Math.round(rect.left)},${Math.round(rect.top)})`);\n\t\t\t});\n\t\t}\n\n\t\tif (debugMode) {\n\t\t\tconsole.log(`[Browser-Use DOM] ==================== FILTERING RESULTS ====================`);\n\t\t\tconsole.log(`[Browser-Use DOM] Filtered out ${interactiveElements.length - filteredInteractive.length} parent elements`);\n\t\t\tfilteredOutParents.forEach(({ parent, child }) => {\n\t\t\t\tconst pEl = parent.element;\n\t\t\t\tconst cEl = child.element;\n\t\t\t\tconsole.log(`[Browser-Use DOM]   ❌ ${pEl.tagName}.${pEl.className || \'no-class\'} (contains ${cEl.tagName}.${cEl.className || \'no-class\'})`);\n\t\t\t});\n\t\t\tconsole.log(`[Browser-Use DOM] Kept ${filteredInteractive.length} innermost elements:`);\n\t\t\tfilteredInteractive.forEach((item, idx) => {\n\t\t\t\tconst el = item.element;\n\t\t\t\tconst rect = item.rect;\n\t\t\t\tconst text = el.textContent?.trim().substring(0, 30) || \'\';\n\t\t\t\tconsole.log(`[Browser-Use DOM]   ✓ ${idx}: ${el.tagName}.${el.className || \'no-class\'} "${text}" pos=(${Math.round(rect.left)},${Math.round(rect.top)})`);\n\t\t\t});\n\t\t}\n\n\t\t// Sort filtered interactive elements by visual position (top-to-bottom, left-to-right)\n\t\tfilteredInteractive.sort((a, b) => {\n\t\t\tconst rectA = a.rect;\n\t\t\tconst rectB = b.rect;\n\n\t\t\t// Primary sort: top position\n\t\t\tconst topDiff = rectA.top - rectB.top;\n\t\t\tif (Math.abs(topDiff) > 5) { // 5px tolerance for "same row"\n\t\t\t\treturn topDiff;\n\t\t\t}\n\n\t\t\t// Secondary sort: left position (for elements on same row)\n\t\t\treturn rectA.left - rectB.left;\n\t\t});\n\n\t\tif (debugMode) {\n\t\t\tconsole.log(`[Browser-Use DOM] Sorted ${filteredInteractive.length} interactive elements by visual position`);\n\t\t}\n\n\t\t// Assign highlight indices to filtered interactive elements (stable indices for LLM)\n\t\t// Visual highlights will be filtered in createHighlight to only show top elements\n\t\tif (debugMode) {\n\t\t\tconsole.log(`[Browser-Use DOM] About to assign indices to ${filteredInteractive.length} elements`);\n\t\t}\n\n\t\tfilteredInteractive.forEach((item, index) => {\n\t\t\tconst nodeData = nodeMap[item.nodeId];\n\t\t\tif (nodeData) {\n\t\t\t\t// Update the highlightIndex in the actual nodeMap\n\t\t\t\tnodeMap[item.nodeId].highlightIndex = index;\n\t\t\t\t// Store isTopElement for visual filtering\n\t\t\t\tnodeMap[item.nodeId].isTopElement = item.isTop;\n\n\t\t\t\tif (debugMode && index < 15) {\n\t\t\t\t\tconsole.log(`[Browser-Use DOM] Assigned index ${index} to ${nodeData.tagName} nodeId=${item.nodeId}`);\n\t\t\t\t}\n\n\t\t\t\t// Create visual highlight if enabled (only for topmost elements)\n\t\t\t\tif (doHighlightElements) {\n\t\t\t\t\tconst isFocused = focusHighlightIndex === index;\n\t\t\t\t\t// Pass the pre-adjusted rect (with iframe offsets) for correct positioning\n\t\t\t\t\tcreateHighlight(item.element, index, isFocused, item.isTop, item.rect);\n\t\t\t\t}\n\t\t\t} else {\n\t\t\t\tif (debugMode) {\n\t\t\t\t\tconsole.warn(`[Browser-Use DOM] WARNING: nodeId ${item.nodeId} not found in nodeMap!`);\n\t\t\t\t}\n\t\t\t}\n\t\t});\n\n\t\t// Verify the update worked (AFTER the forEach)\n\t\tif (debugMode && filteredInteractive.length > 0) {\n\t\t\tconst firstInteractive = filteredInteractive[0];\n\t\t\tconst verifyNode = nodeMap[firstInteractive.nodeId];\n\t\t\tconsole.log(`[Browser-Use DOM] ✅ Verification - nodeMap[${firstInteractive.nodeId}].highlightIndex = ${verifyNode ? verifyNode.highlightIndex : \'NOT_FOUND\'} (should be 0)`);\n\t\t}\n\n\t\t// Calculate final metrics\n\t\tperfMetrics.endTime = performance.now();\n\t\tperfMetrics.totalTime = perfMetrics.endTime - perfMetrics.startTime;\n\n\t\t// Add iframe metrics\n\t\tperfMetrics.iframeMetrics = {\n\t\t\ttotalIframes: iframeCount,\n\t\t\tmaxDepth: maxIframeDepth,\n\t\t\tmaxIframes: maxIframes\n\t\t};\n\n\t\t// Add popup container metrics\n\t\tperfMetrics.popupMetrics = {\n\t\t\tdetectedPopups: popupContainers.length,\n\t\t\tpopupTypes: popupContainers.map(p => ({\n\t\t\t\ttagName: p.element.tagName,\n\t\t\t\tid: p.element.id,\n\t\t\t\tclassName: (p.element.className || \'\').toString().substring(0, 100),\n\t\t\t\tzIndex: p.zIndex,\n\t\t\t\tbounds: {\n\t\t\t\t\tx: p.rect.left,\n\t\t\t\t\ty: p.rect.top,\n\t\t\t\t\twidth: p.rect.width,\n\t\t\t\t\theight: p.rect.height\n\t\t\t\t}\n\t\t\t}))\n\t\t};\n\n\t\t// Update interactive count to reflect filtered elements\n\t\tperfMetrics.nodeMetrics.filteredInteractiveNodes = filteredInteractive.length;\n\n\t\tif (debugMode) {\n\t\t\tconsole.log(\'[Browser-Use DOM] Extraction complete:\', {\n\t\t\t\ttotalNodes: perfMetrics.nodeMetrics.totalNodes,\n\t\t\t\tprocessedNodes: perfMetrics.nodeMetrics.processedNodes,\n\t\t\t\tinteractiveNodes: perfMetrics.nodeMetrics.interactiveNodes,\n\t\t\t\tfilteredInteractiveNodes: filteredInteractive.length,\n\t\t\t\tvisibleNodes: perfMetrics.nodeMetrics.visibleNodes,\n\t\t\t\ttotalIframes: iframeCount,\n\t\t\t\tdetectedPopups: popupContainers.length,\n\t\t\t\ttotalTimeMs: perfMetrics.totalTime.toFixed(2)\n\t\t\t});\n\t\t}\n\n\t\t// Build compact nodeMap if compactMode is enabled\n\t\tlet finalNodeMap = nodeMap;\n\t\tif (compactMode) {\n\t\t\tconst essentialNodeIds = new Set();\n\n\t\t\t// Add root node\n\t\t\tessentialNodeIds.add(rootId);\n\n\t\t\t// Add all interactive elements and their ancestors\n\t\t\tfor (const item of filteredInteractive) {\n\t\t\t\tlet currentId = item.nodeId;\n\t\t\t\twhile (currentId != null) {\n\t\t\t\t\tessentialNodeIds.add(currentId);\n\t\t\t\t\tcurrentId = nodeParentMap[currentId];\n\t\t\t\t}\n\t\t\t}\n\n\t\t\t// Add iframe nodes\n\t\t\tfor (const iframe of iframeNodes) {\n\t\t\t\tessentialNodeIds.add(iframe.nodeId);\n\t\t\t}\n\n\t\t\t// Filter nodeMap to only essential nodes\n\t\t\tfinalNodeMap = {};\n\t\t\tfor (const nodeId of essentialNodeIds) {\n\t\t\t\tif (nodeMap[nodeId]) {\n\t\t\t\t\t// Clone the node and filter children to only include essential ones\n\t\t\t\t\tconst node = { ...nodeMap[nodeId] };\n\t\t\t\t\tif (node.children && node.children.length > 0) {\n\t\t\t\t\t\tnode.children = node.children.filter(childId => essentialNodeIds.has(childId));\n\t\t\t\t\t}\n\t\t\t\t\tfinalNodeMap[nodeId] = node;\n\t\t\t\t}\n\t\t\t}\n\n\t\t\tif (debugMode) {\n\t\t\t\tconsole.log(`[Browser-Use DOM] Compact mode: reduced ${Object.keys(nodeMap).length} nodes to ${Object.keys(finalNodeMap).length} essential nodes`);\n\t\t\t}\n\t\t}\n\n\t\treturn {\n\t\t\tmap: finalNodeMap,\n\t\t\trootId: rootId,\n\t\t\tiframeNodes: iframeNodes,\n\t\t\tpopupContainers: popupContainers.map(p => ({\n\t\t\t\ttagName: p.element.tagName,\n\t\t\t\tid: p.element.id,\n\t\t\t\tclassName: (p.element.className || \'\').toString().substring(0, 100),\n\t\t\t\tzIndex: p.zIndex,\n\t\t\t\tbounds: {\n\t\t\t\t\tx: p.rect.left,\n\t\t\t\t\ty: p.rect.top,\n\t\t\t\t\twidth: p.rect.width,\n\t\t\t\t\theight: p.rect.height\n\t\t\t\t}\n\t\t\t})),\n\t\t\tperfMetrics: perfMetrics,\n\t\t\tcompactMode: compactMode\n\t\t};\n\n\t} catch (error) {\n\t\tconsole.error(\'[Browser-Use DOM] Extraction error:\', error);\n\t\treturn {\n\t\t\tmap: {},\n\t\t\trootId: null,\n\t\t\tiframeNodes: [],\n\t\t\tpopupContainers: [],\n\t\t\tperfMetrics: perfMetrics,\n\t\t\terror: error.message\n\t\t};\n\t}\n})\n'
# END GENERATED DOM TREE JS


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
        raw_js_code = _load_dom_tree_js().strip()
        if raw_js_code.startswith('﻿'):
            raw_js_code = raw_js_code[1:]  # Remove UTF-8 BOM if present
        if raw_js_code.endswith(';'):
            raw_js_code = raw_js_code[:-1]
        # Don't wrap with 'return' here - execute_script handles that
        self.js_code = raw_js_code
        self.logger.debug(f'JavaScript code loaded, length: {len(self.js_code)} chars')

    def _should_use_json_dom_transport(self) -> bool:
        """Use string transport for Appium iOS Safari to avoid XCUITest recursion errors."""
        capabilities = dict(getattr(self.driver, 'capabilities', {}) or {})
        platform_name = str(capabilities.get('platformName') or capabilities.get('platform') or '').lower()
        automation_name = str(
            capabilities.get('appium:automationName') or capabilities.get('automationName') or ''
        ).lower()
        return 'ios' in platform_name or automation_name == 'xcuitest'

    def _minimal_eval_result_payload(self, eval_result: dict | None) -> dict:
        eval_result = eval_result or {}
        return {
            'map': eval_result.get('map', {}),
            'rootId': eval_result.get('rootId'),
        }

    def _execute_dom_extraction_script(self, args: dict) -> dict:
        """Execute DOM extraction JS with an Appium-safe fallback transport."""
        object_script = f'return ({self.js_code})(arguments[0])'
        json_script = f"""
            const __browserUseDomResult = ({self.js_code})(arguments[0]) || {{}};
            return JSON.stringify({{
                map: __browserUseDomResult.map || {{}},
                rootId: __browserUseDomResult.rootId ?? null
            }});
        """

        if self._should_use_json_dom_transport():
            serialized_result = self.driver.execute_script(json_script, args)
            return self._minimal_eval_result_payload(json.loads(serialized_result or '{}'))

        try:
            eval_result: dict = self.driver.execute_script(object_script, args)
        except Exception as js_error:
            if 'Recursive object cannot be transferred' not in str(js_error):
                raise

            self.logger.warning(
                'DOM extraction returned a non-transferable object; retrying via JSON string transport'
            )
            serialized_result = self.driver.execute_script(json_script, args)
            return self._minimal_eval_result_payload(json.loads(serialized_result or '{}'))

        return self._minimal_eval_result_payload(eval_result)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        pass

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
                eval_result = self._execute_dom_extraction_script(args)
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
            self.logger.debug('==================== SELECTOR MAP COMPARISON ====================')
            self.logger.debug(f'JS selector_map: {len(js_selector_map)} elements (using this)')
            self.logger.debug(f'Serializer selector_map: {len(serialized_dom_state.selector_map)} elements (ignoring)')
            
            if len(js_selector_map) != len(serialized_dom_state.selector_map):
                self.logger.debug(f'⚠️  Serializer tried to add {len(serialized_dom_state.selector_map) - len(js_selector_map)} elements - using JS map instead')
            
            self.logger.debug('Using JS selector_map elements:')
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

        # Add serializer sub-timings
        for key, value in serializer_timing.items():
            timing_info[f'{key}_ms'] = value * 1000

        timing_info['serialization_total_ms'] = (time.time() - start_serialize) * 1000
        timing_info['get_serialized_dom_tree_total_ms'] = (time.time() - start_total) * 1000

        # Return the serializer's selector_map (not js_selector_map) for consistency
        return serialized_dom_state, enhanced_dom_tree, final_selector_map, timing_info

    async def clear_all_highlights(self) -> None:
        """Clear any legacy page-injected highlight overlays from the current page."""
        await self.clear_highlights()

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
                self.logger.debug('  -> SKIP (no interactive elements in iframe)')
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
                eval_result = self._execute_dom_extraction_script(args)
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
            return main_root, merged_selector_map, iframe_info_map
        
        # Get iframe info using optimized batch collection
        # Identify iframes that are already in the main selector map (have content)
        # If an iframe node has children in the main DOM, it was successfully processed by JS
        populated_iframes = set()
        
        # Check all nodes for iframe/frame related tags that might be parents
        # But specifically, we want to know if specific iframe elements yielded children
        # The JS index.js logic for iframes:
        # if (rect.width > 0 && rect.height > 0) { ... try access contentDocument ... }
        # If accessible, it returns children.
        
        # We can look for iframe elements in the main map
        for node in merged_selector_map.values():
            if node.node_name == 'IFRAME':
                # Check if it has children in the selector map (interactive children)
                # The children_nodes property is the full tree, but selector_map is flattened interactive nodes.
                # However, if it was processed by JS and had accessible content, 
                # the browser-use DOM extraction usually flattens it or keeps structure.
                # In compact mode, we might just get the interactive elements.
                
                # A better way: check if we can access the contentDocument via JS for this iframe.
                # But we want to avoid extra calls.
                
                # Let's rely on the frame path/ID if available, or just check if the iframe 
                # has children in the returned tree.
                if node.children_nodes and len(node.children_nodes) > 0:
                     # It has children, so main JS handled it
                     # We need to match this node to the IframeInfo to exclude it
                     pass

        iframes = await self.iframe_handler.get_all_iframes(
            include_nested=False,  # Skip nested for performance - top-level is usually enough
            max_depth=1,
        )
        
        self.logger.debug(f'Found {len(iframes)} iframes, filtering...')
        
        # smart filtering: visible + reasonable size + NOT ALREADY PROCESSED
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
            
            # CRITICAL DUPLICATION FIX:
            # Check if this iframe was already processed by the main page JS
            # If the main page JS successfully accessed the iframe, it will have extracted its content
            # We can check if the iframe's content is present in the main DOM tree
            
            # Heuristic: If it's same-origin (or effectively same-origin), JS likely handled it.
            # If it's explicitly cross-origin, JS likely blocked it.
            # But "about:blank" is confusing.
            
            # Safest check: Is this iframe "fully populated" in the main DOM?
            # It's hard to map `iframe` object back to `IframeInfo` precisely without robust ID matching.
            # But we can check if `iframe.is_cross_origin` is False.
            # If it is NOT cross-origin, the main index.js script *should* have handled it.
            # So we should SKIP it here to avoid duplication.
            
            # However, sometimes index.js fails on some same-origin frames? 
            # The user's log shows: "Collected 37 top-level iframes... processing 7 of 37"
            # It seems we are aggressively processing iframes that might be same-origin.
            
            # Strategy: Only manually process iframes that are CROSS-ORIGIN.
            # Same-origin iframes are handled by the main page injection.
            if not iframe.is_cross_origin:
                 # Double check: sometimes about:blank iframes (same origin) are not fully traversed 
                 # if they are dynamically loaded?
                 # But generally, if it's same origin, the main JS execution context can see it.
                 self.logger.debug(f'  {display_status} SKIP same-origin (handled by main JS): {iframe.selector}')
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
                    self.logger.debug('  -> No interactive elements found in iframe')
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
