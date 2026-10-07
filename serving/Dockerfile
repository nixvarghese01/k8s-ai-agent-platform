# BentoML service for the message-triage model (infra/k3s/mlops/serving.yaml, README §6.15).
FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY service.py .
USER 1000
# BentoML keeps its home (models store, tmp) under BENTOML_HOME; /tmp is an emptyDir in k3s
ENV PYTHONUNBUFFERED=1 HOME=/tmp BENTOML_HOME=/tmp/bentoml GIT_PYTHON_REFRESH=quiet \
    BENTOML_DO_NOT_TRACK=true
EXPOSE 3000
CMD ["bentoml", "serve", "service:MessageTriage", "--host", "0.0.0.0", "--port", "3000"]
