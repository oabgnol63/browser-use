import asyncio
import os
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

async def test():
    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    
    print("Testing system prompt cache creation...")
    system_instruction = "You are a helpful assistant. " * 300  # ~1500 tokens
    try:
        cache = client.caches.create(
            model="gemini-2.5-flash",
            config=types.CreateCachedContentConfig(
                system_instruction=system_instruction,
                ttl="300s"
            )
        )
        print("Success! Cache name:", cache.name)
        
        # Test using it with new content
        print("Calling with cached_content...")
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents="Say 'Ping'.",
            config=types.GenerateContentConfig(
                cached_content=cache.name
            )
        )
        print("Response 1:", response.text)
        print("Usage 1:", response.usage_metadata.cached_content_token_count)
        
        # Test using it with ANOTHER new content
        print("Calling with cached_content again...")
        response2 = client.models.generate_content(
            model="gemini-2.5-flash",
            contents="Say 'Pong'.",
            config=types.GenerateContentConfig(
                cached_content=cache.name
            )
        )
        print("Response 2:", response2.text)
        print("Usage 2:", response2.usage_metadata.cached_content_token_count)
        
    except Exception as e:
        print("Error:", e)

asyncio.run(test())
