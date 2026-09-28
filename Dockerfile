# Published official RunPod queue worker. Pin the registry index, not an unpublished 5.11.0 tag.
FROM runpod/worker-comfyui:5.10.0-base@sha256:e9d18d3db15839ebb10c10c824109fc2956f31ef7bf21916220c008855b0d538

# The published worker bundles ComfyUI 0.34; native Qwen-Image-2.1 and Viggle need 0.37.
RUN git -C /comfyui fetch --depth 1 origin 73c9bad4d21e7addbe1d13bc92eee0f1431b017d \
    && git -C /comfyui checkout --detach 73c9bad4d21e7addbe1d13bc92eee0f1431b017d \
    && git clone https://github.com/city96/ComfyUI-GGUF.git /comfyui/custom_nodes/ComfyUI-GGUF \
    && git -C /comfyui/custom_nodes/ComfyUI-GGUF checkout --detach 6ea2651e7df66d7585f6ffee804b20e92fb38b8a
RUN uv pip install --python /opt/venv/bin/python \
      -r /comfyui/requirements.txt \
      -r /comfyui/custom_nodes/ComfyUI-GGUF/requirements.txt \
      'transformers>=4.50.3,<5' 'huggingface-hub<1' \
    && /opt/venv/bin/python -c "from urllib.request import urlopen; u='https://huggingface.co/Viggle/Qwen-Image-2.1-viggle-turbo/resolve/bb26a0f38e5fe6c124aaccc9187a87eed5d9ed13/comfyui/viggle_turbo.py'; open('/comfyui/custom_nodes/viggle_turbo.py','wb').write(urlopen(u,timeout=120).read())" \
    && cd /comfyui && timeout 300 /opt/venv/bin/python main.py --quick-test-for-ci --cpu

COPY versions.json /app/versions.json
COPY scripts/download_models.py /app/download_models.py
# Separate weight layers: avoid duplicate HF cache and keep every registry layer below 10 GB.
RUN /opt/venv/bin/python /app/download_models.py 0
RUN /opt/venv/bin/python /app/download_models.py 1
RUN /opt/venv/bin/python /app/download_models.py 2
RUN /opt/venv/bin/python /app/download_models.py 3

# Keep the official /start.sh and /handler.py. No public ComfyUI port or S3 required.
WORKDIR /
