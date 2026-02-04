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
	function isElementVisible(element) {
		if (!element || !element.getBoundingClientRect) return false;

		const style = window.getComputedStyle(element);
		if (style.display === 'none' ||
			style.visibility === 'hidden' ||
			style.visibility === 'collapse' ||
			style.opacity === '0') {
			return false;
		}

		const rect = element.getBoundingClientRect();
		if (rect.width === 0 && rect.height === 0) {
			return false;
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
	function isInViewport(element, expansion = 0) {
		if (!element || !element.getBoundingClientRect) return false;

		const rect = element.getBoundingClientRect();
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
	function isElementInteractive(element) {
		if (!element || element.nodeType !== Node.ELEMENT_NODE) return false;

		// Check if element matches interactive selectors
		for (const selector of INTERACTIVE_SELECTORS) {
			try {
				if (element.matches(selector)) {
					// Filter out empty anchor tags
					if (element.tagName === 'A') {
						const text = (element.textContent || '').trim();
						const ariaLabel = element.getAttribute('aria-label')?.trim();
						const title = element.getAttribute('title')?.trim();
						const hasImage = element.querySelector('img, svg, [role="img"]');
						if (!text && !ariaLabel && !title && !hasImage) {
							return false;  // Skip empty anchors
						}
					}
					return true;
				}
			} catch (e) {
				// Invalid selector, skip
			}
		}

		// Check for click event listeners (heuristic)
		const tagName = element.tagName.toUpperCase();
		if (tagName === 'DIV' || tagName === 'SPAN') {
			const style = window.getComputedStyle(element);
			if (style.cursor === 'pointer') return true;
		}

		return false;
	}

	/**
	 * Check if element is the topmost element at its position - enhanced version
	 * that handles z-index, CSS positioning, and complex overlap scenarios
	 */
	function isTopElement(element) {
		if (!element || !element.getBoundingClientRect) return false;

		const rect = element.getBoundingClientRect();

		// Skip if element has zero dimensions
		if (rect.width === 0 || rect.height === 0) return false;

		const centerX = rect.left + rect.width / 2;
		const centerY = rect.top + rect.height / 2;

		// Check if center point is within viewport
		if (centerX < 0 || centerY < 0 ||
			centerX > window.innerWidth || centerY > window.innerHeight) {
			return false;
		}

		try {
			const topElement = document.elementFromPoint(centerX, centerY);
			if (topElement === element) return true;
			if (element.contains(topElement)) return true;

			// Additional check: element might still be visible under a positioned sibling
			// Check for overlapping elements with higher stacking priority
			return !hasOverlappingHigherElement(element, rect);
		} catch (e) {
			return false;
		}
	}

	/**
	 * Check if there's any overlapping element that should be on top
	 * based on z-index stacking context and positioning
	 */
	function hasOverlappingHigherElement(element, elementRect) {
		const elementStyle = window.getComputedStyle(element);
		const elementZIndex = getZIndex(elementStyle);
		const elementPosition = elementStyle.position;
		const elementOpacity = parseFloat(elementStyle.opacity) || 1;

		// Get parent stacking context
		const parentStackingContext = getStackingContext(element);
		const parentZIndex = parentStackingContext ? getZIndex(window.getComputedStyle(parentStackingContext)) : 'auto';

		// Check siblings and cousins for overlapping elements with higher z-index
		let current = element;
		while (current && current !== document.body) {
			const siblings = getVisibleSiblings(current);
			for (const sibling of siblings) {
				if (sibling === element) continue;

				const siblingStyle = window.getComputedStyle(sibling);
				const siblingZIndex = getZIndex(siblingStyle);
				const siblingPosition = siblingStyle.position;
				const siblingOpacity = parseFloat(siblingStyle.opacity) || 1;

				// Skip invisible siblings
				if (siblingOpacity < 0.1) continue;
				if (siblingStyle.display === 'none') continue;
				if (siblingStyle.visibility === 'hidden') continue;

				// Check visual overlap
				const siblingRect = sibling.getBoundingClientRect();
				if (!rectsOverlap(elementRect, siblingRect)) continue;

				// Compare stacking priority:
				// 1. Elements with explicit z-index > auto
				// 2. Positioned elements (absolute/fixed) > non-positioned
				// 3. Higher z-index value wins
				const elementPriority = getStackingPriority(elementZIndex, elementPosition, parentZIndex);
				const siblingPriority = getStackingPriority(siblingZIndex, siblingPosition, parentZIndex);

				if (siblingPriority > elementPriority) {
					return true;
				}
			}
			current = current.parentElement;
		}

		return false;
	}

	/**
	 * Parse z-index to numeric value for comparison
	 */
	function getZIndex(style) {
		const zIndex = style.zIndex;
		if (zIndex === 'auto') return -Infinity;
		const parsed = parseInt(zIndex, 10);
		return isNaN(parsed) ? -Infinity : parsed;
	}

	/**
	 * Calculate stacking priority for comparison
	 * Returns a tuple [base, zIndex, isPositioned] for lexicographic comparison
	 */
	function getStackingPriority(elementZIndex, elementPosition, parentZIndex) {
		const isPositioned = elementPosition === 'absolute' || elementPosition === 'fixed' ||
			elementPosition === 'relative' || elementPosition === 'sticky';
		const hasExplicitZIndex = elementZIndex > -Infinity;

		// Base priority: positioned elements have higher base priority
		// Within same base, compare z-index values
		// If z-index is 'auto' or negative, use parent context
		const effectiveZIndex = hasExplicitZIndex ? elementZIndex : (parentZIndex > -Infinity ? parentZIndex : 0);

		return [isPositioned ? 1 : 0, effectiveZIndex, isPositioned ? 1 : 0];
	}

	/**
	 * Get visible siblings of an element (considering parent context)
	 */
	function getVisibleSiblings(element) {
		if (!element.parentElement) return [];

		const siblings = [];
		const parent = element.parentElement;

		// Get parent's children
		for (const child of parent.children) {
			if (child === element) continue;

			const style = window.getComputedStyle(child);
			if (style.display === 'none') continue;
			if (parseFloat(style.opacity) < 0.1) continue;

			siblings.push(child);
		}

		// Also check parent's cousins (siblings of parent) for fixed/absolute positioned elements
		if (parent.parentElement && parent.parentElement !== document.body) {
			for (const uncle of parent.parentElement.children) {
				if (uncle === parent) continue;
				if (uncle.tagName === 'SCRIPT' || uncle.tagName === 'STYLE') continue;

				const uncleStyle = window.getComputedStyle(uncle);
				const unclePosition = uncleStyle.position;
				const uncleOpacity = parseFloat(uncleStyle.opacity) || 1;

				// Only consider positioned siblings
				if (unclePosition === 'fixed' || unclePosition === 'absolute') {
					if (uncleOpacity >= 0.1 && uncleStyle.display !== 'none') {
						// Add children of positioned uncle that might overlap
						for (const cousin of uncle.children) {
							const cousinStyle = window.getComputedStyle(cousin);
							const cousinOpacity = parseFloat(cousinStyle.opacity) || 1;
							if (cousinOpacity >= 0.1 && cousinStyle.display !== 'none') {
								siblings.push(cousin);
							}
						}
					}
				}
			}
		}

		return siblings;
	}

	/**
	 * Find the nearest ancestor that creates a stacking context
	 */
	function getStackingContext(element) {
		let current = element.parentElement;
		while (current && current !== document.documentElement) {
			const style = window.getComputedStyle(current);
			const zIndex = style.zIndex;
			const position = style.position;
			const opacity = parseFloat(style.opacity) || 1;

			// Elements that create stacking contexts
			if (opacity < 1) return current;
			if (zIndex !== 'auto') return current;
			if (position === 'fixed') return current;
			if (position === 'absolute' && zIndex !== 'auto') return current;
			if (style.transform !== 'none' && style.transform !== 'matrix(1, 0, 0, 1, 0, 0)') return current;
			if (style.filter !== 'none') return current;
			if (style.perspective !== 'none') return current;
			if (style.clipPath !== 'none') return current;

			current = current.parentElement;
		}
		return null;
	}

	/**
	 * Check if two rectangles overlap (with small tolerance for rounding)
	 */
	function rectsOverlap(rect1, rect2) {
		const tolerance = 1;
		return !(rect1.right + tolerance < rect2.left ||
			rect2.right + tolerance < rect1.left ||
			rect1.bottom + tolerance < rect2.top ||
			rect2.bottom + tolerance < rect1.top);
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
	 */
	function createHighlight(element, index, isFocused, isTopElement) {
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

		const rect = element.getBoundingClientRect();
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

		const isVisible = isElementVisible(node);
		const inViewport = isInViewport(node, viewportExpansion);
		const isInteractive = isElementInteractive(node);
		const isTop = isTopElement(node);

		if (isVisible) perfMetrics.nodeMetrics.visibleNodes++;

		// Get element bounds
		const rect = node.getBoundingClientRect();
		const viewport = {
			x: rect.left,
			y: rect.top,
			width: rect.width,
			height: rect.height
		};

		// Collect interactive elements for later sorted index assignment
		let currentHighlightIndex = null;
		if (isInteractive && isVisible && (inViewport || viewportExpansion > 0)) {
			perfMetrics.nodeMetrics.interactiveNodes++;
			// Store for later sorting by visual position
			interactiveElements.push({
				nodeId: nodeId,
				element: node,
				rect: rect,
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
			const style = window.getComputedStyle(node);
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

		const nodeData = {
			tagName: node.tagName.toLowerCase(),
			attributes: getElementAttributes(node),
			xpath: getXPath(node),
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
			let sibling = current.previousSibling;

			while (sibling) {
				if (sibling.nodeType === Node.ELEMENT_NODE &&
					sibling.tagName === current.tagName) {
					index++;
				}
				sibling = sibling.previousSibling;
			}

			const tagName = current.tagName.toLowerCase();
			const part = index > 1 ? `${tagName}[${index}]` : tagName;
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

	/**
	 * Process an iframe and its contents recursively
	 */
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

				// Recursively process iframe contents
				const iframeRootId = processNode(iframeDoc.body, iframeNode.nodeId);
				iframeNode.children = [iframeRootId];

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

	/**
	 * Detect and process high-z-index popup/overlay containers
	 * These are often used for modals, login popups, cookie banners, etc.
	 */
	function processPopupContainers() {
		const popupContainers = [];

		// Find all elements with high z-index that might be popups
		const allElements = document.querySelectorAll('*');

		for (const element of allElements) {
			if (SKIP_TAGS.has(element.tagName)) continue;

			const style = window.getComputedStyle(element);
			const zIndex = parseInt(style.zIndex, 10);
			const position = style.position;

			// Look for elements with:
			// 1. High z-index (> 9000, common for overlays)
			// 2. Fixed or absolute positioning
			// 3. Visible and has dimensions
			if (zIndex > 9000 &&
				(position === 'fixed' || position === 'absolute') &&
				style.display !== 'none' &&
				style.visibility !== 'hidden') {

				const rect = element.getBoundingClientRect();
				if (rect.width > 50 && rect.height > 50) {
					// Check if this looks like a popup container
					const classes = element.className || '';
					const id = element.id || '';
					const combined = (classes + ' ' + id).toLowerCase();

					const isLikelyPopup =
						combined.includes('modal') ||
						combined.includes('popup') ||
						combined.includes('dialog') ||
						combined.includes('overlay') ||
						combined.includes('signin') ||
						combined.includes('login') ||
						combined.includes('consent') ||
						combined.includes('cookie') ||
						combined.includes('banner') ||
						element.getAttribute('role') === 'dialog' ||
						element.getAttribute('role') === 'alertdialog' ||
						element.getAttribute('aria-modal') === 'true';

					if (isLikelyPopup) {
						popupContainers.push({
							element: element,
							rect: rect,
							zIndex: zIndex,
							type: 'popup-container'
						});

						if (debugMode) {
							console.log(`[Browser-Use DOM] Detected popup container: ${element.tagName}#${id}.${classes.substring(0, 50)} z-index=${zIndex}`);
						}
					}
				}
			}
		}

		return popupContainers;
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

		// Detect popup containers that might be overlaying page content
		const popupContainers = processPopupContainers();
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
		const filteredInteractive = [];
		const filteredOutParents = [];
		const filteredOutOverlaps = [];

		for (let i = 0; i < interactiveElements.length; i++) {
			const current = interactiveElements[i];
			let shouldFilter = false;
			let filterReason = null;

			for (let j = 0; j < interactiveElements.length; j++) {
				if (i === j) continue;
				const other = interactiveElements[j];

				// Check if this element contains ANY other interactive element
				// (Innermost rule: parents usually filter themselves out if they have interactive children)
				if (current.element.contains(other.element) && current.element !== other.element) {
					// EXCEPTION: If I am a link and the child is NOT a link/button, 
					// I am the primary target, so keep me.
					const currentIsLink = current.element.tagName === 'A';
					const otherIsLink = other.element.tagName === 'A' || other.element.tagName === 'BUTTON' || other.element.getAttribute('role') === 'button';

					if (currentIsLink && !otherIsLink) {
						// Don't filter parent link
						continue;
					}

					shouldFilter = true;
					filterReason = 'contains';
					if (debugMode) {
						filteredOutParents.push({
							parent: current,
							child: other
						});
					}
					break;
				}

				// Check if this element is CONTAINED by another interactive element
				if (other.element.contains(current.element) && other.element !== current.element) {
					// If my parent is a link and I am NOT a link/button, 
					// the link is the primary target, so filter me out.
					const otherIsLink = other.element.tagName === 'A';
					const currentIsLink = current.element.tagName === 'A' || current.element.tagName === 'BUTTON' || current.element.getAttribute('role') === 'button';

					if (otherIsLink && !currentIsLink) {
						shouldFilter = true;
						filterReason = 'contained-by-link';
						break;
					}
				}

				// Check for visual overlap between non-ancestor elements
				// This handles positioned siblings, modals, tooltips, etc.
				if (!shouldFilter) {
					const currentRect = current.rect;
					const otherRect = other.rect;

					// Check bounding box overlap with tolerance
					if (rectsOverlap(currentRect, otherRect)) {
						// Elements overlap visually - keep the one that should be on top
						// Priority: element with smaller area is likely the intended target (button inside container)
						// OR if one is marked as top element, keep that one
						const currentArea = currentRect.width * currentRect.height;
						const otherArea = otherRect.width * otherRect.height;

						// Keep the smaller element (usually the button/link, not the container)
						// UNLESS the current element is specifically marked as top
						if (currentArea > otherArea && !current.isTop) {
							shouldFilter = true;
							filterReason = 'overlap';
							if (debugMode) {
								filteredOutOverlaps.push({
									filtered: current,
									kept: other,
									reason: 'larger element overlapped by smaller'
								});
							}
							break;
						}
					}
				}
			}

			if (!shouldFilter) {
				filteredInteractive.push(current);
			}
		}

		if (debugMode) {
			console.log(`[Browser-Use DOM] ==================== FILTERING RESULTS ====================`);
			console.log(`[Browser-Use DOM] Filtered out ${interactiveElements.length - filteredInteractive.length} parent elements`);
			filteredOutParents.forEach(({ parent, child }) => {
				const pEl = parent.element;
				const cEl = child.element;
				console.log(`[Browser-Use DOM]   ❌ ${pEl.tagName}.${pEl.className || 'no-class'} (contains ${cEl.tagName}.${cEl.className || 'no-class'})`);
			});
			filteredOutOverlaps.forEach(({ filtered, kept, reason }) => {
				const fEl = filtered.element;
				const kEl = kept.element;
				console.log(`[Browser-Use DOM]   ❌ ${fEl.tagName}.${fEl.className || 'no-class'} (overlap: ${reason}, kept ${kEl.tagName})`);
			});
			console.log(`[Browser-Use DOM] Kept ${filteredInteractive.length} innermost elements:`);
			filteredInteractive.forEach((item, idx) => {
				const el = item.element;
				const rect = item.rect;
				const text = el.textContent?.trim().substring(0, 30) || '';
				console.log(`[Browser-Use DOM]   ✓ ${idx}: ${el.tagName}.${el.className || 'no-class'} "${text}" pos=(${Math.round(rect.left)},${Math.round(rect.top)})`);
			});
		}

		if (debugMode) {
			console.log(`[Browser-Use DOM] ==================== FILTERING RESULTS ====================`);
			console.log(`[Browser-Use DOM] Filtered out ${interactiveElements.length - filteredInteractive.length} parent elements`);
			filteredOutParents.forEach(({ parent, child }) => {
				const pEl = parent.element;
				const cEl = child.element;
				console.log(`[Browser-Use DOM]   ❌ ${pEl.tagName}.${pEl.className || 'no-class'} (contains ${cEl.tagName}.${cEl.className || 'no-class'})`);
			});
			console.log(`[Browser-Use DOM] Kept ${filteredInteractive.length} innermost elements:`);
			filteredInteractive.forEach((item, idx) => {
				const el = item.element;
				const rect = item.rect;
				const text = el.textContent?.trim().substring(0, 30) || '';
				console.log(`[Browser-Use DOM]   ✓ ${idx}: ${el.tagName}.${el.className || 'no-class'} "${text}" pos=(${Math.round(rect.left)},${Math.round(rect.top)})`);
			});
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
					createHighlight(item.element, index, isFocused, item.isTop);
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
