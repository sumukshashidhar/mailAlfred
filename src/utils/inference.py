"""
Handles all model inference.
"""
from openai import AsyncOpenAI, RateLimitError, APIError
import os
import asyncio
from typing import TypeVar
from dotenv import load_dotenv
from pydantic import BaseModel
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

T = TypeVar("T", bound=BaseModel)

load_dotenv(override=True)

class CalendarEvent(BaseModel):
    title: str
    description: str

client = None # to store our OpenAI client later
DEFAULT_MODEL = "gpt-5-mini" # or "gpt-5-nano" if you want something cheaper
DEFAULT_SERVICE_TIER = "flex" # or "priority" if you want something faster
DEFAULT_TIMEOUT = 900 # 15 minutes

def _get_client() -> AsyncOpenAI:
    global client
    if client is None: 
        client = AsyncOpenAI(
            api_key=os.getenv("OPENAI_API_KEY"),
            base_url=os.getenv("OPENAI_BASE_URL"),
            timeout=DEFAULT_TIMEOUT
        )
    return client


@retry(
    retry=retry_if_exception_type((RateLimitError, APIError)),
    wait=wait_exponential(multiplier=1, min=2, max=60),
    stop=stop_after_attempt(5),
    reraise=True,
)
async def do_structured_output_inference(
    user_prompt: str, 
    schema: type[T], 
    system_prompt: str = None, 
    model: str = DEFAULT_MODEL, 
    service_tier: str = DEFAULT_SERVICE_TIER) -> T:
    """
    Performs structured output inference using the OpenAI API.
    
    Includes retry logic with exponential backoff for rate limits and API errors.
    
    Args:
        user_prompt: The user's prompt
        schema: A Pydantic BaseModel class to parse the response into
        system_prompt: Optional system prompt
        model: Model name to use
        service_tier: Service tier ("flex" or "priority")
    
    Returns:
        An instance of the provided schema class with parsed data
    """
    client = _get_client()
    messages = []
    if system_prompt: messages.append({"role" : "system", "content" : system_prompt})
    messages.append({"role" : "user", "content" : user_prompt})
    response = await client.responses.parse(
        model = model, 
        input = messages, 
        text_format = schema,
        service_tier=service_tier
    )
    return response.output_parsed


if __name__ == "__main__":
    response = asyncio.run(do_structured_output_inference("Give me a mock calendar event", CalendarEvent))
    print(response)
    print(type(response))
