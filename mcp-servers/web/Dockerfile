FROM python:3.14-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY web_server.py .
USER 1000
ENV PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["python", "web_server.py"]
