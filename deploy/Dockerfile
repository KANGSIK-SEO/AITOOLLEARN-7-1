# Ubuntu 24.04에서 Vercel CLI로 배포하기 위한 환경 (배포 전용, 앱 실행 이미지는 루트 Dockerfile)
FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
    && apt-get install -y --no-install-recommends nodejs npm ca-certificates git \
    && rm -rf /var/lib/apt/lists/* \
    && npm install -g vercel
WORKDIR /app
