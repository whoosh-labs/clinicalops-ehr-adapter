# clinicalops-ehr-adapter (Clinical DataOps Hub): Streamlit UI that turns raw EHR exports
# (AthenaOne, ECW, IMS Meditab, ModuleMD, EPIC, ModMed face sheets) into VOB import CSVs.
# Built by Jenkins (clinical-ops/clinicalops-ehr-adapter) as ragaai/clinicalops-ehr-adapter:<tag>.
# Served on 8000 to match the Helm chart's Service/containerPort.
# Streamlit's health endpoint is /_stcore/health.

FROM python:3.11-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# poppler-utils provides `pdftotext`, which the face sheet parser shells out to (see packages.txt)
RUN apt-get update \
    && apt-get install -y --no-install-recommends poppler-utils \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --gid 1000 app \
    && useradd --uid 1000 --gid app --shell /bin/bash --create-home app

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY --chown=app:app .streamlit/config.toml /app/.streamlit/config.toml
COPY --chown=app:app app.py facesheet_to_csv.py /app/

USER app

# Server settings for running in a pod (Streamlit reads STREAMLIT_* env vars).
ENV STREAMLIT_SERVER_PORT=8000 \
    STREAMLIT_SERVER_ADDRESS=0.0.0.0 \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_SERVER_FILE_WATCHER_TYPE=none \
    STREAMLIT_SERVER_RUN_ON_SAVE=false \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false \
    STREAMLIT_CLIENT_TOOLBAR_MODE=viewer \
    LOG_LEVEL=INFO \
    EHR_ADAPTER_MAX_FILE_MB=25

EXPOSE 8000

# Kubernetes probes cover health in the cluster; this is for local `docker run`.
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/_stcore/health', timeout=4).status == 200 else 1)"

# LOG_LEVEL and EHR_ADAPTER_MAX_FILE_MB come from the Helm env list (ClinicalopsEhrAdapter).
CMD ["sh", "-c", "exec streamlit run app.py --logger.level=$(echo \"$LOG_LEVEL\" | tr '[:upper:]' '[:lower:]') --server.maxUploadSize=\"$EHR_ADAPTER_MAX_FILE_MB\""]
