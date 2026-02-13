"""
Plasma AI - AI Analysis Module

Uses Google Gemini to analyze tender documents and extract structured data.
"""

import json
import logging
import os
from typing import Any

import google.generativeai as genai

logger = logging.getLogger(__name__)

# Lazy initialization flag
_gemini_configured = False


# Gemini model configuration
MODEL_NAME = "gemini-3-flash-preview"

# Company context builder
def _build_company_context(company_context: dict[str, str] | None = None) -> str:
    """Build company persona section for AI prompts."""
    if not company_context:
        return "You are an Expert Consultant analyzing technical task documents."
    
    name = company_context.get("company_name", "")
    services = company_context.get("core_services", "")
    experience = company_context.get("past_experience", "")
    
    if not name:
        return "You are an Expert Consultant analyzing technical task documents."
    
    parts = [f"You are the Lead Proposal Writer for {name}."]
    if services:
        parts.append(f"Your company specializes in: {services}.")
    if experience:
        parts.append(f"Key qualifications and past experience: {experience}.")
    parts.append("Use this context to write relevant, company-specific analysis.")
    
    return " ".join(parts)


TENDER_ANALYSIS_PROMPT = """{company_persona}
The document may be in Uzbek (Cyrillic or Latin), Russian, or English.

Analyze the following tender technical task text and extract structured information.

IMPORTANT: Return ONLY valid JSON, no markdown, no explanation.

Required JSON structure:
{{
    "summary": "A 2-3 sentence technical summary of what this tender is about",
    "items": [
        {{"name": "Item name", "quantity": 10, "unit": "pcs"}},
        {{"name": "Another item", "quantity": 5, "unit": "sets"}}
    ],
    "delivery_days": 30,
    "required_licenses": ["ISO 9001", "Construction License"],
    "estimated_cost_breakdown": {{
        "materials": 0,
        "labor": 0,
        "other": 0
    }},
    "key_requirements": ["Requirement 1", "Requirement 2"],
    "risks": ["Potential risk 1", "Potential risk 2"]
}}

Rules:
- "items": Extract all products/services/equipment mentioned with quantities. If quantity not specified, estimate or use 1.
- "delivery_days": Look for delivery timeline. Default to 30 if not mentioned.
- "required_licenses": Any certifications, licenses, or qualifications required.
- "estimated_cost_breakdown": Rough breakdown if budget info is available, otherwise use zeros.
- "key_requirements": Technical specifications, standards, conditions that must be met.
- "risks": Potential challenges or risks you identify.

TEXT TO ANALYZE:
---
{text}
---

Return ONLY the JSON object, nothing else."""


def analyze_tender_text(text: str, company_context: dict[str, str] | None = None) -> dict[str, Any]:
    """
    Analyze tender document text using Gemini AI.
    
    Args:
        text: Extracted text from tender document
        
    Returns:
        Structured data dict with summary, items, delivery_days, etc.
    """
    global _gemini_configured
    
    # Lazy initialization - configure Gemini on first call
    if not _gemini_configured:
        # Import settings here to avoid circular imports and ensure .env is loaded
        from app.core.config import settings
        
        api_key = settings.GOOGLE_API_KEY
        if api_key:
            genai.configure(api_key=api_key)
            _gemini_configured = True
            logger.info("Gemini AI configured successfully (lazy init)")
        else:
            logger.error("Cannot analyze: GOOGLE_API_KEY not configured")
            return {
                "error": "AI not configured",
                "summary": "AI analysis unavailable - API key not configured",
                "items": [],
                "delivery_days": 30,
                "required_licenses": [],
            }
    
    if not text or len(text.strip()) < 100:
        logger.warning("Text too short for meaningful analysis")
        return {
            "error": "Text too short",
            "summary": "Document text too short for analysis",
            "items": [],
            "delivery_days": 30,
            "required_licenses": [],
        }
    
    try:
        model = genai.GenerativeModel(
            MODEL_NAME,
            generation_config=genai.types.GenerationConfig(
                response_mime_type="application/json",
            )
        )
        
        # Truncate if extremely long (though Flash handles 1M tokens)
        max_chars = 100_000  # ~25K tokens for faster processing
        if len(text) > max_chars:
            logger.warning(f"Text truncated from {len(text)} to {max_chars} chars")
            text = text[:max_chars]
        
        company_persona = _build_company_context(company_context)
        prompt = TENDER_ANALYSIS_PROMPT.format(text=text, company_persona=company_persona)
        
        logger.info(f"Sending {len(text)} chars to Gemini {MODEL_NAME}")
        response = model.generate_content(prompt)
        
        # Extract JSON from response
        response_text = response.text.strip()
        logger.debug(f"Raw response (first 500): {response_text[:500]}")
        
        # Clean up response (remove markdown code blocks if present)
        if response_text.startswith("```"):
            lines = response_text.split("\n")
            # Remove first and last lines (```json and ```)
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            response_text = "\n".join(lines)
        
        # Try to find JSON object in response
        start_idx = response_text.find("{")
        end_idx = response_text.rfind("}") + 1
        if start_idx >= 0 and end_idx > start_idx:
            response_text = response_text[start_idx:end_idx]
        
        result = json.loads(response_text)
        logger.info(f"AI analysis complete: {len(result.get('items', []))} items extracted")
        
        return result
        
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse AI response as JSON: {e}")
        logger.error(f"Raw response: {response_text[:1000] if 'response_text' in dir() else 'N/A'}")
        return {
            "error": f"JSON parse error: {e}",
            "summary": "AI response could not be parsed - please try again",
            "items": [],
            "delivery_days": 30,
            "required_licenses": [],
        }
        
    except Exception as e:
        logger.error(f"Gemini API error: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return {
            "error": str(e),
            "summary": f"AI analysis failed: {e}",
            "items": [],
            "delivery_days": 30,
            "required_licenses": [],
        }


async def analyze_tender_text_async(text: str, company_context: dict[str, str] | None = None) -> dict[str, Any]:
    """
    Async wrapper for analyze_tender_text.
    
    Uses run_in_executor since google-generativeai is sync.
    """
    import asyncio
    from functools import partial
    
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, partial(analyze_tender_text, text, company_context))


# Prompt for file-based analysis (handles scanned PDFs)
FILE_ANALYSIS_PROMPT = """{company_persona}
You are analyzing a Technical Task document.
This document may be a SCANNED IMAGE or a text-based PDF. Use your vision capabilities to read it.
The document may be in Uzbek (Cyrillic or Latin), Russian, or English.

Analyze the attached document and extract structured information.

IMPORTANT: Return ONLY valid JSON, no markdown, no explanation.

Required JSON structure:
{{
    "summary": "A 2-3 sentence technical summary of what this tender is about",
    "items": [
        {{"name": "Item name", "quantity": 10, "unit": "pcs"}},
        {{"name": "Another item", "quantity": 5, "unit": "sets"}}
    ],
    "delivery_days": 30,
    "required_licenses": ["ISO 9001", "Construction License"],
    "estimated_cost_breakdown": {{
        "materials": 0,
        "labor": 0,
        "other": 0
    }},
    "key_requirements": ["Requirement 1", "Requirement 2"],
    "risks": ["Potential risk 1", "Potential risk 2"]
}}

Rules:
- "items": Extract all products/services/equipment mentioned with quantities. If quantity not specified, estimate or use 1.
- "delivery_days": Look for delivery timeline. Default to 30 if not mentioned.
- "required_licenses": Any certifications, licenses, or qualifications required.
- "estimated_cost_breakdown": Rough breakdown if budget info is available, otherwise use zeros.
- "key_requirements": Technical specifications, standards, conditions that must be met.
- "risks": Potential challenges or risks you identify.

Return ONLY the JSON object, nothing else."""


def analyze_tender_file(file_path: str, company_context: dict[str, str] | None = None) -> dict[str, Any]:
    """
    Analyze tender document by uploading directly to Gemini.
    
    Uses Gemini's vision capabilities to read scanned/image PDFs.
    
    Args:
        file_path: Path to the PDF file
        
    Returns:
        Structured data dict with summary, items, delivery_days, etc.
    """
    global _gemini_configured
    
    # Lazy initialization - configure Gemini on first call
    if not _gemini_configured:
        from app.core.config import settings
        
        api_key = settings.GOOGLE_API_KEY
        if api_key:
            genai.configure(api_key=api_key)
            _gemini_configured = True
            logger.info("Gemini AI configured successfully (lazy init)")
        else:
            logger.error("Cannot analyze: GOOGLE_API_KEY not configured")
            return {
                "error": "AI not configured",
                "summary": "AI analysis unavailable - API key not configured",
                "items": [],
                "delivery_days": 30,
                "required_licenses": [],
            }
    
    try:
        print(f"[AI] Uploading file to Gemini: {file_path}")
        
        # Upload file to Gemini
        uploaded_file = genai.upload_file(file_path)
        print(f"[AI] File uploaded: {uploaded_file.name}")
        
        # Create model (use gemini-3-flash-preview for vision + speed)
        model = genai.GenerativeModel(
            MODEL_NAME,  # Uses gemini-3-flash-preview
            generation_config=genai.types.GenerationConfig(
                response_mime_type="application/json",
            )
        )
        
        print("[AI] Sending to Gemini for analysis...")
        company_persona = _build_company_context(company_context)
        file_prompt = FILE_ANALYSIS_PROMPT.format(company_persona=company_persona)
        response = model.generate_content([uploaded_file, file_prompt])
        
        # Extract JSON from response
        response_text = response.text.strip()
        print(f"[AI] Raw response (first 300): {response_text[:300]}")
        
        # Clean up response (remove markdown code blocks if present)
        if response_text.startswith("```"):
            lines = response_text.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            response_text = "\n".join(lines)
        
        # Try to find JSON object in response
        start_idx = response_text.find("{")
        end_idx = response_text.rfind("}") + 1
        if start_idx >= 0 and end_idx > start_idx:
            response_text = response_text[start_idx:end_idx]
        
        result = json.loads(response_text)
        print(f"[AI] Analysis complete: {len(result.get('items', []))} items extracted")
        logger.info(f"AI file analysis complete: {len(result.get('items', []))} items extracted")
        
        # Cleanup uploaded file
        try:
            genai.delete_file(uploaded_file.name)
            print(f"[AI] Cleaned up uploaded file")
        except Exception:
            pass  # Ignore cleanup errors
        
        return result
        
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse AI response as JSON: {e}")
        return {
            "error": f"JSON parse error: {e}",
            "summary": "AI response could not be parsed - please try again",
            "items": [],
            "delivery_days": 30,
            "required_licenses": [],
        }
        
    except Exception as e:
        logger.error(f"Gemini API error: {e}")
        import traceback
        logger.error(traceback.format_exc())
        print(f"[AI] Error: {e}")
        return {
            "error": str(e),
            "summary": f"AI analysis failed: {e}",
            "items": [],
            "delivery_days": 30,
            "required_licenses": [],
        }


async def analyze_tender_file_async(file_path: str, company_context: dict[str, str] | None = None) -> dict[str, Any]:
    """
    Async wrapper for analyze_tender_file.
    
    Uses run_in_executor since google-generativeai is sync.
    """
    import asyncio
    from functools import partial
    
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, partial(analyze_tender_file, file_path, company_context))

