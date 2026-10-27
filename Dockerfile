ARG PYTHON_IMAGE=python:3.12-slim
FROM ${PYTHON_IMAGE}
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HOME=/tmp
WORKDIR /opt/h2portable
# Build from a prepared context containing the pinned CLI sources, with no .git/.venv.
COPY upstream-cli/harness2 /opt/harness2-cli/harness2
COPY upstream-cli/LICENSE /opt/harness2-cli/LICENSE
COPY wheels /opt/wheels
RUN python -m pip install --no-cache-dir --no-index --no-deps /opt/wheels/*.whl
COPY src /opt/h2portable/src
ENV PYTHONPATH=/opt/h2portable/src:/opt/harness2-cli
USER 1000:1000
WORKDIR /work
CMD ["python", "--version"]
