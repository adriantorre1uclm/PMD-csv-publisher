## PMD-csv-publisher (benchmark data generator)

API FastAPI para **generar datos sintéticos** (CSV) y subirlos a **Azure Blob Storage**, pensada para benchmarking en Databricks comparando:

- **Flat (sin partición)**: listing grande en una raíz
- **Partitioned (por date/hour)**: folder partitioning `date=YYYY-MM-DD/hour=HH`

### Requisitos

- `fastapi`
- `uvicorn`
- `azure-storage-blob`

### Variables de entorno

Define estas variables (local o en tu Web App):

- **AZURE_CONNECTION_STRING**: cadena de conexión del Storage Account
- **AZURE_CONTAINER_NAME**: nombre del contenedor destino
- **API_KEY**: clave esperada en el header `X-API-Key`

### Endpoints

- **GET `/health`**: healthcheck simple
- **POST `/start-upload`**: genera y sube ficheros CSV (benchmark)

### POST `/start-upload` (llamada mínima)

Con este payload mínimo, la API por defecto genera en **una sola ejecución**:

- **100 ficheros** en **flat root**
- **100 ficheros** en **partitioned root (date/hour)**
- **rows_per_file = 10000**
- timestamps distribuidos en un rango amplio (**últimos 30 días** por defecto)

Payload mínimo:

```json
{
  "folder_name": "spo2temperatura",
  "subfolder_name": "pacientes_sanos"
}
```

Ejemplo `curl`:

```bash
curl -X POST "http://127.0.0.1:8000/start-upload" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: TU_API_KEY" \
  -d "{\"folder_name\":\"spo2temperatura\",\"subfolder_name\":\"pacientes_sanos\"}"
```

En PowerShell (Windows):

```powershell
curl.exe -X POST "http://127.0.0.1:8000/start-upload" `
  -H "Content-Type: application/json" `
  -H "X-API-Key: TU_API_KEY" `
  -d "{\"folder_name\":\"spo2temperatura\",\"subfolder_name\":\"pacientes_sanos\"}"
```

### Paths generados en Azure Blob

Raíces fijas:

- **Flat root**: `<folder_name>_flat/`
- **Partitioned root**: `<folder_name>_partitioned/`

Si `subfolder_name` viene vacío o `null`, no se añade. Si viene con valor, se inserta como un nivel adicional.

**1) Flat**

`<folder_name>_flat/<subfolder opcional>/datos_<run_id>_<i>.csv`

Ejemplo:

- `spo2temperatura_flat/pacientes_sanos/datos_7a9d..._0.csv`

**2) Partitioned (date_hour)**

`<folder_name>_partitioned/<subfolder opcional>/date=YYYY-MM-DD/hour=HH/datos_<run_id>_<i>.csv`

Ejemplo:

- `spo2temperatura_partitioned/pacientes_sanos/date=2025-12-10/hour=03/datos_7a9d..._17.csv`

Nota importante: en el modo **partitioned**, **cada fichero cae en una única partición** (una sola combinación date/hour). Globalmente, los 100 ficheros se reparten en muchos buckets para forzar la creación de muchas carpetas `date=/hour=` en una sola ejecución.

### Parámetros configurables (opcionales)

Además de `folder_name` / `subfolder_name`, puedes enviar (todos opcionales):

- `flat_files` (default 100)
- `partitioned_files` (default 100)
- `rows_per_file` (default 10000)
- `id_max_paciente` (default 100000)
- `start_ts` (ISO, ejemplo `"2025-12-01T00:00:00Z"`; default `now()-30d`)
- `end_ts` (ISO, ejemplo `"2025-12-31T23:59:59Z"`; default `now()`)
- `seed` (int, reproducibilidad)
- `write_both` (default true). Si `false`, usar `write_flat` / `write_partitioned`

### Ejecución local

Instalar dependencias:

```bash
python -m pip install -r requirements.txt
```

Arrancar:

```bash
uvicorn main:app --reload
```

Swagger:

`http://127.0.0.1:8000/docs/`
