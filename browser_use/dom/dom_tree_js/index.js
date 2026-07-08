/**
 * DOM Tree Extraction Script for Browser-Use
 * 
 * This script is injected into pages via Playwright's page.evaluate() to extract
 * DOM elements and their properties for Firefox and WebKit (Safari) browsers.
 * 
 * For Chromium browsers, the CDP-based approach in service.py is used instead.
 * 
 * @param {Object} args - Configuration arguments
 * @param {boolean} args.doHighlightElements - Whether to add visual highlights
 * @param {number} args.focusHighlightIndex - Element index to focus (-1 for none)
 * @param {number} args.viewportExpansion - Pixels to expand viewport detection
 * @param {boolean} args.debugMode - Enable debug logging
 * @returns {Object} - DOM tree data with map, rootId, and perfMetrics
 */
(function (args) {
	'use strict';

	const {
		doHighlightElements = true,
		focusHighlightIndex = -1,
		viewportExpansion = 0,
		debugMode = false,
		maxIframeDepth = 5,
		maxIframes = 100,
		includeCrossOriginIframes = true,
		compactMode = false  // When true, only return interactive nodes + ancestors
	} = args || {};

	// Track parent relationships for compact mode
	const nodeParentMap = {};  // nodeId -> parentId

	// Performance tracking
	const perfMetrics = {
		startTime: performance.now(),
		nodeMetrics: {
			totalNodes: 0,
			processedNodes: 0,
			interactiveNodes: 0,
			visibleNodes: 0,
			filteredEmptyInteractive: 0
		}
	};

	// Node map to store extracted data
	const nodeMap = {};
	let nodeIdCounter = 1;
	let highlightIndex = 0;

	// Highlight container for visual elements
	let highlightContainer = null;

	// Track interactive elements for sorted index assignment
	const interactiveElements = [];

	// Iframe tracking
	let iframeCount = 0;
	const iframeNodes = [];

	// Popup/overlay containers collected during the main walk (was a separate
	// full-document querySelectorAll scan).
	const popupContainers = [];

	function maybeCollectPopup(element, style, rect) {
		// Top document only: the old processPopupContainers scanned just the top
		// document.querySelectorAll('*'). The main walk recurses into same-origin
		// iframe bodies, so without this guard we would newly report iframe-internal
		// popups and change the frozen popupContainers output.
		if (element.ownerDocument !== document) return;
		const zIndex = parseInt(style.zIndex, 10);
		if (!(zIndex > 9000)) return;
		const position = style.position;
		if (position !== 'fixed' && position !== 'absolute') return;
		if (style.display === 'none' || style.visibility === 'hidden') return;
		if (rect.width <= 50 || rect.height <= 50) return;

		const classes = (element.className || '').toString();
		const id = element.id || '';
		const combined = (classes + ' ' + id).toLowerCase();
		const role = element.getAttribute('role');
		const isLikelyPopup =
			combined.includes('modal') || combined.includes('popup') ||
			combined.includes('dialog') || combined.includes('overlay') ||
			combined.includes('signin') || combined.includes('login') ||
			combined.includes('consent') || combined.includes('cookie') ||
			combined.includes('banner') ||
			role === 'dialog' || role === 'alertdialog' ||
			element.getAttribute('aria-modal') === 'true';

		if (isLikelyPopup) {
			popupContainers.push({ element, rect, zIndex, type: 'popup-container' });
			if (debugMode) {
				console.log(`[Browser-Use DOM] Detected popup container: ${element.tagName}#${id} z-index=${zIndex}`);
			}
		}
	}

	// Iframe coordinate offset tracking
	// When processing elements inside same-origin iframes, getBoundingClientRect()
	// returns coordinates relative to the iframe viewport, not the main document.
	// These offsets accumulate the iframe position to convert to main document coordinates.
	let iframeOffsetX = 0;
	let iframeOffsetY = 0;

	// Interactive element selectors
	const INTERACTIVE_SELECTORS = [
		'a[href]',
		'a[role]',  // Links with roles even without href
		'button',
		'input',
		'select',
		'textarea',
		'[role="button"]',
		'[role="link"]',
		'[role="checkbox"]',
		'[role="radio"]',
		'[role="tab"]',
		'[role="menuitem"]',
		'[role="option"]',
		'[role="switch"]',
		'[role="slider"]',
		'[role="spinbutton"]',
		'[role="combobox"]',
		'[role="listbox"]',
		'[role="searchbox"]',
		'[role="textbox"]',
		'[role="dialog"]',
		'[role="alertdialog"]',
		'[tabindex]',
		'[onclick]',
		'[contenteditable="true"]',
		'summary',
		'details',
		'label[for]',
		'[draggable="true"]',
		// Additional patterns for styled buttons/links
		'[data-testid*="button"]',
		'[data-testid*="btn"]',
		'[class*="button"]',
		'[class*="btn"]',
		// Generic popup/modal selectors
		'[class*="popup"]',
		'[class*="modal"]',
		'[class*="dialog"]',
		'[class*="overlay"]',
		'[aria-modal="true"]',
	];

	// Precompute one combined selector so isElementInteractive does a single
	// matches() call instead of ~30. Drop any token a given engine rejects
	// (validated once here, not per node).
	const COMBINED_INTERACTIVE_SELECTOR = (function () {
		const valid = [];
		const probe = document.createElement('div');
		for (const sel of INTERACTIVE_SELECTORS) {
			try {
				probe.matches(sel);
				valid.push(sel);
			} catch (e) {
				// Unsupported selector token on this engine — skip it.
			}
		}
		return valid.join(',');
	})();

	// Elements to skip completely
	const SKIP_TAGS = new Set([
		'SCRIPT', 'STYLE', 'NOSCRIPT', 'META', 'LINK', 'HEAD', 'BR', 'HR'
	]);

	// Inline elements that shouldn't break text flow
	const INLINE_TAGS = new Set([
		'A', 'ABBR', 'ACRONYM', 'B', 'BDO', 'BIG', 'BR', 'BUTTON', 'CITE', 'CODE',
		'DFN', 'EM', 'I', 'IMG', 'INPUT', 'KBD', 'LABEL', 'MAP', 'OBJECT', 'Q',
		'SAMP', 'SCRIPT', 'SELECT', 'SMALL', 'SPAN', 'STRONG', 'SUB', 'SUP',
		'TEXTAREA', 'TIME', 'TT', 'VAR'
	]);

	/**
	 * Check if an element is visible in the viewport
	 * Enhanced to detect elements hidden via offsetParent, pointer-events, and visibility:collapse
	 */
	function isElementVisible(element, style, rect) {
		if (!element || !element.getBoundingClientRect) return false;

		// Use modern checkVisibility API if available (checks ancestors too)
		if (typeof element.checkVisibility === 'function') {
			if (!element.checkVisibility({ opacityProperty: true, visibilityProperty: true })) {
				return false;
			}
		}

		style = style || window.getComputedStyle(element);
		if (style.display === 'none' ||
			style.visibility === 'hidden' ||
			style.visibility === 'collapse' ||
			style.opacity === '0') {
			return false;
		}

		// Fallback for older browsers: check ancestors for opacity 0
		if (typeof element.checkVisibility !== 'function') {
			let curr = element.parentElement;
			while (curr && curr !== document.body) {
				const parentStyle = window.getComputedStyle(curr);
				if (parentStyle.opacity === '0' || parentStyle.display === 'none' || parentStyle.visibility === 'hidden') {
					return false;
				}
				curr = curr.parentElement;
			}
		}

		rect = rect || element.getBoundingClientRect();
		if (rect.width === 0 || rect.height === 0) {
			return false;
		}

		// Check if the center point is clipped by an overflow: hidden/scroll/auto ancestor
		const centerX = rect.left + rect.width / 2;
		const centerY = rect.top + rect.height / 2;
		let clipCurr = element.parentElement;
		while (clipCurr && clipCurr !== document.body && clipCurr !== document.documentElement) {
			const clipStyle = window.getComputedStyle(clipCurr);
			if (clipStyle.display === 'contents') {
				clipCurr = clipCurr.parentElement;
				continue;
			}
			if (clipStyle.overflow !== 'visible' || clipStyle.overflowX !== 'visible' || clipStyle.overflowY !== 'visible') {
				const parentRect = clipCurr.getBoundingClientRect();
				if (centerX < parentRect.left || centerX > parentRect.right ||
					centerY < parentRect.top || centerY > parentRect.bottom) {
					return false;
				}
			}
			clipCurr = clipCurr.parentElement;
		}

		// Check offsetParent - if null, element is not in layout
		// Exception: body, html, and fixed/sticky positioned elements can have null offsetParent
		if (element.offsetParent === null &&
			element !== document.body &&
			element !== document.documentElement) {
			const position = style.position;
			if (position !== 'fixed' && position !== 'sticky') {
				return false;
			}
		}

		// Check pointer-events - elements with pointer-events:none are not truly interactive
		if (style.pointerEvents === 'none') {
			return false;
		}

		return true;
	}

	/**
	 * Check if an element is in the viewport (with expansion)
	 */
	function isInViewport(element, expansion = 0, rect) {
		if (!element || !element.getBoundingClientRect) return false;
		rect = rect || element.getBoundingClientRect();
		const viewportHeight = window.innerHeight || document.documentElement.clientHeight;
		const viewportWidth = window.innerWidth || document.documentElement.clientWidth;
		return (
			rect.bottom >= -expansion &&
			rect.top <= viewportHeight + expansion &&
			rect.right >= -expansion &&
			rect.left <= viewportWidth + expansion
		);
	}

	/**
	 * Check if an element is interactive
	 */
	function isElementInteractive(element, style) {
		if (!element || element.nodeType !== Node.ELEMENT_NODE) return false;

		let matchesInteractive = false;
		try {
			matchesInteractive = COMBINED_INTERACTIVE_SELECTOR && element.matches(COMBINED_INTERACTIVE_SELECTOR);
		} catch (e) {
			matchesInteractive = false;
		}

		if (matchesInteractive) {
			if (element.tagName === 'A') {
				const text = (element.textContent || '').trim();
				const ariaLabel = element.getAttribute('aria-label')?.trim();
				const title = element.getAttribute('title')?.trim();
				const hasImage = element.querySelector('img, svg, [role="img"]');
				if (!text && !ariaLabel && !title && !hasImage) {
					return false;
				}
			}
			return true;
		}

		const tagName = element.tagName.toUpperCase();
		if (tagName === 'DIV' || tagName === 'SPAN') {
			style = style || window.getComputedStyle(element);
			if (style.cursor === 'pointer') return true;
		}
		return false;
	}

	/**
	 * Check if element is the topmost element at its position - enhanced version
	 * that handles z-index, CSS positioning, and complex overlap scenarios
	 */
	/**
	 * Is this element the one the browser would hit at its center point?
	 * Uses the real paint stack instead of hand-rolled z-index math. Hit-tests
	 * against the element's OWN document (element.ownerDocument): inside a
	 * same-origin iframe, getBoundingClientRect() is relative to the iframe's
	 * own viewport, so we must query that document, not the top one. Elements
	 * whose center is outside their document's viewport cannot be hit-tested and
	 * are treated as top (still indexed when viewportExpansion > 0).
	 */
	function isTopElement(element, rect) {
		if (!element || !element.getBoundingClientRect) return false;
		rect = rect || element.getBoundingClientRect();
		if (rect.width === 0 || rect.height === 0) return false;

		const doc = element.ownerDocument || document;
		const view = doc.defaultView || window;
		const centerX = rect.left + rect.width / 2;
		const centerY = rect.top + rect.height / 2;

		if (centerX < 0 || centerY < 0 ||
			centerX > view.innerWidth || centerY > view.innerHeight) {
			return true;  // outside this document's viewport: cannot hit-test
		}

		try {
			const stack = doc.elementsFromPoint(centerX, centerY);
			let top = null;
			for (const el of stack) {
				if (el.id === 'browser-use-highlight-container') continue;
				if (el.classList && el.classList.contains('browser-use-highlight')) continue;
				top = el;
				break;
			}
			if (!top) return false;
			if (top === element) return true;
			if (element.contains(top)) return true;   // hit a descendant
			if (top.contains(element)) return true;    // pointer-events wrapper on top
			return false;
		} catch (e) {
			return false;
		}
	}

	/**
	 * Get element attributes as a clean object
	 */
	function getElementAttributes(element) {
		const attrs = {};
		if (!element.attributes) return attrs;

		for (const attr of element.attributes) {
			// Skip internal/noisy attributes
			if (attr.name.startsWith('data-reactid') ||
				attr.name.startsWith('data-reactroot') ||
				attr.name.startsWith('ng-') ||
				attr.name === 'style') {
				continue;
			}
			attrs[attr.name] = attr.value;
		}

		return attrs;
	}

	/**
	 * Get text content for a node
	 */
	function getNodeText(node) {
		if (node.nodeType === Node.TEXT_NODE) {
			return node.textContent.trim();
		}
		if (node.nodeType === Node.ELEMENT_NODE) {
			// For input elements, get value
			if (node.tagName === 'INPUT' || node.tagName === 'TEXTAREA') {
				return node.value || node.placeholder || '';
			}
			// For select elements, get selected option text
			if (node.tagName === 'SELECT' && node.selectedOptions && node.selectedOptions.length > 0) {
				return node.selectedOptions[0].textContent.trim();
			}
		}
		return '';
	}

	/**
	 * Create highlight overlay for an element
	 * @param {Element} element - The DOM element to highlight
	 * @param {number} index - The highlight index
	 * @param {boolean} isFocused - Whether the element is focused
	 * @param {boolean} isTopElement - Whether the element is topmost
	 * @param {Object} adjustedRect - Pre-adjusted rect with iframe offsets applied
	 */
	function createHighlight(element, index, isFocused, isTopElement, adjustedRect) {
		// Skip creating highlights for hidden elements (covered by other elements)
		if (isTopElement === false) {
			return;
		}

		if (!highlightContainer) {
			highlightContainer = document.createElement('div');
			highlightContainer.id = 'browser-use-highlight-container';
			highlightContainer.style.cssText = `
				position: fixed;
				top: 0;
				left: 0;
				width: 100%;
				height: 100%;
				pointer-events: none;
				z-index: 2147483647;
			`;
			document.body.appendChild(highlightContainer);
		}

		// Use pre-adjusted rect (already has iframe offsets applied)
		const rect = adjustedRect || element.getBoundingClientRect();
		const highlight = document.createElement('div');
		highlight.className = 'browser-use-highlight';
		highlight.setAttribute('data-highlight-index', index);

		const color = isFocused ? 'rgba(255, 127, 39, 0.5)' : 'rgba(255, 127, 39, 0.3)';
		const borderColor = isFocused ? 'rgb(255, 127, 39)' : 'rgba(255, 127, 39, 0.8)';

		highlight.style.cssText = `
			position: fixed;
			left: ${rect.left}px;
			top: ${rect.top}px;
			width: ${rect.width}px;
			height: ${rect.height}px;
			background-color: ${color};
			border: 2px solid ${borderColor};
			box-sizing: border-box;
			pointer-events: none;
		`;

		// Add index label
		const label = document.createElement('span');
		label.style.cssText = `
			position: absolute;
			top: -18px;
			left: 0;
			background-color: rgb(255, 127, 39);
			color: white;
			padding: 2px 6px;
			font-size: 11px;
			font-family: monospace;
			border-radius: 3px;
			white-space: nowrap;
		`;
		label.textContent = String(index);
		highlight.appendChild(label);

		highlightContainer.appendChild(highlight);
	}

	/**
	 * Process a single DOM node
	 */
	function processNode(node, parentId) {
		const nodeId = nodeIdCounter++;
		perfMetrics.nodeMetrics.totalNodes++;

		// Handle text nodes
		if (node.nodeType === Node.TEXT_NODE) {
			let text = node.textContent.trim();
			if (!text) return null;

			// Cap text node content to 100 chars to match CDP behavior
			if (text.length > 100) {
				text = text.substring(0, 100);
			}

			const isVisible = node.parentElement ? isElementVisible(node.parentElement) : false;
			if (isVisible) perfMetrics.nodeMetrics.visibleNodes++;

			nodeMap[nodeId] = {
				type: 'TEXT_NODE',
				text: text,
				isVisible: isVisible,
				children: []
			};
			nodeParentMap[nodeId] = parentId;

			perfMetrics.nodeMetrics.processedNodes++;
			return nodeId;
		}

		// Skip non-element nodes
		if (node.nodeType !== Node.ELEMENT_NODE) {
			return null;
		}

		// Skip certain tags
		if (SKIP_TAGS.has(node.tagName)) {
			return null;
		}

		const style = window.getComputedStyle(node);
		const rect = node.getBoundingClientRect();

		maybeCollectPopup(node, style, rect);

		const isVisible = isElementVisible(node, style, rect);
		const inViewport = isInViewport(node, viewportExpansion, rect);
		const isInteractive = isElementInteractive(node, style);
		const isTop = isTopElement(node, rect);

		if (isVisible) perfMetrics.nodeMetrics.visibleNodes++;

		// Apply iframe offset to convert iframe-relative coords to main document coords
		const viewport = {
			x: rect.left + iframeOffsetX,
			y: rect.top + iframeOffsetY,
			width: rect.width,
			height: rect.height
		};

		// Collect interactive elements for later sorted index assignment
		let currentHighlightIndex = null;

		if (isInteractive && isVisible && (inViewport || viewportExpansion > 0)) {
			perfMetrics.nodeMetrics.interactiveNodes++;
			// Create adjusted rect with iframe offsets for correct sorting and highlighting
			const adjustedRect = {
				left: rect.left + iframeOffsetX,
				top: rect.top + iframeOffsetY,
				right: rect.right + iframeOffsetX,
				bottom: rect.bottom + iframeOffsetY,
				width: rect.width,
				height: rect.height
			};
			// Store for later sorting by visual position
			interactiveElements.push({
				nodeId: nodeId,
				element: node,
				rect: adjustedRect,
				isTop: isTop
			});
			// Assign a temporary placeholder (will be updated after sorting)
			currentHighlightIndex = -1;
		}

		// Process children
		const childIds = [];
		for (const child of node.childNodes) {
			const childId = processNode(child, nodeId);
			if (childId !== null) {
				childIds.push(childId);
			}
		}

		// Get node text (direct text, not from children)
		let directText = '';
		for (const child of node.childNodes) {
			if (child.nodeType === Node.TEXT_NODE) {
				const text = child.textContent.trim();
				if (text) directText += text + ' ';
			}
		}
		directText = directText.trim();

		// Build node data
		// Cap text length to 100 chars to match CDP accessibility tree behavior and reduce token usage
		let nodeText = isInteractive ? (node.innerText || node.textContent || '').trim() : (directText || getNodeText(node));
		if (nodeText && nodeText.length > 100) {
			nodeText = nodeText.substring(0, 100);
		}

		// Check if element is actually scrollable (has overflow content AND CSS allows scrolling)
		let isActuallyScrollable = false;
		const hasOverflowContent = node.scrollHeight > node.clientHeight + 1 || node.scrollWidth > node.clientWidth + 1;
		if (hasOverflowContent) {
			const overflow = style.overflow.toLowerCase();
			const overflowX = style.overflowX.toLowerCase();
			const overflowY = style.overflowY.toLowerCase();
			// Only mark as scrollable if CSS explicitly allows scrolling
			const allowsScroll = ['auto', 'scroll', 'overlay'].some(v =>
				overflow === v || overflowX === v || overflowY === v
			);
			// For body/html, also consider them scrollable if they have overflow content
			const isRootElement = node.tagName.toLowerCase() === 'body' || node.tagName.toLowerCase() === 'html';
			isActuallyScrollable = allowsScroll || isRootElement;
		}

		// Always include xpath for interactive elements (needed for reliable Selenium clicks)
		// In compact mode, only generate xpath for elements that will get a highlightIndex
		// Note: currentHighlightIndex is -1 at this point (temporary placeholder),
		// it gets updated after sorting. Use isInteractive check instead.
		const shouldIncludeXpath = !compactMode || (compactMode && isInteractive && isVisible);

		const nodeData = {
			tagName: node.tagName.toLowerCase(),
			attributes: getElementAttributes(node),
			xpath: shouldIncludeXpath ? getXPath(node) : undefined,
			isVisible: isVisible,
			isInteractive: isInteractive,
			isTopElement: isTop,
			isInViewport: inViewport,
			highlightIndex: currentHighlightIndex,
			shadowRoot: !!node.shadowRoot,
			viewport: viewport,
			children: childIds,
			text: nodeText,
			ariaLabel: node.getAttribute('aria-label'),
			ariaDescription: node.getAttribute('aria-describedby'),
			title: node.getAttribute('title'),
			role: node.getAttribute('role'),
			isScrollable: isActuallyScrollable
		};

		nodeMap[nodeId] = nodeData;
		nodeParentMap[nodeId] = parentId;
		perfMetrics.nodeMetrics.processedNodes++;

		return nodeId;
	}

	/**
	 * Generate XPath for an element
	 */
	function getXPath(element) {
		if (!element) return '';
		if (element.id) return `//*[@id="${element.id}"]`;

		const parts = [];
		let current = element;

		while (current && current.nodeType === Node.ELEMENT_NODE) {
			let index = 1;
			let hasSameTagSiblings = false;
			const tagName = current.tagName.toLowerCase();

			// Count previous siblings of same tag
			let sibling = current.previousSibling;
			while (sibling) {
				if (sibling.nodeType === Node.ELEMENT_NODE && sibling.tagName.toLowerCase() === tagName) {
					index++;
					hasSameTagSiblings = true;
				}
				sibling = sibling.previousSibling;
			}

			// Check if there are next siblings of same tag
			sibling = current.nextSibling;
			while (sibling && !hasSameTagSiblings) {
				if (sibling.nodeType === Node.ELEMENT_NODE && sibling.tagName.toLowerCase() === tagName) {
					hasSameTagSiblings = true;
				}
				sibling = sibling.nextSibling;
			}

			const part = hasSameTagSiblings ? `${tagName}[${index}]` : tagName;
			parts.unshift(part);

			current = current.parentNode;
		}

		return '/' + parts.join('/');
	}

	/**
	 * Process shadow DOM roots
	 */
	function processShadowRoots(element, parentId) {
		if (!element.shadowRoot) return;

		for (const child of element.shadowRoot.childNodes) {
			processNode(child, parentId);
		}
	}


	/**
	 * Create an iframe node for the node map
	 */
	function createIframeNode(iframe, type) {
		const rect = iframe.getBoundingClientRect();
		const nodeId = nodeIdCounter++;

		if (debugMode) {
			console.log(`[Browser-Use DOM] Creating iframe node ${nodeId} (${type}): ${iframe.src.substring(0, 50)}...`);
		}

		const iframeNode = {
			nodeId: nodeId,
			tagName: 'iframe',
			attributes: {
				src: iframe.src.substring(0, 200),  // Truncate long URLs
				'data-iframe-type': type,
				title: iframe.title || '',
				'aria-label': iframe.getAttribute('aria-label') || '',
				name: iframe.name || '',
				id: iframe.id || ''
			},
			isVisible: rect.width > 0 && rect.height > 0,
			isInteractive: true,
			isTopElement: true,
			isInViewport: isInViewport(iframe),
			highlightIndex: -1,
			viewport: {
				x: rect.left + window.scrollX,
				y: rect.top + window.scrollY,
				width: rect.width,
				height: rect.height
			},
			text: '',
			children: [],
			iframeContent: type === 'same-origin' ? 'extractable' : 'cross-origin-blocked',
			iframeDepth: 0
		};

		return iframeNode;
	}

	function processIframe(iframe, parentId, depth) {
		if (iframeCount >= maxIframes) {
			if (debugMode) {
				console.log(`[Browser-Use DOM] Skipping iframe - max iframes (${maxIframes}) reached`);
			}
			return;
		}

		if (depth >= maxIframeDepth) {
			if (debugMode) {
				console.log(`[Browser-Use DOM] Skipping iframe at depth ${depth} - max depth (${maxIframeDepth}) exceeded`);
			}
			return;
		}

		// Skip iframes that are not visible or not the top element from the parent document.
		// This filters out hidden ad iframes, iframes behind overlays, off-screen iframes, etc.
		// without relying on fragile pattern matching.
		if (!isElementVisible(iframe) || !isTopElement(iframe)) {
			if (debugMode) {
				console.log(`[Browser-Use DOM] Skipping non-visible/obstructed iframe: ${iframe.id || iframe.src?.substring(0, 60) || 'unknown'}`);
			}
			return;
		}

		try {
			// Try to access same-origin iframe content
			const iframeDoc = iframe.contentDocument || iframe.contentWindow.document;

			if (iframeDoc && iframeDoc.body) {
				const type = 'same-origin';
				const iframeNode = createIframeNode(iframe, type);
				iframeNode.iframeDepth = depth;
				nodeMap[iframeNode.nodeId] = iframeNode;
				iframeNodes.push(iframeNode);
				iframeCount++;

				// Save current iframe offset and accumulate this iframe's position
				const iframeRect = iframe.getBoundingClientRect();
				const prevOffsetX = iframeOffsetX;
				const prevOffsetY = iframeOffsetY;
				iframeOffsetX += iframeRect.left;
				iframeOffsetY += iframeRect.top;

				// Recursively process iframe contents (coordinates will be adjusted by offsets)
				const iframeRootId = processNode(iframeDoc.body, iframeNode.nodeId);
				iframeNode.children = [iframeRootId];

				// Restore previous iframe offset
				iframeOffsetX = prevOffsetX;
				iframeOffsetY = prevOffsetY;

				perfMetrics.nodeMetrics.filteredEmptyInteractive++;
				if (debugMode) {
					console.log(`[Browser-Use DOM] Processed same-origin iframe at depth ${depth}`);
				}
			}
		} catch (e) {
			// Cross-origin iframe - can't access content
			if (includeCrossOriginIframes) {
				const iframeNode = createIframeNode(iframe, 'cross-origin');
				iframeNode.iframeDepth = depth;
				iframeNode.iframeContent = 'cross-origin-blocked';
				nodeMap[iframeNode.nodeId] = iframeNode;
				iframeNodes.push(iframeNode);
				iframeCount++;

				if (debugMode) {
					console.log(`[Browser-Use DOM] Recorded cross-origin iframe at depth ${depth}: ${iframe.src.substring(0, 50)}...`);
				}
			}
		}
	}

	/**
	 * Find and process all iframes in a document
	 */
	function processAllIframes(rootElement, depth) {
		if (depth >= maxIframeDepth) return;

		const iframes = rootElement.querySelectorAll('iframe');
		for (const iframe of iframes) {
			processIframe(iframe, null, depth);
			// Process nested iframes within this iframe if same-origin
			try {
				const iframeDoc = iframe.contentDocument || iframe.contentWindow.document;
				if (iframeDoc) {
					processAllIframes(iframeDoc.documentElement || iframeDoc.body, depth + 1);
				}
			} catch (e) {
				// Cross-origin - skip nested processing
			}
		}
	}



	// Main execution
	try {
		// Start from document body
		const rootId = processNode(document.body, null);

		// Process all iframes (same-origin and cross-origin)
		if (maxIframes > 0) {
			processAllIframes(document.documentElement, 0);
			if (debugMode) {
				console.log(`[Browser-Use DOM] Processed ${iframeCount} iframes (max depth: ${maxIframeDepth})`);
			}
		}

		if (debugMode && popupContainers.length > 0) {
			console.log(`[Browser-Use DOM] Detected ${popupContainers.length} popup containers`);
		}

		if (debugMode) {
			console.log(`[Browser-Use DOM] ==================== INTERACTIVE ELEMENTS DEBUG ====================`);
			console.log(`[Browser-Use DOM] Total interactive elements found: ${interactiveElements.length}`);
			interactiveElements.forEach((item, idx) => {
				const el = item.element;
				const rect = item.rect;
				const text = el.textContent?.trim().substring(0, 30) || '';
				const classes = el.className || '';
				console.log(`[Browser-Use DOM]   ${idx}: ${el.tagName} class="${classes}" text="${text}" pos=(${Math.round(rect.left)},${Math.round(rect.top)}) size=${Math.round(rect.width)}x${Math.round(rect.height)}`);
			});
		}

		// Aggressively filter out nested/overlapping interactive elements
		// Strategy: For each element, check if it has ANY interactive descendant - if so, skip it
		// This keeps only the innermost interactive elements
		// Enhanced to also filter out visually overlapping elements (not just DOM containment)
		// O(n·depth) dedup. For each interactive element we walk UP to its first
		// interactive ancestor and decide with the existing target/innermost
		// rules. Each nesting level is resolved by its own walk, so no pairwise
		// O(n^2) scan is needed. `drop` collects elements to filter out.
		const interactiveElementSet = new Set(interactiveElements.map(it => it.element));
		const drop = new Set();

		function isTargetEl(el) {
			return el.tagName === 'A' || el.tagName === 'BUTTON' || el.getAttribute('role') === 'button';
		}

		for (const cur of interactiveElements) {
			const curTarget = isTargetEl(cur.element);
			let intermediateButton = false;
			let a = cur.element.parentElement;
			while (a) {
				if (interactiveElementSet.has(a)) {
					const aTarget = isTargetEl(a);
					if (aTarget) {
						if (curTarget) {
							// Outer target contains an inner target -> keep the inner one.
							drop.add(a);
						} else if (!intermediateButton) {
							// Generic descendant of a link/button -> the target is the
							// click point; drop the descendant.
							drop.add(cur.element);
						}
						break;  // first target ancestor decides this element
					} else {
						// Outer parent is NOT a target (e.g. a div/span container) -> drop the parent.
						drop.add(a);
						// Keep walking upward: do NOT break, so we can reach target ancestors further up
					}
				}
				if (a.tagName === 'BUTTON' || a.getAttribute('role') === 'button') {
					intermediateButton = true;
				}
				a = a.parentElement;
			}
		}

		const filteredInteractive = interactiveElements.filter(
			it => it.isTop !== false && !drop.has(it.element)
		);

		if (debugMode) {
			console.log(`[Browser-Use DOM] Kept ${filteredInteractive.length}/${interactiveElements.length} interactive elements`);
		}

		// Sort filtered interactive elements by visual position (top-to-bottom, left-to-right)
		filteredInteractive.sort((a, b) => {
			const rectA = a.rect;
			const rectB = b.rect;

			// Primary sort: top position
			const topDiff = rectA.top - rectB.top;
			if (Math.abs(topDiff) > 5) { // 5px tolerance for "same row"
				return topDiff;
			}

			// Secondary sort: left position (for elements on same row)
			return rectA.left - rectB.left;
		});

		if (debugMode) {
			console.log(`[Browser-Use DOM] Sorted ${filteredInteractive.length} interactive elements by visual position`);
		}

		// Assign highlight indices to filtered interactive elements (stable indices for LLM)
		// Visual highlights will be filtered in createHighlight to only show top elements
		if (debugMode) {
			console.log(`[Browser-Use DOM] About to assign indices to ${filteredInteractive.length} elements`);
		}

		filteredInteractive.forEach((item, index) => {
			const nodeData = nodeMap[item.nodeId];
			if (nodeData) {
				// Update the highlightIndex in the actual nodeMap
				nodeMap[item.nodeId].highlightIndex = index;
				// Store isTopElement for visual filtering
				nodeMap[item.nodeId].isTopElement = item.isTop;

				if (debugMode && index < 15) {
					console.log(`[Browser-Use DOM] Assigned index ${index} to ${nodeData.tagName} nodeId=${item.nodeId}`);
				}

				// Create visual highlight if enabled (only for topmost elements)
				if (doHighlightElements) {
					const isFocused = focusHighlightIndex === index;
					// Pass the pre-adjusted rect (with iframe offsets) for correct positioning
					createHighlight(item.element, index, isFocused, item.isTop, item.rect);
				}
			} else {
				if (debugMode) {
					console.warn(`[Browser-Use DOM] WARNING: nodeId ${item.nodeId} not found in nodeMap!`);
				}
			}
		});

		// Verify the update worked (AFTER the forEach)
		if (debugMode && filteredInteractive.length > 0) {
			const firstInteractive = filteredInteractive[0];
			const verifyNode = nodeMap[firstInteractive.nodeId];
			console.log(`[Browser-Use DOM] ✅ Verification - nodeMap[${firstInteractive.nodeId}].highlightIndex = ${verifyNode ? verifyNode.highlightIndex : 'NOT_FOUND'} (should be 0)`);
		}

		// Calculate final metrics
		perfMetrics.endTime = performance.now();
		perfMetrics.totalTime = perfMetrics.endTime - perfMetrics.startTime;

		// Add iframe metrics
		perfMetrics.iframeMetrics = {
			totalIframes: iframeCount,
			maxDepth: maxIframeDepth,
			maxIframes: maxIframes
		};

		// Add popup container metrics
		perfMetrics.popupMetrics = {
			detectedPopups: popupContainers.length,
			popupTypes: popupContainers.map(p => ({
				tagName: p.element.tagName,
				id: p.element.id,
				className: (p.element.className || '').toString().substring(0, 100),
				zIndex: p.zIndex,
				bounds: {
					x: p.rect.left,
					y: p.rect.top,
					width: p.rect.width,
					height: p.rect.height
				}
			}))
		};

		// Update interactive count to reflect filtered elements
		perfMetrics.nodeMetrics.filteredInteractiveNodes = filteredInteractive.length;

		if (debugMode) {
			console.log('[Browser-Use DOM] Extraction complete:', {
				totalNodes: perfMetrics.nodeMetrics.totalNodes,
				processedNodes: perfMetrics.nodeMetrics.processedNodes,
				interactiveNodes: perfMetrics.nodeMetrics.interactiveNodes,
				filteredInteractiveNodes: filteredInteractive.length,
				visibleNodes: perfMetrics.nodeMetrics.visibleNodes,
				totalIframes: iframeCount,
				detectedPopups: popupContainers.length,
				totalTimeMs: perfMetrics.totalTime.toFixed(2)
			});
		}

		// Build compact nodeMap if compactMode is enabled
		let finalNodeMap = nodeMap;
		if (compactMode) {
			const essentialNodeIds = new Set();

			// Add root node
			essentialNodeIds.add(rootId);

			// Add all interactive elements and their ancestors
			for (const item of filteredInteractive) {
				let currentId = item.nodeId;
				while (currentId != null) {
					essentialNodeIds.add(currentId);
					currentId = nodeParentMap[currentId];
				}
			}

			// Add iframe nodes
			for (const iframe of iframeNodes) {
				essentialNodeIds.add(iframe.nodeId);
			}

			// Filter nodeMap to only essential nodes
			finalNodeMap = {};
			for (const nodeId of essentialNodeIds) {
				if (nodeMap[nodeId]) {
					// Clone the node and filter children to only include essential ones
					const node = { ...nodeMap[nodeId] };
					if (node.children && node.children.length > 0) {
						node.children = node.children.filter(childId => essentialNodeIds.has(childId));
					}
					finalNodeMap[nodeId] = node;
				}
			}

			if (debugMode) {
				console.log(`[Browser-Use DOM] Compact mode: reduced ${Object.keys(nodeMap).length} nodes to ${Object.keys(finalNodeMap).length} essential nodes`);
			}
		}

		return {
			map: finalNodeMap,
			rootId: rootId,
			iframeNodes: iframeNodes,
			popupContainers: popupContainers.map(p => ({
				tagName: p.element.tagName,
				id: p.element.id,
				className: (p.element.className || '').toString().substring(0, 100),
				zIndex: p.zIndex,
				bounds: {
					x: p.rect.left,
					y: p.rect.top,
					width: p.rect.width,
					height: p.rect.height
				}
			})),
			perfMetrics: perfMetrics,
			compactMode: compactMode
		};

	} catch (error) {
		console.error('[Browser-Use DOM] Extraction error:', error);
		return {
			map: {},
			rootId: null,
			iframeNodes: [],
			popupContainers: [],
			perfMetrics: perfMetrics,
			error: error.message
		};
	}
})
