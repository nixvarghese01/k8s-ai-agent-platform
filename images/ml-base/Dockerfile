# Shared base for the ML images (mlflow, pipelines, serving): the heavy libraries they all use,
# installed once, so k3s and GHCR store these layers once instead of three times (README §7).
# Pins match what the services resolved to; their own requirements list them too, so pip finds
# them satisfied and adds only what each service needs on top.
FROM python:3.13-slim
COPY requirements.txt /tmp/ml-base-requirements.txt
RUN pip install --no-cache-dir -r /tmp/ml-base-requirements.txt && rm /tmp/ml-base-requirements.txt
# GIT_PYTHON_REFRESH: no git in the images; stops MLflow warning about it on every run
ENV PYTHONUNBUFFERED=1 GIT_PYTHON_REFRESH=quiet HOME=/tmp
