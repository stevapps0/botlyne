from fastapi import FastAPI, UploadFile, File, HTTPException
from pydantic import BaseModel
from typing import Optional, List, Union
from enum import Enum
import httpx
import tempfile
import os
import asyncio
import logging
import time
from datetime import datetime
from pathlib import Path

from docling.document_converter import DocumentConverter
from docling.datamodel.base_models import ConversionStatus

# ============ Configuration ============
logger = logging.getLogger(__name__)

# Import settings for scraping service URL
from src.core.config import settings

class Config:
    SCRAPING_SERVICE_URL = settings.SCRAPING_SERVICE_URL
    SCRAPING_API_KEY = settings.SCRAPING_API_KEY
    MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB
    DOCUMENT_EXTENSIONS = {".pdf", ".docx", ".pptx", ".xlsx", ".html", ".md", ".txt", ".odt", ".rtf"}
    HTTP_TIMEOUT = settings.WEB_SCRAPING_TIMEOUT
    HEAD_REQUEST_TIMEOUT = 10.0
    MAX_PARALLEL_TASKS = 10

# ============ Enums ============
class ProcessingStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"

class ContentType(str, Enum):
    DOCUMENT = "document"
    WEBSITE = "website"

class SourceType(str, Enum):
    FILE = "file"
    URL = "url"

# ============ Models ============
class ProcessedItem(BaseModel):
    id: str
    title: Optional[str] = None
    content: str
    metadata: dict
    raw_response: Optional[dict] = None
    source: str
    source_type: SourceType
    content_type: ContentType
    processor: str
    status: ProcessingStatus
    error: Optional[str] = None
    processed_at: str

class BatchProcessResponse(BaseModel):
    batch_id: str
    total_items: int
    successful_items: int
    failed_items: int
    results: List[ProcessedItem]
    processing_time: float
    timestamp: str

# ============ Utility Classes ============
class URLDetector:
    """Detect URL content type (document vs website)"""
    
    @staticmethod
    async def detect(url: str) -> ContentType:
        """Detect if URL points to document or website"""
        try:
            # Check file extension first (fastest)
            path = url.split("?")[0].lower()
            if any(path.endswith(ext) for ext in Config.DOCUMENT_EXTENSIONS):
                return ContentType.DOCUMENT
            
            # Check Content-Type header
            async with httpx.AsyncClient() as client:
                response = await client.head(
                    url,
                    follow_redirects=True,
                    timeout=Config.HEAD_REQUEST_TIMEOUT
                )
                content_type = response.headers.get("content-type", "").lower()
                
                if any(ct in content_type for ct in ["application/pdf", "application/msword", "document"]):
                    return ContentType.DOCUMENT
                elif "text/html" in content_type:
                    return ContentType.WEBSITE
            
            return ContentType.WEBSITE
        except Exception as e:
            logger.warning(f"URL type detection failed for {url}: {e}. Defaulting to WEBSITE")
            return ContentType.WEBSITE

class DocumentProcessor:
    """Process documents with Docling"""
    
    @staticmethod
    async def process(source: str, item_id: str) -> ProcessedItem:
        """Process document (file path or URL) with Docling"""
        try:
            converter = DocumentConverter()
            result = converter.convert(source)
            
            if result.status != ConversionStatus.SUCCESS:
                return ProcessedItem(
                    id=item_id,
                    content="",
                    metadata={},
                    source=source,
                    source_type=SourceType.URL if source.startswith("http") else SourceType.FILE,
                    content_type=ContentType.DOCUMENT,
                    processor="docling",
                    status=ProcessingStatus.FAILED,
                    error=f"Conversion failed: {result.status}",
                    processed_at=datetime.utcnow().isoformat()
                )
            
            content = result.document.export_to_markdown()
            metadata = {
                "pages": len(result.document.pages) if hasattr(result.document, 'pages') else None,
                "language": getattr(result.document, 'language', None),
                "file_size": getattr(result.document, 'file_size', None),
            }
            
            return ProcessedItem(
                id=item_id,
                title=getattr(result.document, 'title', None),
                content=content,
                metadata=metadata,
                raw_response={"docling_status": str(result.status)},
                source=source,
                source_type=SourceType.URL if source.startswith("http") else SourceType.FILE,
                content_type=ContentType.DOCUMENT,
                processor="docling",
                status=ProcessingStatus.SUCCESS,
                processed_at=datetime.utcnow().isoformat()
            )
        except Exception as e:
            logger.error(f"Docling processing error for {source}: {e}")
            return ProcessedItem(
                id=item_id,
                content="",
                metadata={},
                source=source,
                source_type=SourceType.URL if source.startswith("http") else SourceType.FILE,
                content_type=ContentType.DOCUMENT,
                processor="docling",
                status=ProcessingStatus.FAILED,
                error=str(e),
                processed_at=datetime.utcnow().isoformat()
            )

class WebScraper:
    """Scrape websites with local scraping service"""
    
    @staticmethod
    async def scrape(url: str, item_id: str) -> ProcessedItem:
        """Scrape website using local scraping service with automatic retry"""
        from src.core.retry_utils import retry_http_request
        
        @retry_http_request(max_attempts=3)
        async def _do_scrape() -> ProcessedItem:
            """Inner function with retry logic"""
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        f"{Config.SCRAPING_SERVICE_URL}/scrape",
                        json={"urls": [url]},
                        headers={"Authorization": f"Bearer {Config.OPENLYNE_API_KEY}"},
                        timeout=Config.HTTP_TIMEOUT
                    )
                    
                    # Raise for HTTP errors (triggers retry on 5xx via decorator)
                    response.raise_for_status()
                    
                    data = response.json()
                    # Handle response - may be array or single object
                    result_data = data[0] if isinstance(data, list) and len(data) > 0 else data
                    
                    return ProcessedItem(
                        id=item_id,
                        title=result_data.get("title"),
                        content=result_data.get("content", ""),
                        metadata={
                            "url": url,
                            "status_code": result_data.get("status_code"),
                        },
                        raw_response=result_data,
                        source=url,
                        source_type=SourceType.URL,
                        content_type=ContentType.WEBSITE,
                        processor="scraping_service",
                        status=ProcessingStatus.SUCCESS,
                        processed_at=datetime.utcnow().isoformat()
                    )
                    
            except httpx.HTTPStatusError as e:
                status_code = e.response.status_code
                logger.error(f"HTTP {status_code} error for {url}: {e}")
                return WebScraper._create_error_item(
                    item_id, url, f"HTTP error {status_code}"
                )
                
            except httpx.ConnectError as e:
                logger.error(f"Connection error for {url}: {e}")
                return WebScraper._create_error_item(
                    item_id, url, "Cannot connect to scraping service"
                )
                
            except httpx.TimeoutException as e:
                logger.error(f"Timeout for {url}: {e}")
                return WebScraper._create_error_item(
                    item_id, url, "Request timeout"
                )
                
            except Exception as e:
                logger.error(f"Unexpected error scraping {url}: {e}")
                return WebScraper._create_error_item(
                    item_id, url, f"Unexpected error: {str(e)}"
                )
        
        return await _do_scrape()
    
    @staticmethod
    def _create_error_item(item_id: str, url: str, error: str) -> ProcessedItem:
        """Create error ProcessedItem"""
        return ProcessedItem(
            id=item_id,
            content="",
            metadata={},
            source=url,
            source_type=SourceType.URL,
            content_type=ContentType.WEBSITE,
            processor="scraping_service",
            status=ProcessingStatus.FAILED,
            error=error,
            processed_at=datetime.utcnow().isoformat()
        )

class ItemProcessor:
    """Route items to appropriate processor"""
    
    @staticmethod
    async def process(source: Union[str, tuple], item_id: str) -> ProcessedItem:
        """Route URL or file to appropriate processor"""
        try:
            if isinstance(source, tuple):
                # File upload (filename, content)
                return await ItemProcessor._process_file(source, item_id)
            else:
                # URL
                return await ItemProcessor._process_url(source, item_id)
        except Exception as e:
            logger.error(f"Error processing item {item_id}: {e}")
            return ProcessedItem(
                id=item_id,
                content="",
                metadata={},
                source=str(source)[:100],
                source_type=SourceType.URL if isinstance(source, str) else SourceType.FILE,
                content_type=ContentType.WEBSITE,
                processor="unknown",
                status=ProcessingStatus.FAILED,
                error=str(e),
                processed_at=datetime.utcnow().isoformat()
            )
    
    @staticmethod
    async def _process_file(file_data: tuple, item_id: str) -> ProcessedItem:
        """Save file to temp location and process with Docling"""
        filename, content = file_data
        ext = Path(filename).suffix
        
        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
            tmp.write(content)
            tmp_path = tmp.name
        
        try:
            return await DocumentProcessor.process(tmp_path, item_id)
        finally:
            os.unlink(tmp_path)
    
    @staticmethod
    async def _process_url(url: str, item_id: str) -> ProcessedItem:
        """Detect URL type and route to appropriate processor"""
        content_type = await URLDetector.detect(url)
        
        if content_type == ContentType.DOCUMENT:
            return await DocumentProcessor.process(url, item_id)
        else:
            return await WebScraper.scrape(url, item_id)

# ============ FastAPI Application ============
app = FastAPI(
    title="Unified Document & Link Processor",
    version="2.0",
    description="Process documents and web content with Docling and OpenLyne"
)

@app.post("/batch-process", response_model=BatchProcessResponse)
async def batch_process(
    urls: Optional[List[str]] = None,
    files: Optional[List[UploadFile]] = File(None)
):
    """
    Process multiple URLs and files in batch.
    
    - **urls**: List of URLs (documents or websites)
    - **files**: Uploaded files (documents)
    
    Returns structured content and metadata for each item.
    """
    start_time = time.time()
    batch_id = datetime.utcnow().strftime("%Y%m%d_%H%M%S_%f")
    items_to_process = []
    
    # Validate and collect URLs
    if urls:
        for idx, url in enumerate(urls):
            if not url or not isinstance(url, str):
                logger.warning(f"Invalid URL at index {idx}")
                continue
            items_to_process.append((f"{batch_id}_url_{idx}", url))
    
    # Validate and collect files
    if files:
        for idx, file in enumerate(files):
            if file.size is None or file.size > Config.MAX_FILE_SIZE:
                logger.warning(f"File {file.filename} exceeds max size or invalid")
                continue
            items_to_process.append((f"{batch_id}_file_{idx}", file))
    
    if not items_to_process:
        raise HTTPException(status_code=400, detail="No valid URLs or files provided")
    
    # Read file contents
    processed_items = []
    for item_id, item in items_to_process:
        if isinstance(item, UploadFile):
            content = await item.read()
            processed_items.append((item_id, (item.filename, content)))
        else:
            processed_items.append((item_id, item))
    
    # Process in batches to avoid overwhelming the system
    results = []
    for i in range(0, len(processed_items), Config.MAX_PARALLEL_TASKS):
        batch = processed_items[i:i + Config.MAX_PARALLEL_TASKS]
        tasks = [ItemProcessor.process(item[1], item[0]) for item in batch]
        batch_results = await asyncio.gather(*tasks)
        results.extend(batch_results)
    
    processing_time = time.time() - start_time
    successful = sum(1 for r in results if r.status == ProcessingStatus.SUCCESS)
    failed = len(results) - successful
    
    return BatchProcessResponse(
        batch_id=batch_id,
        total_items=len(results),
        successful_items=successful,
        failed_items=failed,
        results=results,
        processing_time=round(processing_time, 2),
        timestamp=datetime.utcnow().isoformat()
    )

@app.get("/health")
async def health():
    """Health check endpoint"""
    return {
        "status": "ok",
        "timestamp": datetime.utcnow().isoformat(),
        "version": "2.0"
    }

@app.get("/")
async def root():
    """API information"""
    return {
        "name": "Unified Document & Link Processor",
        "version": "2.0",
        "description": "Process documents and web content",
        "endpoints": {
            "POST /batch-process": "Process multiple URLs and files",
            "GET /health": "Health check"
        }
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, workers=1)