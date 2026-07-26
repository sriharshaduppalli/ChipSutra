FROM debian:bookworm-slim AS system

# Prefer OSS CAD Suite (Yosys ≥ 0.35 + SBY + Z3) when available; fall back to apt packages.
ARG OSS_CAD_SUITE_URL=https://github.com/YosysHQ/oss-cad-suite-build/releases/download/2024-12-20/oss-cad-suite-linux-x64-241220.tgz
ARG USE_OSS_CAD_SUITE=1

RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    python3 python3-pip python3-venv python3-click \
    build-essential git curl ca-certificates \
    verilator \
    && rm -rf /var/lib/apt/lists/*

RUN if [ "$USE_OSS_CAD_SUITE" = "1" ]; then \
      mkdir -p /opt && \
      curl -L --fail -o /tmp/oss-cad-suite.tgz "$OSS_CAD_SUITE_URL" && \
      tar -xzf /tmp/oss-cad-suite.tgz -C /opt && \
      rm /tmp/oss-cad-suite.tgz && \
      ln -sf /opt/oss-cad-suite/bin/* /usr/local/bin/ || true; \
    else \
      apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends yosys z3 && \
      git clone --depth 1 https://github.com/YosysHQ/sby.git /tmp/sby && \
      cd /tmp/sby && make install && rm -rf /tmp/sby && \
      sed -i '1s|.*|#!/usr/bin/python3|' /usr/local/bin/sby && \
      rm -rf /var/lib/apt/lists/*; \
    fi

ENV PATH="/opt/oss-cad-suite/bin:${PATH}"

FROM system AS app
WORKDIR /app

# Python deps — Community Edition (public PyPI; no Emergent account required)
COPY requirements-oss.txt /app/
RUN pip3 install --break-system-packages --no-cache-dir -r /app/requirements-oss.txt

# App code
COPY . /app/

# Create storage dir (for local storage mode)
RUN mkdir -p /app/storage
VOLUME /app/storage

ENV PYTHONUNBUFFERED=1
EXPOSE 8001
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8001"]
