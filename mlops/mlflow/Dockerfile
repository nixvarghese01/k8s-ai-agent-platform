# MLflow tracking server + model registry (infra/k3s/mlops/mlflow.yaml). The official image has
# no Postgres driver, so this one adds psycopg 3 (SQLAlchemy 2.1+ default) and boto3 (artifacts in SeaweedFS S3).
ARG BASE=local-ai/ml-base:dev
FROM ${BASE}
RUN pip install --no-cache-dir mlflow==3.16.1 "psycopg[binary]==3.3.6"
USER 1000
ENV PYTHONUNBUFFERED=1 HOME=/tmp
EXPOSE 5000
CMD ["mlflow", "server", "--host", "0.0.0.0", "--port", "5000"]
