# Use Red Hat UBI9 Python 3.12 image (no Docker Hub rate limits on OpenShift)
# To update: docker pull registry.access.redhat.com/ubi9/python-312:latest
#            docker inspect --format='{{index .RepoDigests 0}}' registry.access.redhat.com/ubi9/python-312:latest
FROM registry.access.redhat.com/ubi9/python-312@sha256:e95978812895b9abb2bdc109b501078da2a47c8dbb9fa23758af40ed50ab6023
WORKDIR /opt/app-root/src/agents/langgraph/templates/agentic_rag

# Switch to root for installing dependencies
USER 0

# Install uv for fast dependency management (v0.11.1)
# To update: docker pull ghcr.io/astral-sh/uv:latest
#            docker inspect --format='{{index .RepoDigests 0}}' ghcr.io/astral-sh/uv:latest
COPY --from=ghcr.io/astral-sh/uv@sha256:fc93e9ecd7218e9ec8fba117af89348eef8fd2463c50c13347478769aaedd0ce /uv /usr/local/bin/uv

# Copy project files for dependency installation.
# Keep the repo-relative layout so ../../../../components/auth resolves.
COPY pyproject.toml uv.lock ./
COPY src/ ./src/
COPY components/auth/ /opt/app-root/src/components/auth/

# Install from the lockfile so builds are reproducible (--frozen fails if
# uv.lock is stale relative to pyproject.toml)
ENV UV_PROJECT_ENVIRONMENT=/opt/app-root
RUN uv sync --frozen --no-dev --extra tracing --extra auth

# Copy the application entrypoint, playground UI, data, and images
COPY main.py .
COPY playground/ ./playground/
COPY data/ ./data/
COPY images/ ./images/

# Create data directory for vector store and make everything group-writable for OpenShift
RUN mkdir -p /opt/app-root/src/agents/langgraph/templates/agentic_rag/data && \
    chown -R 1001:0 /opt/app-root/src && \
    chmod -R g=u /opt/app-root/src

# Switch back to default non-root user
USER 1001

# Expose port 8080 (OpenShift standard)
EXPOSE 8080

# Set environment variables
ENV PORT=8080
ENV HOME=/opt/app-root
ENV PYTHONPATH=/opt/app-root/src/agents/langgraph/templates/agentic_rag
ENV VECTOR_STORE_PATH=/opt/app-root/src/agents/langgraph/templates/agentic_rag/data/vector_store

# Run the application — reads PORT at runtime
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT}"]
