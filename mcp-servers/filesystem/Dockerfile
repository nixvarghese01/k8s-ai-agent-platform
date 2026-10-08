FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY server.py .
# Same uid as the WSL user that owns the files under /mnt/<drive>
USER 1000
ENV PYTHONUNBUFFERED=1 FILES_ROOT=/data
EXPOSE 8000
CMD ["python", "server.py"]
