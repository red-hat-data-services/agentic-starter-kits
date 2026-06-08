# Single image for both A2A servers; set A2A_ROLE at runtime (Kubernetes env or docker run -e).
FROM python:3.12-slim

WORKDIR /app

RUN groupadd -r appuser && useradd -r -u 1001 -g 0 -m -d /home/appuser appuser

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY pyproject.toml .
COPY src ./src
# Always install MLflow tracing deps for container images (Kagenti auto-configures
# MLflow tracing when deployed to MLflow operator from RHOAI)
RUN uv pip install --system --no-cache ".[tracing]"

COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# CrewAI runtime paths (OpenShift arbitrary UID / GID 0)
RUN mkdir -p /home/appuser/.local/share/app \
    && chown -R appuser:0 /app /home/appuser \
    && chmod -R g=u /app /home/appuser \
    && chmod g+x /app/entrypoint.sh

ENV HOME=/home/appuser
ENV PYTHONPATH=/app
ENV PORT=8080

USER appuser

EXPOSE 8080

ENTRYPOINT ["/app/entrypoint.sh"]
