# Dagster webserver + daemon + the triage pipeline code (infra/k3s/mlops/dagster.yaml).
FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# GIT_PYTHON_REFRESH: there is no git in the image; stops MLflow warning about it on every run
ENV DAGSTER_HOME=/opt/dagster/home PYTHONUNBUFFERED=1 HOME=/tmp GIT_PYTHON_REFRESH=quiet
RUN mkdir -p $DAGSTER_HOME && chown 1000 $DAGSTER_HOME
COPY dagster.yaml $DAGSTER_HOME/
COPY workspace.yaml ./
COPY triage/ triage/
USER 1000
EXPOSE 3000
CMD ["dagster-webserver", "-h", "0.0.0.0", "-p", "3000", "-w", "workspace.yaml"]
