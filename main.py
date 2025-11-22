import argparse
import logging

from typing import Optional, Union

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
try:
    from pydantic import BaseModel, Field, ConfigDict
except ImportError:  # pragma: no cover - pydantic v1 fallback
    from pydantic import BaseModel, Field  # type: ignore[misc]
    ConfigDict = None  # type: ignore[assignment]

from acm_meta.crossref_client import CrossrefClient
from acm_meta.errors import MetaError, MetaErrorCode
from acm_meta.models import UploadResponseItem
from acm_meta.pipeline import MetadataPipeline, save_outputs
from acm_meta.settings import (
    INDEX_HTML,
    MAX_UPLOAD_BATCH,
    PDF_DIR,
    RECORDS_CSV_PATH,
    RECORDS_JSON_PATH,
    RECORDS_XLSX_PATH,
    STATIC_DIR,
)
from acm_meta.storage import RecordStore


load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("acm_meta")


class ReorderPayload(BaseModel):
    order: list[str]


class RecordPatchPayload(BaseModel):
    title: Optional[str] = Field(None, alias="Title")
    venue: Optional[str] = Field(None, alias="Venue")
    publication_year: Optional[Union[int, str]] = Field(None, alias="Publication year")
    author_list: Optional[str] = Field(None, alias="Author list")
    abstract: Optional[str] = Field(None, alias="Abstract")
    doi: Optional[str] = Field(None, alias="DOI")

    if ConfigDict is not None:
        model_config = ConfigDict(populate_by_name=True)  # type: ignore[misc]
    else:  # pragma: no cover - pydantic v1 fallback
        class Config:
            allow_population_by_field_name = True


store = RecordStore()
crossref_client = CrossrefClient()
pipeline = MetadataPipeline(store, crossref_client)

app = FastAPI(title="ACM Meta MVP")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def dump_by_alias(model: BaseModel, *, exclude_unset: bool = True) -> dict:
    try:
        return model.model_dump(by_alias=True, exclude_unset=exclude_unset)
    except AttributeError:  # pragma: no cover - Pydantic v1 fallback
        return model.dict(by_alias=True, exclude_unset=exclude_unset)


async def process_upload_file(file: UploadFile) -> UploadResponseItem:
    try:
        record, _ = await pipeline.process_upload(file)
        return UploadResponseItem.success(record)
    except MetaError as exc:
        logger.warning("Processing error for %s: %s", file.filename, exc)
        return UploadResponseItem.failure(file.filename, code=exc.code.value, message=exc.message)
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.exception("Unexpected failure for %s", file.filename)
        return UploadResponseItem.failure(file.filename, code=MetaErrorCode.UNKNOWN_ERROR.value, message=str(exc))


@app.get("/", response_class=FileResponse)
def read_index():
    return FileResponse(INDEX_HTML)


@app.post("/api/upload")
async def upload(file: UploadFile = File(...)):
    result = await process_upload_file(file)
    status_code = 200 if result.status == "ok" else 400
    return JSONResponse(result.to_payload(), status_code=status_code)


@app.post("/api/upload/batch")
async def upload_batch(files: list[UploadFile] = File(...)):
    if not files:
        raise HTTPException(status_code=400, detail="No files provided")
    if len(files) > MAX_UPLOAD_BATCH:
        raise HTTPException(status_code=400, detail=f"Maximum {MAX_UPLOAD_BATCH} files per upload")

    results = [await process_upload_file(upload_file) for upload_file in files]
    success = any(item.status == "ok" for item in results)
    body: dict[str, object] = {
        "status": "ok" if success else "error",
        "results": [item.to_payload() for item in results],
    }
    if not success:
        failure = next((item for item in results if item.status != "ok"), None)
        if failure:
            body["error"] = failure.message
            body["code"] = failure.error_code
    status_code = 200 if success else 400
    return JSONResponse(body, status_code=status_code)


@app.get("/api/records")
def list_records():
    return {"records": store.reversed_snapshot()}


@app.delete("/api/records/{record_id:path}")
def delete_record(record_id: str):
    if store.delete(record_id):
        return {"status": "ok"}
    raise HTTPException(status_code=404, detail="Record not found")


@app.post("/api/records/reorder")
def reorder_records(payload: ReorderPayload):
    if not payload.order:
        raise HTTPException(status_code=400, detail="Order list required")
    store.reorder(payload.order)
    return {"status": "ok"}


@app.patch("/api/records/{record_id:path}")
def patch_record(record_id: str, payload: RecordPatchPayload):
    updates = dump_by_alias(payload)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields provided")
    try:
        record = store.update_fields(record_id, updates)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "ok", "record": record}


@app.get("/api/export")
def export_records():
    store.flush()
    return FileResponse(RECORDS_CSV_PATH, filename="metadata_records.csv")


@app.get("/api/export/json")
def export_records_json():
    store.flush()
    return FileResponse(RECORDS_JSON_PATH, filename="metadata_records.json")


@app.get("/api/export/xlsx")
def export_records_xlsx():
    path = store.export_xlsx()
    return FileResponse(path, filename=RECORDS_XLSX_PATH.name)


def main() -> None:
    parser = argparse.ArgumentParser(description="ACM Meta MVP")
    parser.add_argument(
        "mode",
        nargs="?",
        default="batch",
        choices=["batch", "serve"],
        help="batch: process pdfs/ directory; serve: launch API",
    )
    args = parser.parse_args()

    if args.mode == "batch":
        results = pipeline.batch_process(PDF_DIR)
        save_outputs(results)
    else:
        import uvicorn

        uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)


if __name__ == "__main__":
    main()
