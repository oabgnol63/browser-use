import asyncio
import sys
import os

sys.path.insert(0, os.path.abspath("."))

from selenium import webdriver
from browser_use.selenium.dom_service import SeleniumDomService
from browser_use.dom.serializer.serializer import DOMTreeSerializer
from browser_use.selenium.session import SeleniumSession

async def main():
    session = await SeleniumSession.new_local_session(browser='firefox', headless=False)
    
    # Load test HTML
    session.driver.get("https://cnn.com")
    
    await asyncio.sleep(2)
    # Run the equivalent of dom extraction
    dom_state, selector_map = await session.get_dom_state(highlight_elements=True)
    
    with open("test_js_output.txt", "w", encoding="utf-8") as f:
        f.write("SELECTOR MAP:\n")
        f.write(str(selector_map) + "\n\n")
        
        # Traverse actual dom elements
        f.write("DOM ELEMENTS:\n")
        def dump_node(n, depth=0):
            ind = "  " * depth
            text_val = n.node_value or ''
            text_val = text_val.replace('\n', ' ')
            f.write(f'{ind}Type: {n.node_type}, Name: {n.node_name}, visible: {n.is_visible}, snap: {bool(n.snapshot_node)}, text: {text_val}\n')
            for c in n.children_nodes:
                dump_node(c, depth + 1)
                
        # Get python tree
        args = {
            'doHighlightElements': False,
            'focusHighlightIndex': -1,
            'viewportExpansion': 0,
            'debugMode': True,
            'maxIframeDepth': 5,
            'maxIframes': 100,
            'includeCrossOriginIframes': True,
            'compactMode': False,
        }
        eval_result = session.driver.execute_script(
            f'return ({session.dom_service.js_code})(arguments[0])', args
        )
        root_node, selector_map = session.dom_service._construct_dom_tree(eval_result)
        
        f.write("\nChecking TEXT_NODE values in Python tree:\n")
        text_nodes_py = []
        def check_text_nodes(n):
            if n.node_type == 3 or n.node_name == '#text':
                text_nodes_py.append(n)
                if len(text_nodes_py) <= 10:
                    f.write(f"TEXT NODE: {repr(n.node_value)} | is_visible: {n.is_visible} | has_snapshot: {n.snapshot_node is not None}\n")
            for c in n.children_nodes:
                check_text_nodes(c)
                
        check_text_nodes(root_node)
        
        # Test serialization
        from browser_use.dom.views import SerializedDOMState
        from browser_use.dom.serializer.serializer import DOMTreeSerializer
        
        serializer = DOMTreeSerializer(root_node, None)
        serialized_state, _ = serializer.serialize_accessible_elements()
        dom_str = "SERIALIZED STATE OUTPUT" # serialized_state.llm_representation()
        f.write("\nSERIALIZED DOM TREE:\n")
        f.write(dom_str)
        f.write("\nSERIALIZED DOM TREE:\n")
        f.write(dom_str)
        
        text_nodes_py = []
        def find_text_nodes(n):
            if n.node_type == 3 or n.node_name == '#text':
                text_nodes_py.append(n)
            for c in n.children_nodes:
                find_text_nodes(c)
                
        find_text_nodes(root_node)
        
        f.write("\nPYTHON TREE TEXT NODES counts:\n")
        f.write(f"Count: {len(text_nodes_py)}\n")
        for tn in text_nodes_py[:10]:
            f.write(str(tn.node_value) + "\n")
        
    await session.close()

if __name__ == "__main__":
    asyncio.run(main())
