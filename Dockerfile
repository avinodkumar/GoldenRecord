# GoldenRecord images
#   runtime : agent API (FastAPI) and control-room UI (Streamlit); same image, different command
#   toolbox : runtime + Microsoft Fabric CLI, for building the wheel and deploying notebooks to Fabric

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    MLFLOW_DISABLE_AGENT_HINT=1 \
    GOLDENRECORD_CONFIG_DIR=/app/config \
    LAKEHOUSE_ROOT=/lakehouse
WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install ".[stack]"

COPY config ./config
COPY ui ./ui

RUN useradd --create-home --uid 1000 goldenrecord && mkdir -p /lakehouse && chown goldenrecord /lakehouse
USER goldenrecord

EXPOSE 8000 8501
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=4)" || exit 1
CMD ["uvicorn", "goldenrecord.api:app", "--host", "0.0.0.0", "--port", "8000"]


FROM runtime AS toolbox
USER root
RUN pip install ms-fabric-cli build pytest httpx
COPY fabric ./fabric
COPY deploy ./deploy
COPY tests ./tests
RUN chmod +x deploy/*.sh && chown -R goldenrecord /app
USER goldenrecord
HEALTHCHECK NONE
ENTRYPOINT ["bash"]
CMD ["deploy/deploy_fabric.sh"]
