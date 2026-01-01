from __future__ import annotations

import csv
import io
import logging
import os
import random
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from azure.storage.blob import BlobServiceClient, ContentSettings
from fastapi import Depends, FastAPI, HTTPException
from fastapi.security import APIKeyHeader
from pydantic import BaseModel

logger = logging.getLogger("csv_publisher")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

# Configuración Azure como variables de entorno
AZURE_CONNECTION_STRING = os.getenv("AZURE_CONNECTION_STRING")
CONTAINER_NAME = os.getenv("AZURE_CONTAINER_NAME")

# Clave de API autorizada definida como variable de entorno
API_KEY_AUTORIZADA = os.getenv("API_KEY")

# Definición del tipo de seguridad con el nombre de la cabecera
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

# Función de dependencia para verificar la clave de API
async def verificar_api_key(api_key_param: str = Depends(api_key_header)):
    if not API_KEY_AUTORIZADA:
        raise HTTPException(
            status_code=500,
            detail="API_KEY no está configurada en variables de entorno",
        )
    if api_key_param != API_KEY_AUTORIZADA:
        raise HTTPException(
            status_code=401,
            detail="API Key no válida (cabecera X-API-Key)",
        )
    return True

app = FastAPI(title="API para generación de archivos CSV con Protección de API Key")

class UploadRequest(BaseModel):
    # Nuevos parámetros (benchmark)
    folder_name: str
    subfolder_name: Optional[str] = None

    flat_files: int = 100
    partitioned_files: int = 100
    rows_per_file: int = 10_000
    id_max_paciente: int = 100_000

    # Rango temporal (ISO). Si no se envían, por defecto: ahora()-30d .. ahora()
    start_ts: Optional[str] = None
    end_ts: Optional[str] = None

    partition_granularity: str = "date_hour"
    seed: Optional[int] = None

    write_both: bool = True
    write_flat: bool = True
    write_partitioned: bool = True

    # Campos legacy (compatibilidad). Ya NO controlan el comportamiento.
    rows: Optional[int] = None
    latency: Optional[int] = None
    duration: Optional[int] = None


def _ensure_azure_env() -> None:
    missing = []
    if not AZURE_CONNECTION_STRING:
        missing.append("AZURE_CONNECTION_STRING")
    if not CONTAINER_NAME:
        missing.append("AZURE_CONTAINER_NAME")
    if missing:
        raise HTTPException(
            status_code=500,
            detail=f"Faltan variables de entorno: {', '.join(missing)}",
        )


_BLOB_SERVICE_CLIENT: Optional[BlobServiceClient] = None


def get_blob_service_client() -> BlobServiceClient:
    global _BLOB_SERVICE_CLIENT
    _ensure_azure_env()
    if _BLOB_SERVICE_CLIENT is None:
        _BLOB_SERVICE_CLIENT = BlobServiceClient.from_connection_string(
            AZURE_CONNECTION_STRING
        )
    return _BLOB_SERVICE_CLIENT


def parse_iso_datetime(s: str) -> datetime:
    """
    Parse ISO datetime into timezone-aware UTC datetime.
    Accepts 'Z' suffix.
    """
    if not s:
        raise ValueError("timestamp ISO vacío")
    raw = s.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _floor_to_hour(dt: datetime) -> datetime:
    dt = dt.astimezone(timezone.utc)
    return dt.replace(minute=0, second=0, microsecond=0)


def random_bucket_hours(
    start: datetime, end: datetime, k: int, rng: random.Random
) -> list[datetime]:
    """
    Return a list of hour-start datetimes (UTC) length k.
    Tries to sample unique hour buckets when possible.
    """
    if k <= 0:
        return []

    start_hour = _floor_to_hour(start)
    end_hour = _floor_to_hour(end)
    if end <= start:
        raise ValueError("start_ts debe ser < end_ts")

    total_hours = int((end_hour - start_hour).total_seconds() // 3600) + 1
    if total_hours <= 0:
        return [start_hour] * k

    if k <= total_hours:
        idxs = rng.sample(range(total_hours), k)
        return [start_hour + timedelta(hours=i) for i in idxs]

    # Más ficheros que horas disponibles → permite repetición
    return [start_hour + timedelta(hours=rng.randrange(total_hours)) for _ in range(k)]


def _iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def generate_rows_for_hour(
    bucket_hour: datetime,
    n_rows: int,
    rng: random.Random,
    id_max_paciente: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    base = _floor_to_hour(bucket_hour)
    for _ in range(n_rows):
        seconds = rng.randrange(3600)
        micros = rng.randrange(1_000_000)
        ts = base + timedelta(seconds=seconds, microseconds=micros)
        rows.append(
            {
                "id_paciente": rng.randint(1, id_max_paciente),
                "temperatura": round(rng.uniform(35.0, 40.5), 2),
                "SpO2": round(rng.uniform(85.0, 100.0), 2),
                "timestamp": _iso_z(ts),
            }
        )
    return rows


def generate_rows_uniform_range(
    start: datetime,
    end: datetime,
    n_rows: int,
    rng: random.Random,
    id_max_paciente: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    start = start.astimezone(timezone.utc)
    end = end.astimezone(timezone.utc)
    delta_s = (end - start).total_seconds()
    for _ in range(n_rows):
        offset = rng.random() * delta_s
        ts = start + timedelta(seconds=offset)
        rows.append(
            {
                "id_paciente": rng.randint(1, id_max_paciente),
                "temperatura": round(rng.uniform(35.0, 40.5), 2),
                "SpO2": round(rng.uniform(85.0, 100.0), 2),
                "timestamp": _iso_z(ts),
            }
        )
    return rows


def rows_to_csv_bytes(rows: list[dict[str, Any]]) -> bytes:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=["id_paciente", "temperatura", "SpO2", "timestamp"])
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue().encode("utf-8")


def _clean_subfolder(subfolder: Optional[str]) -> Optional[str]:
    if not subfolder:
        return None
    s = subfolder.strip().strip("/")
    return s or None


def build_flat_path(folder_name: str, subfolder: Optional[str], run_id: str, i: int) -> str:
    root = f"{folder_name}_flat"
    sub = _clean_subfolder(subfolder)
    if sub:
        return f"{root}/{sub}/datos_{run_id}_{i}.csv"
    return f"{root}/datos_{run_id}_{i}.csv"


def build_partitioned_path(
    folder_name: str,
    subfolder: Optional[str],
    bucket_hour: datetime,
    run_id: str,
    i: int,
) -> str:
    root = f"{folder_name}_partitioned"
    sub = _clean_subfolder(subfolder)
    date_str = bucket_hour.astimezone(timezone.utc).strftime("%Y-%m-%d")
    hour_str = bucket_hour.astimezone(timezone.utc).strftime("%H")
    prefix = f"{root}/date={date_str}/hour={hour_str}"
    if sub:
        prefix = f"{root}/{sub}/date={date_str}/hour={hour_str}"
    return f"{prefix}/datos_{run_id}_{i}.csv"


def upload_blob(path: str, content_bytes: bytes) -> None:
    bsc = get_blob_service_client()
    blob_client = bsc.get_blob_client(container=CONTAINER_NAME, blob=path)
    blob_client.upload_blob(
        content_bytes,
        overwrite=True,
        content_settings=ContentSettings(content_type="text/csv; charset=utf-8"),
    )


def _default_range_if_missing(start_ts: Optional[str], end_ts: Optional[str]) -> tuple[datetime, datetime]:
    now = datetime.now(timezone.utc)
    try:
        start = parse_iso_datetime(start_ts) if start_ts else (now - timedelta(days=30))
        end = parse_iso_datetime(end_ts) if end_ts else now
    except ValueError as e:
        raise HTTPException(status_code=422, detail=f"start_ts/end_ts inválidos: {e}") from e
    if start >= end:
        raise HTTPException(status_code=422, detail="start_ts debe ser < end_ts")
    return start, end


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "azure_configured": bool(AZURE_CONNECTION_STRING and CONTAINER_NAME),
        "container": CONTAINER_NAME,
    }

@app.post("/start-upload", dependencies=[Depends(verificar_api_key)])
def start_upload(request: UploadRequest) -> dict[str, Any]:
    """
    Generador de benchmark: en una sola llamada puede escribir flat + partitioned.

    Paths:
    - Flat:         <folder_name>_flat/<subfolder?>/datos_<run_id>_<i>.csv
    - Partitioned:  <folder_name>_partitioned/<subfolder?>/date=YYYY-MM-DD/hour=HH/datos_<run_id>_<i>.csv
    """
    _ensure_azure_env()

    # Compatibilidad: si alguien manda rows legacy, úsalo como rows_per_file (sin obligar al usuario a saberlo).
    if request.rows is not None and request.rows > 0:
        request.rows_per_file = request.rows

    # Validaciones clave
    if not request.folder_name or not request.folder_name.strip():
        raise HTTPException(status_code=422, detail="folder_name es obligatorio")
    if request.flat_files < 0 or request.partitioned_files < 0:
        raise HTTPException(status_code=422, detail="flat_files/partitioned_files deben ser >= 0")
    if request.rows_per_file <= 0:
        raise HTTPException(status_code=422, detail="rows_per_file debe ser > 0")
    if request.id_max_paciente <= 0:
        raise HTTPException(status_code=422, detail="id_max_paciente debe ser > 0")
    if request.partition_granularity != "date_hour":
        raise HTTPException(status_code=422, detail="partition_granularity soportada: 'date_hour'")

    start_dt, end_dt = _default_range_if_missing(request.start_ts, request.end_ts)

    # Control simple de modos
    if request.write_both:
        write_flat = True
        write_partitioned = True
    else:
        write_flat = bool(request.write_flat)
        write_partitioned = bool(request.write_partitioned)

    rng = random.Random(request.seed)
    run_id = str(uuid.uuid4())

    flat_written = 0
    partitioned_written = 0
    flat_examples: list[str] = []
    partitioned_examples: list[str] = []

    # Flat generation: timestamps uniformes en todo el rango por fila (rango amplio).
    if write_flat and request.flat_files > 0:
        for i in range(request.flat_files):
            rows = generate_rows_uniform_range(
                start=start_dt,
                end=end_dt,
                n_rows=request.rows_per_file,
                rng=rng,
                id_max_paciente=request.id_max_paciente,
            )
            path = build_flat_path(
                folder_name=request.folder_name,
                subfolder=request.subfolder_name,
                run_id=run_id,
                i=i,
            )
            upload_blob(path, rows_to_csv_bytes(rows))
            flat_written += 1
            if len(flat_examples) < 5:
                flat_examples.append(path)
            if flat_written % 10 == 0:
                logger.info("Flat: subidos %s/%s", flat_written, request.flat_files)

    # Partitioned generation: 1 partición por fichero (date/hour), pero muchas particiones globalmente.
    if write_partitioned and request.partitioned_files > 0:
        buckets = random_bucket_hours(
            start=start_dt,
            end=end_dt,
            k=request.partitioned_files,
            rng=rng,
        )
        for i, bucket_hour in enumerate(buckets):
            rows = generate_rows_for_hour(
                bucket_hour=bucket_hour,
                n_rows=request.rows_per_file,
                rng=rng,
                id_max_paciente=request.id_max_paciente,
            )
            path = build_partitioned_path(
                folder_name=request.folder_name,
                subfolder=request.subfolder_name,
                bucket_hour=bucket_hour,
                run_id=run_id,
                i=i,
            )
            upload_blob(path, rows_to_csv_bytes(rows))
            partitioned_written += 1
            if len(partitioned_examples) < 5:
                partitioned_examples.append(path)
            if partitioned_written % 10 == 0:
                logger.info(
                    "Partitioned: subidos %s/%s", partitioned_written, request.partitioned_files
                )

    flat_root = f"{request.folder_name}_flat/"
    partitioned_root = f"{request.folder_name}_partitioned/"
    if _clean_subfolder(request.subfolder_name):
        flat_root = f"{request.folder_name}_flat/{_clean_subfolder(request.subfolder_name)}/"
        partitioned_root = (
            f"{request.folder_name}_partitioned/{_clean_subfolder(request.subfolder_name)}/"
        )

    return {
        "run_id": run_id,
        "flat_files_written": flat_written,
        "partitioned_files_written": partitioned_written,
        "base_paths": {
            "flat_root": flat_root,
            "partitioned_root": partitioned_root,
        },
        "example_paths": {
            "flat": flat_examples,
            "partitioned": partitioned_examples,
        },
        "timestamp_range_used": {
            "start_ts": _iso_z(start_dt),
            "end_ts": _iso_z(end_dt),
        },
        "rows_per_file": request.rows_per_file,
        "partition_granularity": request.partition_granularity,
        "seed": request.seed,
        "write_both": request.write_both,
    }
