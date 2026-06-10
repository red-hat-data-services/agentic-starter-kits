# Use Red Hat UBI9 Python 3.12 image (no Docker Hub rate limits on OpenShift)
# To update: docker pull registry.access.redhat.com/ubi9/python-312:latest
#            docker inspect --format='{{index .RepoDigests 0}}' registry.access.redhat.com/ubi9/python-312:latest
FROM registry.access.redhat.com/ubi9/python-312@sha256:e95978812895b9abb2bdc109b501078da2a47c8dbb9fa23758af40ed50ab6023
WORKDIR /opt/app-root/src

# Switch to root for installing dependencies
USER 0

# Install uv for fast dependency management (v0.11.1)
# To update: docker pull ghcr.io/astral-sh/uv:latest
#            docker inspect --format='{{index .RepoDigests 0}}' ghcr.io/astral-sh/uv:latest
COPY --from=ghcr.io/astral-sh/uv@sha256:fc93e9ecd7218e9ec8fba117af89348eef8fd2463c50c13347478769aaedd0ce /uv /usr/local/bin/uv

# Copy project files for dependency installation
COPY pyproject.toml .
COPY src/ ./src/

# Install the project and its dependencies using uv
# pysqlite3-binary (installed inline) provides SQLite >= 3.35 for ChromaDB on UBI9
RUN uv pip install --no-cache ".[tracing]" pysqlite3-binary \
    && SITE=$(python3 -c "import site; print(site.getsitepackages()[0])") \
    && printf '__import__("pysqlite3")\nimport sys\nsys.modules["sqlite3"] = sys.modules.pop("pysqlite3")\n' > "$SITE/sitecustomize.py"

# Copy the application entrypoint, playground UI, and images
COPY main.py .
COPY playground/ ./playground/
COPY images/ ./images/

# Pre-create the directory that CrewAI writes to at import time
# (crewai.utilities.paths.db_storage_path -> ~/.local/share/app/)
# Make everything group-writable (GID 0) for OpenShift arbitrary UID support
RUN mkdir -p /opt/app-root/.local/share/app \
    && chown -R 1001:0 /opt/app-root/src /opt/app-root/.local \
    && chmod -R g=u /opt/app-root/src /opt/app-root/.local

# Switch back to default non-root user
USER 1001

# Expose port 8080 (OpenShift standard)
EXPOSE 8080

# Set environment variables
ENV PORT=8080
ENV HOME=/opt/app-root
ENV PYTHONPATH=/opt/app-root/src

# Run the application — reads PORT at runtime
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT}"]
