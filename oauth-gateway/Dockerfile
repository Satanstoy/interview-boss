FROM python:3.12-slim

ARG PYPI_MIRROR=https://mirrors.cloud.tencent.com/pypi/simple/

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --timeout 30 --retries 2 \
    -i ${PYPI_MIRROR} \
    --trusted-host $(echo ${PYPI_MIRROR} | sed 's|https://||;s|/.*||') \
    -r requirements.txt

COPY . .

EXPOSE 8082

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8082"]
