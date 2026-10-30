# ─────────────────────────────────────────────────────────────────────────────
# Dockerfile — Jetson Orin Nano (JetPack 6 / L4T r36)
# Base: dustynv/l4t-pytorch (PyTorch + CUDA + TensorRT for ARM64)
#
# Check your L4T version: cat /etc/nv_tegra_release
# Full tag list: https://hub.docker.com/r/dustynv/l4t-pytorch/tags
# ─────────────────────────────────────────────────────────────────────────────
ARG L4T_TAG=r36.4.0
FROM dustynv/l4t-pytorch:${L4T_TAG}

# ── System deps ──────────────────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        wget \
        curl \
        git \
        python3-pip \
        python3-opencv \
        libopencv-dev \
        v4l-utils \
        libv4l-dev \
    && rm -rf /var/lib/apt/lists/*

RUN python3 -m pip install --upgrade pip

# ── Python deps ───────────────────────────────────────────────────────────────
COPY requirements.txt /tmp/requirements.txt

# CRITICAL FIX: Explicitly route standard packages to PyPI and Jetson-specific wheels 
# to the webredirect mirror. Do not allow pip to overwrite the base image's PyTorch.
# Route standard packages to PyPI and Jetson-specific wheels to the new official mirror
RUN pip3 install --no-cache-dir \
    --index-url https://pypi.org/simple \
    --extra-index-url https://pypi.jetson-ai-lab.io/jp6/cu126 \
    --trusted-host pypi.org \
    --trusted-host pypi.jetson-ai-lab.io \
    -r /tmp/requirements.txt

# ── MediaMTX (ARM64) ─────────────────────────────────────────────────────────
ARG MEDIAMTX_VERSION=v1.16.1
WORKDIR /opt/mediamtx
RUN wget -q \
    https://github.com/bluenviron/mediamtx/releases/download/${MEDIAMTX_VERSION}/mediamtx_${MEDIAMTX_VERSION}_linux_arm64.tar.gz \
    -O mediamtx.tar.gz \
    && tar -xzf mediamtx.tar.gz \
    && rm mediamtx.tar.gz

# ── App ───────────────────────────────────────────────────────────────────────
WORKDIR /app

COPY mediamtx.yml       /opt/mediamtx/mediamtx.yml
COPY entrypoint.sh      /app/entrypoint.sh
COPY stream_mgr.py      /app/stream_mgr.py
COPY pipeline_worker.py /app/pipeline_worker.py
COPY udp_listener.py    /app/udp_listener.py
COPY udp_cmd_server.py  /app/udp_cmd_server.py
COPY model_base.py      /app/model_base.py
COPY plugins/           /app/plugins/

RUN chmod +x /app/entrypoint.sh \
    && ln -s /app/stream_mgr.py /usr/local/bin/stream-mgr \
    && chmod +x /usr/local/bin/stream-mgr

RUN mkdir -p /app/models /app/logs

VOLUME ["/app/logs", "/app/models"]

# 8554  RTSP | 9997 MediaMTX API | 9998 metrics | 9000 UDP MPEG-TS | 9100 UDP JSON
EXPOSE 8554 9997 9998 9000/udp 9100/udp 9200/udp

# Health = MediaMTX API responds AND "main" is a ready publisher.
# Deliberately does NOT just check `pgrep ffmpeg` - that's precisely the
# check that let the reported failure mode go undetected for 30-60min.
HEALTHCHECK --interval=15s --timeout=5s --start-period=45s --retries=3 \
    CMD curl -fsS http://127.0.0.1:9997/v3/paths/get/main 2>/dev/null | grep -q '"ready":true' || exit 1

ENTRYPOINT ["/app/entrypoint.sh"]