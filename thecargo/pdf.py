from __future__ import annotations

import asyncio


async def render_html_to_pdf(
    html: str,
    *,
    renderer: str = "gotenberg",
    gotenberg_url: str | None = None,
) -> bytes:
    if renderer == "weasyprint":
        return await _via_weasyprint(html)
    if not gotenberg_url:
        raise RuntimeError("gotenberg_url is required for the 'gotenberg' renderer")
    return await _via_gotenberg(html, gotenberg_url)


async def _via_gotenberg(html: str, gotenberg_url: str) -> bytes:
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
    def _run() -> bytes:
        from weasyprint import HTML

        return HTML(string=html).write_pdf()

    return await asyncio.to_thread(_run)
