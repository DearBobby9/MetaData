# acm-meta-mvp

Metadata-first pipeline for ACM Digital Library PDFs. The MVP prioritizes automatic extraction of structured fields (Title, Venue, Year, Authors, Abstract, DOI) so the teacher's spreadsheet can be filled with minimal manual effort. Representative figures and video links remain manual placeholders for later releases.

---

## 1. 老师需求 & 字段拆解

### 1.1 目标数据结构

每篇论文需要输出一行 spreadsheet，列名与顺序固定如下：

| Column | 描述 | 约束 |
| --- | --- | --- |
| Title | 论文标题 | 原始英文标题，末尾不加标点 |
| Venue | 会议 / 期刊名 | 使用正式全称（例如 `CHI Conference on Human Factors in Computing Systems`） |
| Publication year | 出版年份 | 四位整数，例如 `2022` |
| Author list | 作者列表 | `名字 姓氏` 形式，用 `, ` 分隔；不含 `and` 或句号 |
| Abstract | 摘要 | 去掉 ABSTRACT 标题后的纯英文段落 |
| Representative figure | 代表图片 | 目前 MVP 固定填 `N/A`，后续可填文件名 |
| DOI | 数字对象标识符 | 形如 `10.1145/3491102.3502071` |
| Video | 公开视频链接 | 只接受 YouTube/Vimeo；没有则 `N/A` |

### 1.2 Metadata 核心字段

本轮优先自动化：Title、Venue、Publication year、Author list、Abstract、DOI。Representative figure 与 Video 是人工回填的富媒体字段，降级到后续版本。

---

## 2. 项目分期 & 优先级

### 2.1 V0 / MVP（当前范围）

- 支持批量或 Web 上传 ACM DL PDF（假定均含 DOI）。
- 从 PDF 前几页用正则提取 DOI，调用 Crossref `/works/{doi}` 获取 metadata。
- 规范化字段并生成两个输出：
  - `output/metadata.json`：完整记录（调试、后续扩展用）。
  - `output/metadata_for_spreadsheet.csv`：列顺序即老师所需，图与视频占位 `N/A`。

### 2.2 V1（下一步）

- 当 Crossref 缺摘要时，回退到 PDF 内文搜索 “Abstract” 段。
- CLI/前端工具帮助人工挑选 representative figure、填写视频链接。
- 辅助脚本导出 PDF 内所有图片。

### 2.3 V2+（长期）

- 自动抓取官方视频链接或推荐候选。
- 图片评分/排序，辅助挑选 teaser。
- 生成 making prompts、XR 浏览体验等研究化功能。

---

## 3. MVP 项目文档

### 3.1 概述

- **项目名**：`acm-meta-mvp`
- **目标**：给定任何 ACM DL PDF，自动输出 Title / Venue / Year / Authors / Abstract / DOI，结果可直接贴入老师的 spreadsheet。
- **流程**：PDF → 提取 DOI → Crossref metadata → 清洗 → JSON & CSV。

### 3.2 技术栈

- Python 3.10+
- FastAPI + Uvicorn：Web API (`/api/upload`).
- PyPDF：解析 PDF 文本以捕捉 DOI。
- Requests：访问 Crossref API。
- Pandas：生成 CSV。
- python-dotenv：读取 Crossref 邮箱配置（礼貌 User-Agent）。

### 3.3 目录结构

```text
MetaData/
├─ README.md
├─ requirements.txt
├─ main.py
├─ config.example.env
├─ data/
│  └─ .gitkeep              # 运行后会生成 records.json / records.csv，持久化所有 metadata
├─ frontend/
│  └─ index.html
├─ static/
│  ├─ app.js
│  └─ styles.css
├─ pdfs/
└─ output/
```

`frontend/index.html` + `static/` 组成了新的 Web UI：运行 `python main.py serve` 后，访问 `http://127.0.0.1:8000/` 即可批量上传（一次最多 20 篇），实时查看 metadata 卡片，并在“Metadata 表格”页浏览/导出持久化数据。

### 3.4 依赖与配置

`requirements.txt`

```txt
fastapi
uvicorn[standard]
pypdf
requests
pandas
python-dotenv
python-multipart
```

`config.example.env`

```env
CROSSREF_MAILTO=your_email@example.com
```

复制为 `.env` 并替换邮箱即可。

### 3.5 核心实现（`main.py`）

功能概览：

1. **DOI 提取**：`pypdf` 读取前两页文本，使用 `r"10\.\d{4,9}/[^\s\"<>]+"` 正则。
2. **Crossref 查询**：`GET https://api.crossref.org/works/{doi}`，User-Agent 带邮箱。
3. **字段规范化**：
   - Title：`message.title[0]`；
   - Venue：`container-title[0]`；
   - Publication year：`issued.date-parts[0][0]`；
   - Author list：`given family` 拼接后用 `, ` 连接；
   - Abstract：去除 HTML 标签；
   - DOI：Crossref 返回或 PDF fallback。
4. **输出**：
   - `metadata.json`：`[{ file_name, title, venue, year, authors[], abstract, doi, source_url, raw_crossref }]`。
   - `metadata_for_spreadsheet.csv`：8 列固定顺序，图与视频默认 `N/A`。
5. **Web 接口**：`/api/upload` 接收单个 PDF，落盘后返回一行 metadata。
6. **CLI 模式**：`python main.py batch` 批处理 `pdfs/`；`python main.py serve` 启动 API。

完整可运行示例：

```python
import os
import re
import json
import argparse
from pathlib import Path
from typing import Optional, Dict, List

import requests
from pypdf import PdfReader
import pandas as pd
from dotenv import load_dotenv

from fastapi import FastAPI, UploadFile, File
from fastapi.responses import JSONResponse

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
PDF_DIR = BASE_DIR / "pdfs"
OUT_DIR = BASE_DIR / "output"
PDF_DIR.mkdir(exist_ok=True, parents=True)
OUT_DIR.mkdir(exist_ok=True, parents=True)

DOI_RE = re.compile(r"\b10\.\d{4,9}/[^\s\"<>]+\b")
CROSSREF_API_BASE = "https://api.crossref.org/works"


def extract_doi_from_pdf(pdf_path: Path, max_pages: int = 2) -> Optional[str]:
    reader = PdfReader(str(pdf_path))
    text = ""
    for page in reader.pages[:max_pages]:
        text += page.extract_text() or ""
    match = DOI_RE.search(text)
    return match.group(0) if match else None


def fetch_crossref_metadata(doi: str) -> Dict:
    url = f"{CROSSREF_API_BASE}/{doi}"
    headers = {
        "User-Agent": f"acm-meta-mvp/1.0 (mailto:{os.getenv('CROSSREF_MAILTO', 'nobody@example.com')})"
    }
    resp = requests.get(url, headers=headers, timeout=15)
    resp.raise_for_status()
    return resp.json().get("message", {})


def strip_tags(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text).strip()


def normalize_metadata(message: Dict, file_name: str, doi_fallback: Optional[str]) -> Dict:
    title_list = message.get("title") or []
    title = title_list[0] if title_list else ""

    authors: List[str] = []
    for author in message.get("author", []):
        given = author.get("given") or ""
        family = author.get("family") or ""
        full = " ".join(part for part in [given, family] if part)
        if full:
            authors.append(full)
    author_list_str = ", ".join(authors)

    issued = message.get("issued", {}).get("date-parts", [[None]])
    year = issued[0][0] if issued and issued[0] else ""

    venue_list = message.get("container-title") or []
    venue = venue_list[0] if venue_list else ""

    doi = message.get("DOI") or doi_fallback or ""

    abstract_raw = message.get("abstract")
    abstract = strip_tags(abstract_raw) if isinstance(abstract_raw, str) else ""

    sheet_row = {
        "Title": title,
        "Venue": venue,
        "Publication year": year,
        "Author list": author_list_str,
        "Abstract": abstract,
        "Representative figure": "N/A",
        "DOI": doi,
        "Video": "N/A",
    }

    full = {
        "file_name": file_name,
        "title": title,
        "venue": venue,
        "year": year,
        "authors": authors,
        "abstract": abstract,
        "doi": doi,
        "source_url": message.get("URL", ""),
        "raw_crossref": message,
    }

    return {"sheet_row": sheet_row, "full": full}


def process_single_pdf(pdf_path: Path) -> Dict:
    doi = extract_doi_from_pdf(pdf_path)
    if not doi:
        raise ValueError(f"DOI not found in {pdf_path.name}")

    metadata = fetch_crossref_metadata(doi)
    return normalize_metadata(metadata, pdf_path.name, doi)


def batch_process(pdf_dir: Path = PDF_DIR) -> List[Dict]:
    results: List[Dict] = []
    for pdf in sorted(pdf_dir.glob("*.pdf")):
        print(f"[INFO] Processing: {pdf.name}")
        try:
            info = process_single_pdf(pdf)
            results.append(info)
            print(f"       ✔ DOI={info['sheet_row']['DOI']}")
        except Exception as exc:
            print(f"       ✖ Failed: {exc}")
    return results


def save_outputs(results: List[Dict]):
    json_data = [item["full"] for item in results]
    json_path = OUT_DIR / "metadata.json"
    json_path.write_text(json.dumps(json_data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[INFO] JSON written to {json_path}")

    sheet_rows = [item["sheet_row"] for item in results]
    df = pd.DataFrame(sheet_rows, columns=[
        "Title",
        "Venue",
        "Publication year",
        "Author list",
        "Abstract",
        "Representative figure",
        "DOI",
        "Video",
    ])
    csv_path = OUT_DIR / "metadata_for_spreadsheet.csv"
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    print(f"[INFO] CSV written to {csv_path}")


app = FastAPI(title="ACM Meta MVP")


@app.post("/api/upload")
async def upload(file: UploadFile = File(...)):
    pdf_path = PDF_DIR / file.filename
    with pdf_path.open("wb") as dest:
        dest.write(await file.read())

    try:
        result = process_single_pdf(pdf_path)
        return JSONResponse({
            "status": "ok",
            "data": result["sheet_row"],
            "debug": {
                "file_name": result["full"]["file_name"],
                "source_url": result["full"].get("source_url", ""),
            }
        })
    except Exception as exc:
        return JSONResponse({"status": "error", "error": str(exc)}, status_code=400)


def main():
    parser = argparse.ArgumentParser(description="ACM Meta MVP")
    parser.add_argument(
        "mode",
        nargs="?",
        default="batch",
        choices=["batch", "serve"],
        help="batch: process pdfs/ directory; serve: launch FastAPI server"
    )
    args = parser.parse_args()

    if args.mode == "batch":
        results = batch_process(PDF_DIR)
        save_outputs(results)
    elif args.mode == "serve":
        import uvicorn
        uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)


if __name__ == "__main__":
    main()
```

#### 持久化 & 批量 API

- `POST /api/upload/batch`：一次上传最多 20 个 `files`，返回每个文件的处理状态；成功的条目会写入 `data/records.json` & `data/records.csv`。
- `GET /api/records`：返回当前已保存的所有 metadata 行，新数据按时间倒序排列，可用于前端表格或自定义脚本。
- `GET /api/export`：直接下载 `data/records.csv`，列顺序与老师 Spreadsheet 完全一致。
- `data/` 目录保存的 JSON/CSV 在刷新或重启后不会丢失，可作为长期语料库。若想清空，只需删除对应文件即可。

### 3.6 运行步骤

1. **初始化环境**
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   cp config.example.env .env  # 并编辑 CROSSREF_MAILTO
   mkdir -p pdfs output
   ```

2. **批量提取**
   ```bash
   python main.py batch
   ```
   - 成功后在 `output/metadata.json` 与 `output/metadata_for_spreadsheet.csv` 查看结果。
   - CSV 列顺序为 Title → Venue → Publication year → Author list → Abstract → Representative figure → DOI → Video，其中后两项预填 `N/A`。

3. **Web 上传（可选）**
   ```bash
   python main.py serve
   ```
   - 打开浏览器访问 `http://127.0.0.1:8000/`，可见两个视图：
     - **上传 PDF**：拖拽或点击一次性选择 ≤20 个 PDF，实时查看最新成功条目的 Metadata 卡片；下方状态列表会逐个显示成功/失败情况。
     - **Metadata 表格**：浏览所有历史记录（存储在 `data/records.json`），点击右上角即可导出 CSV。
   - 若需脚本化调用，可继续使用 `curl`：
     ```bash
     curl -X POST http://127.0.0.1:8000/api/upload/batch \
       -F "files=@pdfs/sample1.pdf" \
       -F "files=@pdfs/sample2.pdf"
     ```

4. **一键运行前后端**
   ```bash
   ./run.sh
   ```
   - 自动创建/复用 `.venv`、安装依赖、确保 `.env` 存在，并以 `python main.py serve` 启动 FastAPI（前后端共用）。
   - 结束服务时使用 `Ctrl + C`。

### 3.7 交付与后续

- **交付方式**：运行批处理后，把 CSV 中的 Representative figure、Video 人工补齐再上交；JSON 留作后续扩展语料。
- **后续钩子**：
  1. 在 `normalize_metadata` 中为 Representative figure / Video 预留字段，后续脚本可直接写入 CSV。
  2. `raw_crossref` 始终保留，方便未来做关键词/推荐等 AI 处理。

---

## 4. 状态速览

- ✅ 自动 metadata：DOI 提取 + Crossref + CSV/JSON 输出。
- ⏳ 待办（V1）：PDF 摘要回退、图像导出、视频/图人工填表工具。
- 🔭 V2：自动图像/视频推荐、making prompt 生成、XR 浏览等。

此 README 即项目文档，可直接跟老师作业对齐，也为后续扩展提供路线。
