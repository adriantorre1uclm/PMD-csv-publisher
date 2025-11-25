# PMD-csv-publisher

## Requisitos

- FastAPI (para la API)
- azure-storage-blob (para interactuar con Azure Blob Storage)
- pandas (para generar el CSV)
- random y datetime (para datos aleatorios)

## Estructura de la API

Endpoint: POST /start-upload
Parámetros:
- folder_name: carpeta dentro del contenedor
- subfolder_name: subcarpeta específica (por ejemplo, pacientes_sanos)
- rows: número de filas en el archivo csv que indican cuantas medidas se enviarán
- latency: cada cuánto tiempo se envía un archivo (en milisegundos).
- duration: durante cuánto tiempo se estarán enviando archivos (en segundos).
- id_max_paciente: cuál es el valor máximo de id de paciente, considerando los datos que tenemos en la tabla de pacientes en nuestro catalogo


### Acción realizada por la FastAPI

Generar y subir múltiples archivos CSV con columnas id_paciente timestamp, temperatura y humedad al Blob Storage.
Cada archivo se sube después de esperar la latencia indicada.
El proceso termina cuando se cumple la duración.

## Configuración necesaria en la Web APP en Azure
Para poder **ejecutar** esta FastAPI, necesitas definir las siguientes **variables de entorno** en tu web app en Azure:
- AZURE_CONNECTION_STRING # recupera el valor en Tu cuenta de almacenamiento/Claves de acceso/Cadena de Conexión
- AZURE_CONTAINER_NAME  # nombre del contenedor que hayas creado
- API_KEY # contraseña que has establecido para poder ejecutar tu APIKEY

También necesitas establecer cuál es eñ **comando de inicio** disponible en Configuración/Configuración de la Pila:
gunicorn -w 4 -k uvicorn.workers.UvicornWorker main:app

## Alternativa: Ejecutar tu Web APP en VSCode

1. Instalar los siguients paquetes:

- python -m pip install fastapi uvicorn[standard]
- python -m pip install pandas
- python -m pip install azure.storage.blob

2. Clonar el repo o bajar main.py
3. Proporcionar los valores para las variables de entorno en lugar de utilizar las almacenadas en la web app:

- AZURE_CONNECTION_STRING ="DefaultEndpointsProtocol=++++" # recupera el valor en Tu cuenta de almacenamiento/Claves de acceso/Cadena de Conexión
- CONTAINER_NAME = "sensorespacientes" # nombre del contenedor que hayas creado
- API_KEY = "tucontraseña" # la que quieras utilizar para la ejecución
  
4. Ejecutar la FastAPI con el siguiente comando en el terminal:
http://127.0.0.1:8000/docs/


