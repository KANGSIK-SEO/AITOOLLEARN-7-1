# Ubuntu 24.04(Linux)에서 앱을 실행·테스트하기 위한 환경
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive PYTHONUNBUFFERED=1
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-venv python3-pip ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements-dev.txt requirements.txt ./
RUN python3 -m venv /opt/venv && /opt/venv/bin/pip install --no-cache-dir -r requirements-dev.txt
ENV PATH="/opt/venv/bin:$PATH"

COPY . .
EXPOSE 8000
# 환경 변수(UPSTAGE_API_KEY, SECRET_KEY 등)는 --env-file 로 주입한다. 이미지에 .env를 넣지 않는다.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
