"""一般研究材料的有界正文提取；PDF 保留页码且不伪装 OCR 结果。"""

from pathlib import Path
import shutil
import subprocess
import tempfile
import time

from bs4 import BeautifulSoup

from alpha.contracts.cancellation import CancellationToken
from alpha.contracts.research_materials import ResearchMaterial

_PDF_TIMEOUT_SECONDS = 20.0
_POLL_SECONDS = 0.05
_MAX_TEXT_BYTES = 2 * 1024 * 1024
_MAX_PAGE_RANGE = 5


def extract_material_text(material: ResearchMaterial, content: bytes, temporary_root: Path, *,
                          first_page: int = 1, last_page: int = 1, token: CancellationToken | None = None) -> str:
    """提取指定页或文本正文。参数：材料、字节、临时目录、页范围、Host 令牌。返回：带页码原文。异常：取消、损坏、超限或缺解析器。"""
    if token is not None:
        token.raise_if_cancelled()
    if first_page < 1 or last_page < first_page or last_page - first_page >= _MAX_PAGE_RANGE:
        raise ValueError("单次读取 PDF 须为连续 1–5 页")
    if material.media_type == "application/pdf":
        return _extract_pdf(content, temporary_root, first_page, last_page, token)
    if first_page != 1 or last_page != 1:
        raise ValueError("文本附件不接受 PDF 页码参数")
    if len(content) > _MAX_TEXT_BYTES:
        raise ValueError("文本材料超过 2 MiB 提取上限，请拆分后导入")
    text = content.decode("utf-8-sig")
    if material.media_type == "text/html":
        soup = BeautifulSoup(text, "html.parser")
        for element in soup(("script", "style", "noscript")):
            element.decompose()
        text = soup.get_text(separator="\n")
    if not text.strip():
        raise ValueError("材料未提取到有效正文，不得作为已核验依据")
    return text


def _extract_pdf(content: bytes, temporary_root: Path, first_page: int, last_page: int, token: CancellationToken | None) -> str:
    """调用可取消 Poppler 并回收临时文件。参数：字节、目录、页范围、令牌。返回：逐页文字。异常：缺解析器、取消、损坏、扫描件或超限。"""
    executable = shutil.which("pdftotext")
    if executable is None:
        raise ValueError("PDF 文本解析需要 Poppler pdftotext；请安装后重试，扫描件需另外 OCR")
    temporary_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="research-pdf-", dir=temporary_root) as directory:
        root = Path(directory)
        source, output = root / "source.pdf", root / "pages.txt"
        source.write_bytes(content)
        with output.open("wb") as stdout:
            process = subprocess.Popen([executable, "-layout", "-enc", "UTF-8", "-f", str(first_page), "-l", str(last_page), str(source), "-"],
                                       stdout=stdout, stderr=subprocess.DEVNULL)
            deadline = time.monotonic() + _PDF_TIMEOUT_SECONDS
            try:
                while process.poll() is None:
                    if token is not None:
                        token.raise_if_cancelled()
                    if time.monotonic() >= deadline or output.stat().st_size > _MAX_TEXT_BYTES:
                        raise ValueError("PDF 提取超时或输出超过上限")
                    if token is not None:
                        token.wait(_POLL_SECONDS)
                    else:
                        time.sleep(_POLL_SECONDS)
            finally:
                if process.poll() is None:
                    process.kill()
                process.wait()
        if token is not None:
            token.raise_if_cancelled()
        if process.returncode != 0 or output.stat().st_size > _MAX_TEXT_BYTES:
            raise ValueError("PDF 损坏、加密、页码不存在或提取输出超限")
        text = output.read_text(encoding="utf-8")
        pages = text.split("\f")
        if not text.strip():
            raise ValueError("PDF 未提取到文字，可能是扫描件；尚未 OCR，不得作为已核验依据")
        return "\n\n".join(f"[PDF 第 {first_page + index} 页]\n{page}" for index, page in enumerate(pages) if page.strip())
