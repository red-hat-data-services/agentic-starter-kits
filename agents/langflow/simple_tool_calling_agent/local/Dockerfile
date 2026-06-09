FROM docker.io/langflowai/langflow:1.9.5

# Langfuse SDK 3.x requires pydantic>=2.13 for Python 3.14 compatibility.
# The upstream image ships pydantic 2.12 which breaks langfuse imports.
# See: https://github.com/langfuse/langfuse/issues/9618
#      https://github.com/langflow-ai/langflow/pull/13341
# Allow patch and minor updates in 2.x line while blocking breaking changes in 3.x
RUN pip install --no-cache-dir 'pydantic>=2.13.4,<3' 'langfuse==3.15.0'
