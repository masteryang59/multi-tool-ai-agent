FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY toolagent ./toolagent
COPY mock_services ./mock_services

RUN useradd --create-home app && mkdir data && chown app data
USER app

EXPOSE 8000
ENTRYPOINT ["python", "-m"]
CMD ["toolagent", "serve", "--host", "0.0.0.0", "--port", "8000"]
ENV DECODE_PAYLOAD=true
ENV SAVE_STATE=true
ENV DECODE_PAYLOAD=true