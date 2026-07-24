FROM debian:bookworm-slim AS system

# System toolchain: Verilator, Yosys, Z3, Python, git
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    python3 python3-pip python3-venv python3-click \
    verilator yosys z3 \
    build-essential git curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# SymbiYosys (formal)
RUN git clone --depth 1 https://github.com/YosysHQ/sby.git /tmp/sby && \
    cd /tmp/sby && make install && rm -rf /tmp/sby && \
    sed -i '1s|.*|#!/usr/bin/python3|' /usr/local/bin/sby

FROM system AS app
WORKDIR /app

# Python deps
COPY requirements.txt /app/
RUN pip3 install --break-system-packages --no-cache-dir -r /app/requirements.txt

# App code
COPY . /app/

# Create storage dir (for local storage mode)
RUN mkdir -p /app/storage
VOLUME /app/storage

ENV PYTHONUNBUFFERED=1
EXPOSE 8001
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8001"]
