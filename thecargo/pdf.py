"""Shared HTML → PDF rendering primitive.

Three interchangeable backends behind one async call so every service
renders its documents (contracts, invoices, receipts) through the same
code path instead of each re-implementing the transport:

* ``gotenberg`` (default) — POSTs the HTML to a headless-Chromium sidecar
  over REST. Keeps the browser out of the service image and isolates a
  render OOM to the sidecar; byte-faithful to the on-screen page.
* ``weasyprint`` — pure-Python paged media (Cairo / Pango), no browser or
  subprocess. Lazily imported so the wheel stays optional.
* ``chromium`` — a local headless-Chrome subprocess, mainly for dev and
  pixel-regression against the historical renderer.

The function is settings-agnostic: callers pass the chosen ``renderer`` and
its inputs, so the primitive never reaches into any one service's config.
Document assembly (templates + context) stays in the owning service.
"""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)

DEFAULT_CHROME_CANDIDATES = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "google-chrome",
    "chromium",
)


async def render_html_to_pdf(
    html: str,
    *,
    renderer: str = "gotenberg",
    gotenberg_url: str | None = None,
    chrome_candidates: tuple[str, ...] = DEFAULT_CHROME_CANDIDATES,
) -> bytes:
    """Render a full HTML document to PDF bytes via the selected backend.

    Raises ``RuntimeError`` when the selected backend is unavailable (no
    Chrome binary found, or a missing gotenberg url) so failures stay loud
    rather than returning a degraded artifact.
    """
    if renderer == "chromium":
        pdf = await _via_chromium(html, chrome_candidates)
        if not pdf:
            raise RuntimeError(
                "Chrome/Chromium binary not found — install one (`apt-get install -y chromium`) or expose it on PATH."
            )
        return pdf
    if renderer == "weasyprint":
        return await _via_weasyprint(html)
    if not gotenberg_url:
        raise RuntimeError("gotenberg_url is required for the 'gotenberg' renderer")
    return await _via_gotenberg(html, gotenberg_url)


async def _via_gotenberg(html: str, gotenberg_url: str) -> bytes:
    """POST the HTML to the Gotenberg sidecar and stream back the PDF.

    ``preferCssPageSize`` honours the template's ``@page`` size and
    ``printBackground`` keeps background colours/fills in the output.
    """
    import httpx

    files = {"index.html": ("index.html", html.encode("utf-8"), "text/html")}
    data = {"preferCssPageSize": "true", "printBackground": "true"}
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            f"{gotenberg_url.rstrip('/')}/forms/chromium/convert/html",
            files=files,
            data=data,
        )
        resp.raise_for_status()
        return resp.content


async def _via_weasyprint(html: str) -> bytes:
    """Render via WeasyPrint — pure-Python paged media, no browser/subprocess.

    Requires the ``weasyprint`` wheel plus its Cairo/Pango system libraries;
    the lazy import keeps the dependency optional for gotenberg-only images.
    """

    def _run() -> bytes:
        from weasyprint import HTML

        return HTML(string=html).write_pdf()

    return await asyncio.to_thread(_run)


def _find_chrome_binary(candidates: tuple[str, ...]) -> str | None:
    import shutil
    from pathlib import Path

    for candidate in candidates:
        if "/" in candidate and Path(candidate).is_file():
            return candidate
        if "/" not in candidate:
            resolved = shutil.which(candidate)
            if resolved:
                return resolved
    return None


async def _via_chromium(html: str, candidates: tuple[str, ...]) -> bytes | None:
    """Render via a local headless-Chrome subprocess; ``None`` if no binary.

    Chrome supports the full modern CSS stack (flexbox/grid, web fonts,
    gradients, SVG) so the PDF is a pixel-faithful copy of the browser view.
    """
    chrome = _find_chrome_binary(candidates)
    if not chrome:
        return None

    import tempfile
    from pathlib import Path

    def _run() -> bytes | None:
        import subprocess

        with tempfile.TemporaryDirectory(prefix="pdf_render_") as td:
            tmpdir = Path(td)
            html_path = tmpdir / "doc.html"
            pdf_path = tmpdir / "doc.pdf"
            html_path.write_text(html, encoding="utf-8")
            cmd = [
                chrome,
                "--headless=new",
                "--disable-gpu",
                "--no-sandbox",
                "--no-pdf-header-footer",
                "--hide-scrollbars",
                "--virtual-time-budget=8000",
                f"--print-to-pdf={pdf_path}",
                f"file://{html_path}",
            ]
            try:
                subprocess.run(cmd, check=True, timeout=30, capture_output=True)
            except subprocess.CalledProcessError as exc:
                logger.warning("Chrome PDF render failed (code %s): %s", exc.returncode, exc.stderr[:200])
                return None
            except subprocess.TimeoutExpired:
                logger.warning("Chrome PDF render timed out")
                return None
            if not pdf_path.exists():
                return None
            return pdf_path.read_bytes()

    return await asyncio.to_thread(_run)
