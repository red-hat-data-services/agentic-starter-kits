# LlamaStack Agent (LlamaStack API only, no LlamaIndex). Python 3.12+ required by llama-stack-client.
FROM python:3.12-slim

WORKDIR /app

RUN groupadd -r appuser && useradd -r -u 1001 -g appuser appuser

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY main.py .
COPY src/ ./src/

RUN chown -R appuser:appuser /app
USER appuser

EXPOSE 8080
ENV PORT=8080
ENV PYTHONPATH=/app:/app/src

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
