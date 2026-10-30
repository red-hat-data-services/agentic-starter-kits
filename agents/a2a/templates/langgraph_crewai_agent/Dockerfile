# Single image for both A2A servers; set A2A_ROLE at runtime (Kubernetes env or docker run -e).
# Use Red Hat UBI9 Python 3.12 image (no Docker Hub rate limits on OpenShift)
# To update: docker pull registry.access.redhat.com/ubi9/python-312:latest
#            docker inspect --format='{{index .RepoDigests 0}}' registry.access.redhat.com/ubi9/python-312:latest
FROM registry.access.redhat.com/ubi9/python-312@sha256:e95978812895b9abb2bdc109b501078da2a47c8dbb9fa23758af40ed50ab6023

WORKDIR /app

# Switch to root for installing dependencies and preparing runtime paths
USER 0

# To update: docker pull ghcr.io/astral-sh/uv:latest
#            docker inspect --format='{{index .RepoDigests 0}}' ghcr.io/astral-sh/uv:latest
COPY --from=ghcr.io/astral-sh/uv@sha256:fc93e9ecd7218e9ec8fba117af89348eef8fd2463c50c13347478769aaedd0ce /uv /usr/local/bin/uv

COPY pyproject.toml uv.lock ./
COPY src ./src
# Install from the lockfile so builds are reproducible (--frozen fails if
# uv.lock is stale relative to pyproject.toml).
# Always install MLflow tracing deps for container images (Kagenti auto-configures
# MLflow tracing when deployed to MLflow operator from RHOAI)
# pysqlite3-binary (installed inline) provides SQLite >= 3.35 for ChromaDB on UBI9
ENV UV_PROJECT_ENVIRONMENT=/opt/app-root
RUN uv sync --frozen --no-dev --extra tracing \
    && uv pip install --no-cache pysqlite3-binary \
    && SITE=$(python3 -c "import site; print(site.getsitepackages()[0])") \
    && printf '__import__("pysqlite3")\nimport sys\nsys.modules["sqlite3"] = sys.modules.pop("pysqlite3")\n' > "$SITE/sitecustomize.py"

COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# CrewAI runtime paths (OpenShift arbitrary UID / GID 0)
RUN mkdir -p /home/appuser/.local/share/app \
    && chown -R 1001:0 /app /home/appuser \
    && chmod -R g=u /app /home/appuser \
    && chmod g+x /app/entrypoint.sh

ENV HOME=/home/appuser
ENV PYTHONPATH=/app
ENV PORT=8080

USER 1001

EXPOSE 8080

ENTRYPOINT ["/app/entrypoint.sh"]
