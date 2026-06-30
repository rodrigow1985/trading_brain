FROM python:3.11-slim

WORKDIR /app

# Dependencias primero — capa cacheada si requirements.txt no cambia
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Código fuente
COPY src/ ./src/
COPY scripts/ ./scripts/

# /app/data persiste la base SQLite entre reinicios (montado como volumen)
RUN mkdir -p /app/data

ENV PYTHONPATH=/app

CMD ["python", "scripts/hello.py"]
