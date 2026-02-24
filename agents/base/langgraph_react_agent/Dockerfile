# Use Python 3.12 slim image as base
FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Create a non-privileged user for OpenShift
# UID 1001 is commonly used in OpenShift deployments
RUN groupadd -r appuser && useradd -r -u 1001 -g appuser appuser

# Copy requirements file first for better layer caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy the application code
COPY main.py .
COPY src/ ./src/

# Change ownership of the app directory to the non-privileged user
RUN chown -R appuser:appuser /app

# Switch to non-privileged user
USER appuser

# Expose port 8080 (OpenShift standard)
EXPOSE 8080

# Set environment variables
ENV PORT=8080
ENV PYTHONPATH=/app:/app/src

# Run the application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]

