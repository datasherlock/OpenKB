"""Image extraction and copy utilities for the OpenKB converter pipeline."""

from __future__ import annotations

import base64
import logging
import os
import re
import shutil
from pathlib import Path
from typing import Any

import pymupdf

logger = logging.getLogger(__name__)

# Matches: ![alt](data:image/ext;base64,DATA)
_BASE64_RE = re.compile(r"!\[([^\]]*)\]\(data:image/([^;]+);base64,([^)]+)\)")

# Matches: ![alt](relative/path) — excludes http(s):// and data: URIs
_RELATIVE_RE = re.compile(r"!\[([^\]]*)\]\((?!https?://|data:)([^)]+)\)")


# Minimum pixel dimension — skip icons, bullets, and tiny artifacts
_MIN_IMAGE_DIM = 32


def md_image_ref(alt: str, doc_name: str, filename: str) -> str:
    """Markdown image reference as written into ``wiki/sources/<doc>.md``.

    Note-relative (``images/{doc}/{file}``): source pages live directly in
    ``wiki/sources/``, so this resolves in every renderer that resolves links
    relative to the containing file (Obsidian, GitHub, VS Code). Internal
    metadata (the per-page JSON of long docs) keeps wiki-root-relative
    ``sources/images/...`` paths instead — those are consumed by tools that
    resolve against the wiki root, not rendered from a note.
    """
    return f"![{alt}](images/{doc_name}/{filename})"


_MIME_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".tiff": "image/tiff",
}


def transcribe_image_content(
    image_path: Path,
    model: str | None = None,
    doc_name: str = "",
    kb_dir: Path | None = None,
) -> str:
    """Transcribe technical or tabular image content into structured Markdown using LLM Vision.

    Extracts text, numbers, dates, KPI metrics, tables, and architecture diagrams.
    Returns empty string on failure or if vision transcription is disabled.
    """
    if not image_path.exists():
        return ""

    if not model and kb_dir:
        from openkb.config import resolve_effective_config

        cfg = resolve_effective_config(kb_dir)[0]
        model = cfg.get("model")
    if not model:
        model = "vertex_ai/gemini-3.8-flash"

    # Ensure environment variables (.env) from kb_dir are present
    if kb_dir and (kb_dir / ".env").exists():
        from dotenv import load_dotenv

        load_dotenv(kb_dir / ".env", override=False)

    try:
        import litellm
        from openkb.config import get_extra_headers, get_timeout

        mime = _MIME_TYPES.get(image_path.suffix.lower(), "image/png")
        b64 = base64.b64encode(image_path.read_bytes()).decode("utf-8")

        prompt = (
            "You are an expert technical document transcriber.\n"
            "Transcribe all visual and textual information from this image into clean, structured Markdown:\n"
            "1. Extract all headline metrics, dates, counts, and status indicators (e.g. RAG - Red, Amber, Green).\n"
            "2. Reconstruct any tables into standard Markdown tables with exact headers, rows, counts, and percentages.\n"
            "3. Transcribe all text, headings, bullet points, and callouts exactly as written.\n"
            "4. If there are flowcharts, architectural diagrams, or timeline curves, describe their structure, components, and key takeaways.\n"
            "Do not invent or omit information. Output only the transcribed Markdown."
        )

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime};base64,{b64}"},
                    },
                ],
            }
        ]

        kwargs: dict[str, Any] = {}
        extra_headers = get_extra_headers()
        if extra_headers:
            kwargs["extra_headers"] = extra_headers
        timeout = get_timeout()
        if timeout is not None:
            kwargs["timeout"] = timeout

        if os.getenv("VERTEXAI_PROJECT"):
            kwargs["vertex_project"] = os.getenv("VERTEXAI_PROJECT")
        if os.getenv("VERTEXAI_LOCATION"):
            kwargs["vertex_location"] = os.getenv("VERTEXAI_LOCATION")

        resp = litellm.completion(model=model, messages=messages, **kwargs)
        content = (resp.choices[0].message.content or "").strip()
        logger.info("Transcribed image %s (%d chars)", image_path.name, len(content))
        return content
    except Exception as exc:
        logger.warning("Failed to transcribe image %s with %s: %s", image_path.name, model, exc)
        return ""


def extract_pdf_images(pdf_path: Path, doc_name: str, images_dir: Path) -> dict[int, list[str]]:
    """Extract images from a PDF using pymupdf's dict-mode block iteration.

    Uses ``page.get_text("dict")`` to find image blocks (type 1) in reading
    order. Each image block is rendered via :class:`pymupdf.Pixmap` and saved
    as PNG. This captures both embedded bitmaps *and* vector-rendered figures
    that ``get_images()`` would miss.

    Returns a mapping of page_number (1-based) → list of image paths. Paths
    are wiki-root-relative (``sources/images/...``) — internal metadata for
    tools that resolve against the wiki root, not note-rendered markdown.
    """
    images_dir.mkdir(parents=True, exist_ok=True)
    page_images: dict[int, list[str]] = {}
    img_counter = 0

    with pymupdf.open(str(pdf_path)) as doc:
        for page_idx in range(len(doc)):
            page = doc[page_idx]
            page_num = page_idx + 1

            for block in page.get_text("dict")["blocks"]:
                if block["type"] != 1:  # not an image block
                    continue

                width = block.get("width", 0)
                height = block.get("height", 0)
                if width < _MIN_IMAGE_DIM or height < _MIN_IMAGE_DIM:
                    continue

                image_bytes = block.get("image")
                if not image_bytes:
                    continue

                try:
                    pix = pymupdf.Pixmap(image_bytes)
                    if pix.n > 4:
                        pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
                    img_counter += 1
                    filename = f"p{page_num}_img{img_counter}.png"
                    save_path = images_dir / filename
                    pix.save(str(save_path))
                    pix = None
                except Exception:
                    logger.warning("Failed to save image block on page %d", page_num)
                    continue

                rel_path = f"sources/images/{doc_name}/{filename}"
                page_images.setdefault(page_num, []).append(rel_path)
    return page_images


def convert_pdf_to_pages(
    pdf_path: Path,
    doc_name: str,
    images_dir: Path,
    model: str | None = None,
    kb_dir: Path | None = None,
    transcribe_images: bool = True,
) -> list[dict]:
    """Convert a PDF to per-page dicts with text content and images.

    Each dict has ``{"page": int, "content": str, "images": [{"path": str}]}``.
    Images are saved to *images_dir* and referenced with wiki-root-relative
    ``sources/images/...`` paths — these pages land in ``sources/<doc>.json``
    (never rendered from a note), and both ``get_wiki_page_content`` and
    ``read_wiki_image`` resolve them against the wiki root. When pages contain
    dashboards, diagrams, or sparse text, images are transcribed via LLM Vision.
    """
    images_dir.mkdir(parents=True, exist_ok=True)
    pages: list[dict] = []
    img_counter = 0

    with pymupdf.open(str(pdf_path)) as doc:
        for page_idx in range(len(doc)):
            page = doc[page_idx]
            page_num = page_idx + 1
            parts: list[str] = []
            page_images: list[dict] = []
            page_text_blocks: list[str] = []
            saved_images: list[tuple[str, Path, int, int]] = []

            for block in page.get_text("dict")["blocks"]:
                if block["type"] == 0:  # text block
                    lines = []
                    for line in block["lines"]:
                        spans_text = "".join(span["text"] for span in line["spans"])
                        lines.append(spans_text)
                    page_text_blocks.append("\n".join(lines))

                elif block["type"] == 1:  # image block
                    width = block.get("width", 0)
                    height = block.get("height", 0)
                    if width < _MIN_IMAGE_DIM or height < _MIN_IMAGE_DIM:
                        continue
                    image_bytes = block.get("image")
                    if not image_bytes:
                        continue
                    try:
                        pix = pymupdf.Pixmap(image_bytes)
                        if pix.n > 4:
                            pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
                        img_counter += 1
                        filename = f"p{page_num}_img{img_counter}.png"
                        save_path = images_dir / filename
                        save_path.write_bytes(pix.tobytes("png"))
                        pix = None
                        img_path = f"sources/images/{doc_name}/{filename}"
                        parts.append(f"\n![image]({img_path})\n")
                        page_images.append({"path": img_path})
                        saved_images.append((filename, save_path, width, height))
                    except Exception:
                        logger.warning("Failed to save image block on page %d", page_num)

            total_page_text = "\n".join(page_text_blocks).strip()

            # Render fallback page image if no text and no image blocks
            if not total_page_text and not saved_images:
                try:
                    pix = page.get_pixmap(dpi=150)
                    img_counter += 1
                    filename = f"p{page_num}_page{img_counter}.png"
                    save_path = images_dir / filename
                    pix.save(str(save_path))
                    img_path = f"sources/images/{doc_name}/{filename}"
                    parts.append(f"\n![image]({img_path})\n")
                    page_images.append({"path": img_path})
                    saved_images.append((filename, save_path, int(pix.width), int(pix.height)))
                    pix = None
                except Exception:
                    logger.warning("Failed to render fallback page on page %d", page_num)

            if total_page_text:
                parts.insert(0, total_page_text)

            is_sparse = len(total_page_text) < 100
            if transcribe_images:
                for filename, save_path, width, height in saved_images:
                    is_large = width >= 300 and height >= 200
                    if is_sparse or is_large:
                        transcript = transcribe_image_content(
                            save_path, model=model, doc_name=doc_name, kb_dir=kb_dir
                        )
                        if transcript:
                            parts.append(f"\n{transcript}\n")

            pages.append(
                {
                    "page": page_num,
                    "content": "\n".join(parts),
                    "images": page_images,
                }
            )
    return pages


def convert_pdf_with_images(
    pdf_path: Path,
    doc_name: str,
    images_dir: Path,
    model: str | None = None,
    kb_dir: Path | None = None,
    transcribe_images: bool = True,
) -> str:
    """Convert a PDF to markdown with inline images using pymupdf dict-mode.

    Iterates blocks in reading order per page. Text blocks become text,
    image blocks are saved to disk and replaced with a note-relative
    ``![image](images/{doc_name}/...)`` link inline. When a page has sparse
    text or significant visual assets (dashboards, charts, tables), LLM Vision
    transcribes the full structured markdown directly into the source.

    Returns the full markdown string.
    """
    images_dir.mkdir(parents=True, exist_ok=True)
    parts: list[str] = []
    img_counter = 0

    with pymupdf.open(str(pdf_path)) as doc:
        for page_idx in range(len(doc)):
            page = doc[page_idx]
            page_num = page_idx + 1
            parts.append("\n\n")

            page_text_blocks: list[str] = []
            saved_images: list[tuple[str, Path, int, int]] = []

            for block in page.get_text("dict")["blocks"]:
                if block["type"] == 0:  # text block
                    lines = []
                    for line in block["lines"]:
                        spans_text = "".join(span["text"] for span in line["spans"])
                        lines.append(spans_text)
                    page_text_blocks.append("\n".join(lines))

                elif block["type"] == 1:  # image block
                    width = block.get("width", 0)
                    height = block.get("height", 0)
                    if width < _MIN_IMAGE_DIM or height < _MIN_IMAGE_DIM:
                        continue
                    image_bytes = block.get("image")
                    if not image_bytes:
                        continue
                    try:
                        pix = pymupdf.Pixmap(image_bytes)
                        if pix.n > 4:
                            pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
                        img_counter += 1
                        filename = f"p{page_num}_img{img_counter}.png"
                        save_path = images_dir / filename
                        save_path.write_bytes(pix.tobytes("png"))
                        pix = None
                        saved_images.append((filename, save_path, width, height))
                    except Exception:
                        logger.warning("Failed to save image block on page %d", page_num)

            total_page_text = "\n".join(page_text_blocks).strip()

            # If page had no text and no images extracted, render full page as an image
            if not total_page_text and not saved_images:
                try:
                    pix = page.get_pixmap(dpi=150)
                    img_counter += 1
                    filename = f"p{page_num}_page{img_counter}.png"
                    save_path = images_dir / filename
                    pix.save(str(save_path))
                    saved_images.append((filename, save_path, int(pix.width), int(pix.height)))
                    pix = None
                except Exception:
                    logger.warning("Failed to render fallback page on page %d", page_num)

            if total_page_text:
                parts.append(total_page_text)

            is_sparse = len(total_page_text) < 100
            for filename, save_path, width, height in saved_images:
                parts.append(f"\n{md_image_ref('image', doc_name, filename)}\n")
                is_large = width >= 300 and height >= 200
                if transcribe_images and (is_sparse or is_large):
                    transcript = transcribe_image_content(
                        save_path, model=model, doc_name=doc_name, kb_dir=kb_dir
                    )
                    if transcript:
                        parts.append(f"\n{transcript}\n")
    return "\n".join(parts)


def extract_base64_images(markdown: str, doc_name: str, images_dir: Path) -> str:
    """Decode base64-embedded images, save to disk, and rewrite markdown links.

    For each ``![alt](data:image/ext;base64,DATA)`` match:
    - Decode base64 bytes → save to ``images_dir/img_NNN.ext``
    - Replace the link with ``![alt](images/{doc_name}/img_NNN.ext)``
    - On decode failure: log a warning and leave the original text unchanged.
    """
    counter = 0
    result = markdown

    for match in _BASE64_RE.finditer(markdown):
        alt, ext, b64_data = match.group(1), match.group(2), match.group(3)
        try:
            image_bytes = base64.b64decode(b64_data, validate=True)
        except Exception:
            logger.warning(
                "Failed to decode base64 image (alt=%r, ext=%r); leaving original.",
                alt,
                ext,
            )
            continue

        counter += 1
        filename = f"img_{counter:03d}.{ext}"
        dest = images_dir / filename
        images_dir.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(image_bytes)

        new_ref = md_image_ref(alt, doc_name, filename)
        result = result.replace(match.group(0), new_ref, 1)

    return result


def copy_relative_images(markdown: str, source_dir: Path, doc_name: str, images_dir: Path) -> str:
    """Copy locally-referenced images into the KB images directory and rewrite links.

    For each ``![alt](relative/path)`` match (skipping http/https and data URIs):
    - Resolve path relative to ``source_dir``
    - Copy to ``images_dir/{filename}``
    - Replace link with ``![alt](images/{doc_name}/{filename})``
    - Missing source file: log a warning and leave the original text unchanged.
    """
    result = markdown
    # Track the destination chosen for each already-copied source so the same
    # image referenced twice isn't duplicated, plus the set of taken names so
    # two *different* sources that share a basename (e.g. ``a/logo.png`` and
    # ``b/logo.png``) don't overwrite each other and collapse both links onto a
    # single image.
    assigned: dict[Path, str] = {}
    taken: set[str] = set()

    for match in _RELATIVE_RE.finditer(markdown):
        alt, rel_path = match.group(1), match.group(2)
        src = (source_dir / rel_path).resolve()
        if not src.is_relative_to(source_dir.resolve()):
            logger.warning("Image path escapes source dir: %s; skipping.", rel_path)
            continue
        if not src.exists():
            logger.warning("Relative image not found: %s; leaving original link.", src)
            continue

        filename = assigned.get(src)
        if filename is None:
            filename = src.name
            n = 1
            while filename in taken:
                filename = f"{src.stem}_{n}{src.suffix}"
                n += 1
            assigned[src] = filename
            taken.add(filename)
            images_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, images_dir / filename)

        new_ref = md_image_ref(alt, doc_name, filename)
        result = result.replace(match.group(0), new_ref, 1)

    return result
