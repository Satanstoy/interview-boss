FROM python:3.12-slim

ARG PYPI_MIRROR=https://mirrors.cloud.tencent.com/pypi/simple/

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --timeout 30 --retries 2 \
    -i ${PYPI_MIRROR} \
    --trusted-host $(echo ${PYPI_MIRROR} | sed 's|https://||;s|/.*||') \
    -r requirements.txt

COPY . .

# 非 root 用户：只读挂载 InterviewBoss DB（/app/data:ro），
# 可写区仅自己的 oauth-data 卷（/app/oauth-data，空卷挂载时沿用镜像目录属主）。
RUN useradd --create-home --shell /bin/false oauthuser && \
    mkdir -p /app/oauth-data && \
    chown -R oauthuser:oauthuser /app

USER oauthuser

EXPOSE 8082

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8082"]
