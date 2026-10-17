FROM python:3.12-alpine

WORKDIR /app
COPY provider.py .

RUN adduser -D -u 10001 stubuser
USER stubuser

EXPOSE 8080
CMD ["python", "provider.py"]
