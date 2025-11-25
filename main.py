from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.security import APIKeyHeader
from starlette.status import HTTP_401_UNAUTHORIZED
from pydantic import BaseModel
from azure.storage.blob import BlobServiceClient
import pandas as pd
import random
from datetime import datetime
import io
import time
import os
import math

# Configuración Azure como variables de entorno
AZURE_CONNECTION_STRING = os.getenv("AZURE_CONNECTION_STRING") 
CONTAINER_NAME =  os.getenv("AZURE_CONTAINER_NAME") 

# Clave de API autorizada definida como variable de entorno
API_KEY_AUTORIZADA = os.getenv("API_KEY") 

# Definición del tipo de seguridad con el nombre de la cabecera
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

# Función de dependencia para verificar la clave de API
async def verificar_api_key(api_key_param: str = Depends(api_key_header)):
    if api_key_param != API_KEY_AUTORIZADA:
        raise HTTPException(status_code=401, detail="API Key no valida verifica la variable de entorno")
    return True

app = FastAPI(title="API para generación de archivos CSV con Protección de API Key")

class UploadRequest(BaseModel):
    folder_name: str       # Carpeta principal
    subfolder_name: str    # Subcarpeta específica
    rows: int              # Número de filas por archivo
    latency: int           # Intervalo entre envíos (milisegundos)
    duration: int          # Tiempo total (segundos)
    id_max_paciente: int   # numero max de id de pacientes que tenemos

@app.post("/start-upload", dependencies=[Depends(verificar_api_key)])
def start_upload(request: UploadRequest):
    # creamos el cliente
    errores_variables_entorno=None
    if AZURE_CONNECTION_STRING is None:
        errores_variables_entorno=errores_variables_entorno+" AZURE_CONNECTION_STRING "
    
    if CONTAINER_NAME is None:
        errores_variables_entorno=errores_variables_entorno+" CONTAINER_NAME "

    if errores_variables_entorno is not None:
        return {
            "message": f"Defina en su API las siguientes variables de entorno: {errores_variables_entorno}",
        }

    blob_service_client = BlobServiceClient.from_connection_string(AZURE_CONNECTION_STRING)
    
    #asignamos por defecto cada 1000 ms
    request.latency=1000 if request.latency==0 else request.latency


    #asignamos por defecto que la duración son 1 segundos
    request.duration=1 if request.duration==0 else request.duration

    #asignamos por defecto que el número máximo de id de paciente es 108
    request.id_max_paciente=8 if request.id_max_paciente==0 else request.id_max_paciente

    #asignamos por defecto número de filas
    request.rows=2 if request.rows==0 else request.rows


    #asignamos por defecto carpeta donde se guardara
    request.folder_name="spo2temperatura" if request.folder_name is None or request.folder_name=="string" else request.folder_name

    request.subfolder_name= None if request.subfolder_name == "string" else request.subfolder_name
    
    num_files = math.trunc(request.duration / (request.latency /1000))
    
    uploaded_files = []

    for i in range(num_files):
        # Generar datos aleatorios
        data = []
        id_paciente = math.trunc(random.uniform(101, request.id_max_paciente))

        # generamos aleatoriamente errores de temperatura para comprobar la validacion de datos
        generar_error_temperatura=random.uniform(0, 100)
        if generar_error_temperatura > 90:
            temperatura = round(random.uniform(-100, 100), 2)
        else:
            temperatura = round(random.uniform(20, 50), 2)

            SpO2 = round(random.uniform(60, 100), 2)
            timestamp = datetime.utcnow().isoformat()
            data.append({"id_paciente":id_paciente, "temperatura": temperatura, "SpO2": SpO2, "timestamp": timestamp })

        df = pd.DataFrame(data)

        # Convertir a CSV en memoria
        csv_buffer = io.StringIO()
        df.to_csv(csv_buffer, index=False)


        # Construir la ruta completa: carpeta/subcarpeta/archivo.csv 
        if not request.subfolder_name: #si no hay subcarpeta lo guarda en la ruta principal
            file_name = f"{request.folder_name}/datos_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{i}.csv"
        else:
            file_name = f"{request.folder_name}/{request.subfolder_name}/datos_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{i}.csv"


        # Subir a Azure Blob Storage
        blob_client = blob_service_client.get_blob_client(container=CONTAINER_NAME, blob=file_name)
        blob_client.upload_blob(csv_buffer.getvalue(), overwrite=True)
        uploaded_files.append(file_name)

        # Esperar latencia antes del siguiente envío
        if i < num_files - 1:
            time.sleep(request.latency/1000) #el parámetro de sleep está en segundos

    return {
        "message": f"{num_files} archivos subidos correctamente",
        "files": uploaded_files
    }
