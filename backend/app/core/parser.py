"""
Plasma AI - Document Parser

Extracts text from tender documents (PDF, DOCX, TXT).
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def extract_text_from_pdf(file_path: str | Path) -> str:
    """
    Extract text from a PDF file using pypdf, with pdfminer.six fallback.
    
    Args:
        file_path: Path to the PDF file
        
    Returns:
        Extracted text as a single string
    """
    from pypdf import PdfReader
    
    # Try pypdf first
    try:
        print(f"[PARSER] Opening PDF with pypdf: {file_path}")
        reader = PdfReader(file_path)
        print(f"[PARSER] PDF has {len(reader.pages)} pages")
        text_parts = []
        
        for i, page in enumerate(reader.pages):
            try:
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text)
            except Exception as page_err:
                print(f"[PARSER] Page {i+1} extraction failed: {page_err}")
        
        full_text = "\n\n".join(text_parts)
        print(f"[PARSER] pypdf extracted: {len(full_text)} chars")
        
        # If pypdf got text, return it
        if len(full_text) >= 100:
            return full_text
            
    except Exception as e:
        print(f"[PARSER] pypdf extraction failed: {e}")
    
    # Fallback to pdfminer.six
    print("[PARSER] Trying pdfminer.six fallback...")
    try:
        from pdfminer.high_level import extract_text
        pdfminer_text = extract_text(str(file_path))
        print(f"[PARSER] pdfminer.six extracted: {len(pdfminer_text)} chars")
        if pdfminer_text and len(pdfminer_text) >= 100:
            return pdfminer_text
    except Exception as e:
        print(f"[PARSER] pdfminer.six extraction failed: {e}")
    
    # Both methods failed - likely scanned PDF
    print("[PARSER] Both extraction methods failed - likely scanned/image PDF")
    return ""


def extract_text_from_bytes(file_bytes: bytes, file_type: str) -> str:
    """
    Extract text from file bytes.
    
    Args:
        file_bytes: Raw file content
        file_type: File extension (pdf, docx, txt)
        
    Returns:
        Extracted text as a single string
    """
    import tempfile
    import os
    
    file_type = file_type.lower().strip(".")
    print(f"[PARSER] extract_text_from_bytes: file_type='{file_type}', bytes_len={len(file_bytes)}")
    
    if file_type == "pdf":
        # Write to temp file and extract
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(file_bytes)
            temp_path = f.name
        
        try:
            return extract_text_from_pdf(temp_path)
        finally:
            os.unlink(temp_path)
    
    elif file_type == "txt":
        # Try common encodings
        for encoding in ["utf-8", "cp1251", "latin-1"]:
            try:
                return file_bytes.decode(encoding)
            except UnicodeDecodeError:
                continue
        return file_bytes.decode("utf-8", errors="ignore")
    
    elif file_type in ("doc", "docx"):
        # DOCX support (requires python-docx)
        try:
            from docx import Document
            import io
            
            doc = Document(io.BytesIO(file_bytes))
            paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
            return "\n\n".join(paragraphs)
        except ImportError:
            logger.warning("python-docx not installed, cannot parse DOCX")
            return ""
        except Exception as e:
            logger.error(f"DOCX extraction failed: {e}")
            return ""
    
    else:
        logger.warning(f"Unsupported file type: {file_type}")
        return ""


def extract_text_from_file(file_path: str | Path) -> str:
    """
    Extract text from a file based on its extension.
    
    Args:
        file_path: Path to the file
        
    Returns:
        Extracted text as a single string
    """
    path = Path(file_path)
    suffix = path.suffix.lower().lstrip(".")
    
    logger.info(f"[PARSER] extract_text_from_file: path={path}, suffix='{suffix}', exists={path.exists()}")
    
    if suffix == "pdf":
        return extract_text_from_pdf(path)
    
    elif suffix == "txt":
        with open(path, "rb") as f:
            return extract_text_from_bytes(f.read(), "txt")
    
    elif suffix in ("doc", "docx"):
        with open(path, "rb") as f:
            return extract_text_from_bytes(f.read(), suffix)
    
    else:
        logger.warning(f"Unsupported file type: {suffix}")
        return ""
