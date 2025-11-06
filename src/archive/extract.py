import os
from typing import Union, Tuple
from enum import Enum
import tempfile
import logging
from datetime import datetime

from docling.document_converter import DocumentConverter
from docling.datamodel.base_models import ConversionStatus
import httpx

logger = logging.getLogger(__name__)

class ProcessingStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"

class ContentType(str, Enum):
    DOCUMENT = "document"
    WEBSITE = "website"

class SourceType(str, Enum):
    FILE = "file"
    URL = "url"

class ProcessedItem:
    def __init__(self, id: str, content: str = "", metadata: dict = None, source: str = "",
                 source_type: SourceType = SourceType.FILE, content_type: ContentType = ContentType.DOCUMENT,
                 processor: str = "", status: ProcessingStatus = ProcessingStatus.FAILED,
                 error: str = None, processed_at: str = None, title: str = None, raw_response: dict = None):
        self.id = id
        self.title = title
        self.content = content
        self.metadata = metadata or {}
        self.raw_response = raw_response
        self.source = source
        self.source_type = source_type
        self.content_type = content_type
        self.processor = processor
        self.status = status
        self.error = error
        self.processed_at = processed_at or datetime.utcnow().isoformat()

class Config:
    OPENLYNE_API_URL = "https://crawl.openlyne.com"
    OPENLYNE_API_KEY = os.getenv("OPENLYNE_API_KEY", "your-api-key")
    MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB
    DOCUMENT_EXTENSIONS = {".pdf", ".docx", ".pptx", ".xlsx", ".html", ".md", ".txt", ".odt", ".rtf"}
    HTTP_TIMEOUT = 30.0
    HEAD_REQUEST_TIMEOUT = 10.0
    MAX_PARALLEL_TASKS = 10

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
    """Scrape websites with OpenLyne API"""

    @staticmethod
    async def scrape(url: str, item_id: str) -> ProcessedItem:
        """Scrape website using OpenLyne API"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{Config.OPENLYNE_API_URL}/crawl",
                    json={"url": url},
                    headers={"Authorization": f"Bearer {Config.OPENLYNE_API_KEY}"},
                    timeout=Config.HTTP_TIMEOUT
                )

                if response.status_code != 200:
                    error_msg = f"OpenLyne API error: {response.status_code}"
                    logger.error(f"{error_msg} for {url}")
                    return ProcessedItem(
                        id=item_id,
                        content="",
                        metadata={"status_code": response.status_code},
                        source=url,
                        source_type=SourceType.URL,
                        content_type=ContentType.WEBSITE,
                        processor="openlyne",
                        status=ProcessingStatus.FAILED,
                        error=error_msg,
                        processed_at=datetime.utcnow().isoformat()
                    )

                data = response.json()
                return ProcessedItem(
                    id=item_id,
                    title=data.get("title"),
                    content=data.get("content", ""),
                    metadata={
                        "url": url,
                        "status_code": data.get("status_code"),
                    },
                    raw_response=data,
                    source=url,
                    source_type=SourceType.URL,
                    content_type=ContentType.WEBSITE,
                    processor="openlyne",
                    status=ProcessingStatus.SUCCESS,
                    processed_at=datetime.utcnow().isoformat()
                )
        except httpx.RequestError as e:
            logger.error(f"OpenLyne request error for {url}: {e}")
            return ProcessedItem(
                id=item_id,
                content="",
                metadata={},
                source=url,
                source_type=SourceType.URL,
                content_type=ContentType.WEBSITE,
                processor="openlyne",
                status=ProcessingStatus.FAILED,
                error=f"Failed to scrape: {str(e)}",
                processed_at=datetime.utcnow().isoformat()
            )

class ItemProcessor:
    """Route items to appropriate processor"""

    @staticmethod
    async def process(source: Union[str, Tuple[str, bytes]], item_id: str) -> ProcessedItem:
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
    async def _process_file(file_data: Tuple[str, bytes], item_id: str) -> ProcessedItem:
        """Save file to temp location and process with Docling"""
        filename, content = file_data

        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(filename)[1]) as tmp:
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