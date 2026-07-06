import asyncio
import logging
import re
from typing import AsyncGenerator
from google.adk.models import Gemini
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from security.audit_log import log_event

logger = logging.getLogger("councilai.model")

class RetryingGemini(Gemini):
    """Subclass of ADK's Gemini model wrapper that transparently retries requests
    when hitting 429 RESOURCE_EXHAUSTED rate limits.
    
    It parses the recommended wait time directly from the API error message,
    or falls back to a generous backoff timeline (5s, 15s, 30s, 60s) to clear the RPM quota.
    """
    
    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        max_retries = 5
        fallback_backoff = [5.0, 15.0, 30.0, 45.0, 60.0]
        
        for attempt in range(max_retries + 1):
            try:
                # Call superclass generator to yield responses
                async for response in super().generate_content_async(llm_request, stream):
                    yield response
                return  # Success, exit the generator
            except Exception as e:
                error_str = str(e).lower()
                is_daily_limit = (
                    "daily" in error_str or
                    "per day" in error_str or
                    "day" in error_str or
                    "generate_content_free_tier_requests" in error_str or
                    ("quota" in error_str and "minute" not in error_str)
                )
                
                if is_daily_limit:
                    log_event(
                        event_type="MODEL_ERROR",
                        actor="system",
                        action="quota_exceeded",
                        status="FAILED",
                        details={"model": self.model, "error": str(e)}
                    )
                    raise Exception(
                        f"Gemini API Quota Exceeded. You have hit the daily request limit for your free-tier API key. "
                        f"Please try again tomorrow, or enable 'Dry Run Mode' in the sidebar configuration to run the simulation instantly. "
                        f"(Details: {str(e)})"
                    )
                
                is_retryable = (
                    ("429" in error_str or
                     "503" in error_str or
                     "resource_exhausted" in error_str or
                     "resource exhausted" in error_str or
                     "unavailable" in error_str or
                     "experiencing high demand" in error_str)
                )
                
                if is_retryable and attempt < max_retries:
                    # Try to parse recommended retry delay (e.g. "retry in 34.799s" or similar)
                    wait_time = fallback_backoff[attempt]
                    
                    # Look for retry time in error text
                    match = re.search(r"retry in (\d+\.?\d*)s", error_str)
                    if match:
                        try:
                            wait_time = float(match.group(1)) + 1.0  # Add 1-second safety buffer
                            logger.info(f"Parsed recommended sleep time from Gemini error: {wait_time:.2f}s")
                        except ValueError:
                            pass
                            
                    logger.warning(
                        f"Gemini API Rate Limit (429) hit. Waiting for {wait_time:.2f}s before retrying... "
                        f"(Attempt {attempt + 1}/{max_retries})"
                    )
                    log_event(
                        event_type="MODEL_RETRY",
                        actor="system",
                        action="gemini_429_retry",
                        status="SUCCESS",
                        details={
                            "attempt": attempt + 1,
                            "max_retries": max_retries,
                            "wait_time": wait_time,
                            "model": self.model,
                            "error": str(e)
                        }
                    )
                    await asyncio.sleep(wait_time)
                else:
                    # Log failure and raise the exception up
                    log_event(
                        event_type="MODEL_ERROR",
                        actor="system",
                        action="gemini_call_failed",
                        status="FAILED",
                        details={
                            "model": self.model,
                            "error": str(e),
                            "attempts_made": attempt + 1
                        }
                    )
                    raise Exception(
                        f"Gemini API calls failed after {attempt + 1} retry attempts due to heavy load or rate limits. "
                        f"Please try again in a few minutes. (Details: {str(e)})"
                    )
