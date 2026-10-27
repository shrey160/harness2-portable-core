ARG PYTHON_IMAGE=python:3.12-slim
FROM ${PYTHON_IMAGE}
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HOME=/tmp
# Built entirely from this repository's context: wheels for this project and
# its vendored harness2-cli engine, installed with their distribution
# metadata. No external checkout, source copy, or path injection is used.
COPY wheels /opt/wheels
COPY LICENSE.harness2-cli /opt/harness2-cli-LICENSE
RUN python -m pip install --no-cache-dir --no-index --no-deps /opt/wheels/*.whl \
    && rm -rf /opt/wheels
USER 1000:1000
WORKDIR /work
CMD ["python", "--version"]
