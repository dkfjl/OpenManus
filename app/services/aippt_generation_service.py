from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Dict, List, Optional

import aiohttp

from app.config import config
from app.logger import logger
from app.services.execution_log_service import log_execution_event


def _sanitize_filename(topic: str) -> str:
    """Sanitize topic for filename generation"""
    sanitized = re.sub(r"[^\w\u4e00-\u9fff]+", "_", topic).strip("_") or "presentation"
    return f"{sanitized}.pptx"


def _default_reports_path(topic: str) -> str:
    """Generate default file path for PPTX"""
    return str(Path("reports") / _sanitize_filename(topic))


async def generate_pptx_from_aippt(
    *,
    topic: str,
    outline: List[dict],
    language: Optional[str] = None,
    style: Optional[str] = None,
    model: Optional[str] = None,
    filepath: Optional[str] = None,
) -> dict:
    """
    Generate PPTX file using the AIPPT third-party API.

    Args:
        topic: The main topic for the PPT
        outline: PPT outline in AIPPT JSON format
        language: Output language (zh, en, etc.)
        style: PPT style (通用, 学术风, 职场风, 教育风, 营销风)
        model: AI model to use (e.g., "gemini-3-pro-preview")
        filepath: Optional custom filepath for saving the PPTX

    Returns:
        Dict containing generation result and file path
    """
    language = language or "zh"
    style = style or "通用"
    model = model or "gemini-3-pro-preview"

    # Setup file path
    target_path = filepath or str(_default_reports_path(topic))
    from app.config import config
    base = config.workspace_root
    candidate = Path(target_path)
    if not candidate.is_absolute():
        candidate = base / candidate
    if candidate.suffix.lower() != ".pptx":
        candidate = candidate.with_suffix(".pptx")
    abs_path = str(candidate)

    log_execution_event(
        "aippt_generation",
        "Starting AIPPT PPTX generation",
        {
            "topic": topic[:100],
            "language": language,
            "style": style,
            "model": model,
            "filepath": abs_path,
        },
    )

    try:
        # Get AIPPT API configuration
        aippt_config = config.aippt_config
        base_url = aippt_config.base_url
        api_endpoint = f"{base_url}/tools/aippt"
        timeout = aippt_config.request_timeout

        # Prepare request payload
        outline_json = json.dumps(outline, ensure_ascii=False)
        payload = {
            "content": outline_json,
            "language": language,
            "style": style,
            "model": model,
        }

        # Make HTTP request with SSE processing
        result = await _process_aippt_sse_request(
            api_endpoint=api_endpoint,
            payload=payload,
            output_path=abs_path,
            timeout=timeout,
        )

        log_execution_event(
            "aippt_generation",
            "AIPPT PPTX generation completed",
            {
                "filepath": abs_path,
                "slides_generated": result.get("slides_count", 0),
                "generation_time": result.get("generation_time", 0),
            },
        )

        return {
            "status": "completed",
            "filepath": abs_path,
            "title": topic,
            "slides_count": result.get("slides_count", 0),
            "generation_time": result.get("generation_time", 0),
        }

    except Exception as e:
        log_execution_event(
            "aippt_generation",
            "AIPPT PPTX generation failed",
            {"error": str(e)},
        )
        logger.error(f"Failed to generate PPTX via AIPPT: {e}")

        return {
            "status": "failed",
            "filepath": abs_path,
            "title": topic,
            "error": str(e),
        }


async def _process_aippt_sse_request(
    api_endpoint: str,
    payload: dict,
    output_path: str,
    timeout: int = 300,
) -> dict:
    """
    Process AIPPT SSE request and save generated PPTX.

    Args:
        api_endpoint: Full AIPPT API endpoint URL
        payload: Request payload
        output_path: Path to save the generated PPTX
        timeout: Request timeout in seconds

    Returns:
        Dict with generation statistics
    """
    start_time = asyncio.get_event_loop().time()
    slides_data = []
    slides_count = 0

    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(
                api_endpoint,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=timeout),
                headers={"Content-Type": "application/json"},
            ) as response:

                if response.status != 200:
                    error_text = await response.text()
                    raise aiohttp.ClientResponseError(
                        request_info=response.request_info,
                        history=response.history,
                        status=response.status,
                        message=f"AIPPT API error: {error_text}",
                    )

                # Process SSE stream
                content_type = response.headers.get('content-type', '')
                if 'text/event-stream' not in content_type:
                    # Handle non-SSE response (might be direct JSON)
                    response_data = await response.json()
                    return _handle_non_sse_response(response_data, output_path)

                # Process SSE stream and collect slide data
                async for line in response.content:
                    if line:
                        line_str = line.decode('utf-8').strip()
                        if line_str.startswith('data: '):
                            data_str = line_str[6:]  # Remove 'data: ' prefix
                            if data_str and data_str != '[DONE]':
                                try:
                                    slide_data = json.loads(data_str)
                                    slides_data.append(slide_data)
                                    slides_count += 1
                                    logger.debug(f"Received slide {slides_count}: {slide_data.get('type', 'unknown')}")
                                except json.JSONDecodeError:
                                    logger.warning(f"Failed to parse SSE data: {data_str}")

        except asyncio.TimeoutError:
            raise TimeoutError(f"AIPPT API request timed out after {timeout} seconds")
        except aiohttp.ClientError as e:
            raise Exception(f"AIPPT API request failed: {str(e)}")

    generation_time = asyncio.get_event_loop().time() - start_time

    # Convert collected slide data to PPTX using our new service
    if slides_data:
        try:
            from app.services.aippt_to_pptx_service import \
                convert_aippt_slides_to_pptx

            logger.info(f"Converting {len(slides_data)} slides to PPTX using local service")
            conversion_result = convert_aippt_slides_to_pptx(slides_data, output_path)

            if conversion_result["status"] == "success":
                return {
                    "slides_count": conversion_result["slides_processed"],
                    "generation_time": generation_time,
                    "file_size": conversion_result["file_size"],
                }
            else:
                raise Exception(f"PPTX conversion failed: {conversion_result.get('error', 'Unknown error')}")

        except Exception as e:
            logger.error(f"Failed to convert slides to PPTX: {e}")
            raise Exception(f"Local PPTX generation failed: {str(e)}")
    else:
        raise Exception("No slide data received from AIPPT API")


def _handle_non_sse_response(response_data: dict, output_path: str) -> dict:
    """
    Handle non-SSE response from AIPPT API.

    Args:
        response_data: JSON response from API
        output_path: Path where PPTX should be saved

    Returns:
        Dict with generation statistics
    """
    # This function needs to be implemented based on actual API response format
    # The API might return:
    # 1. A file download URL
    # 2. Base64 encoded PPTX data
    # 3. Direct binary data
    # 4. Just status information

    if "file_url" in response_data:
        # Handle file download URL
        # This would require an additional request to download the file
        logger.info(f"File URL provided: {response_data['file_url']}")
        # TODO: Implement file download logic
        return {"slides_count": response_data.get("slides_count", 0)}

    elif "file_data" in response_data:
        # Handle base64 encoded file data
        import base64
        try:
            file_data = base64.b64decode(response_data["file_data"])
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, 'wb') as f:
                f.write(file_data)
            return {"slides_count": response_data.get("slides_count", 0)}
        except Exception as e:
            raise Exception(f"Failed to save base64 file data: {str(e)}")

    elif "slides" in response_data:
        # Handle slides data (generate PPTX locally using our service)
        slides_data = response_data["slides"]
        logger.info(f"Received {len(slides_data)} slides data, converting to PPTX locally")

        try:
            from app.services.aippt_to_pptx_service import \
                convert_aippt_slides_to_pptx

            conversion_result = convert_aippt_slides_to_pptx(slides_data, output_path)

            if conversion_result["status"] == "success":
                return {
                    "slides_count": conversion_result["slides_processed"],
                    "file_size": conversion_result["file_size"]
                }
            else:
                raise Exception(f"PPTX conversion failed: {conversion_result.get('error', 'Unknown error')}")

        except Exception as e:
            logger.error(f"Failed to convert slides to PPTX: {e}")
            raise Exception(f"Local PPTX generation failed: {str(e)}")

    else:
        # Just status information
        return {"slides_count": response_data.get("slides_count", 0)}


class AIPPTConfig:
    """AIPPT API configuration"""

    def __init__(
        self,
        base_url: str = "http://192.168.1.119:3001",
        request_timeout: int = 300,
    ):
        self.base_url = base_url.rstrip('/')
        self.request_timeout = request_timeout
