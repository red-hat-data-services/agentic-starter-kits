# Use Red Hat UBI9 Python 3.12 image (no Docker Hub rate limits on OpenShift)
FROM registry.access.redhat.com/ubi9/python-312:latest
WORKDIR /opt/app-root/src

# Switch to root for installing dependencies
USER 0

# Install uv for fast dependency management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy project files for dependency installation
COPY pyproject.toml .
COPY src/ ./src/

# Install the project and its dependencies using uv
RUN uv pip install --no-cache .

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

# Run the application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
