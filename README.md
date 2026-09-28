# Qwen-Image-2.1 on RunPod Serverless

A scale-to-zero, single-worker ComfyUI queue endpoint with Qwen-Image-2.1 Q4_K_M and optional **Viggle Turbo v0.2.1**. One set of base model files serves both modes. The official RunPod worker returns base64 PNG images in `output.images`; the local Python client accepts simple JSON and translates it into ComfyUI API workflows. There is no exposed public ComfyUI admin port, network volume, S3 dependency or always-on process.

> **License:** Qwen-Image-2.1 and Viggle weights are under the [Qwen Research License](https://huggingface.co/Qwen/Qwen-Image-2.1/blob/main/LICENSE), for non-commercial research/evaluation. Commercial usage needs a separate license from the licensor. Do not assume the GGUF repackaging changes the model's license.

## Model inventory

Exact revisions, hashes, sizes and destinations are in [`versions.json`](versions.json). The Docker build verifies both SHA256 and byte count before accepting each download.

| Asset | Repository / pinned revision | File |
|---|---|---|
| Q4_K_M base transformer | [Abiray/Qwen-Image-2.1-GGUF](https://huggingface.co/Abiray/Qwen-Image-2.1-GGUF/tree/c9dd12108f53974cd1e0abd708df042d6df0ca8d) `c9dd1210` | `qwen_image_2.1_Q4_K_M.gguf` |
| INT8 Qwen3-VL encoder | [Comfy-Org/Qwen-Image-2.1](https://huggingface.co/Comfy-Org/Qwen-Image-2.1/tree/9a44dbdb47cefd046be9c0a13476192f34c8db8e) `9a44dbdb` | `qwen3vl_8b_int8_convrot.safetensors` |
| VAE | Same Comfy-Org revision | `qwen_image_2.1_vae_bf16.safetensors` |
| Turbo LoRA | [Viggle/Qwen-Image-2.1-viggle-turbo](https://huggingface.co/Viggle/Qwen-Image-2.1-viggle-turbo/tree/bb26a0f38e5fe6c124aaccc9187a87eed5d9ed13) `bb26a0f3` | `Qwen-Image-2.1-viggle-turbo-v0.2.1-6step-lora-r128.safetensors` |

Upstream [Qwen/Qwen-Image-2.1](https://huggingface.co/Qwen/Qwen-Image-2.1) revision `790c92633540aa0cb11d9abf19eb46d861714758` is the unquantized source family, not an additional downloaded checkpoint. The [official ComfyUI Qwen guide](https://docs.comfy.org/tutorials/image/qwen/qwen-image-2-1) describes native text encoding and VAE. The [Abiray repository](https://huggingface.co/Abiray/Qwen-Image-2.1-GGUF) publishes ComfyUI GGUF text/edit examples; unlike the Unsloth GGUF, this file carries the GGUF architecture metadata expected by the pinned loader. The standalone Qwen3-VL Q4 GGUF and mmproj are *not* drop-in ComfyUI text encoders; INT8 safetensors is the documented reliable choice.

## Architecture and versions

`client → https://api.runpod.ai/v2/<id>/run → official worker-comfyui → ComfyUI 0.37.0 + city96/ComfyUI-GGUF → Qwen transformer + INT8 Qwen3-VL + VAE → optional Viggle r128 LoRA → base64 image`. The base is the **published** [`runpod/worker-comfyui:5.10.0-base`](https://hub.docker.com/r/runpod/worker-comfyui/tags) image pinned to the manifest digest in `versions.json`; the newer GitHub 5.11.0 release had no published Docker Hub base tag when this image was prepared. ComfyUI commit `73c9bad4d21e7addbe1d13bc92eee0f1431b017d`, [city96/ComfyUI-GGUF](https://github.com/city96/ComfyUI-GGUF) commit `6ea2651e7df66d7585f6ffee804b20e92fb38b8a`, Viggle custom nodes from the pinned HF revision. The Dockerfile keeps `/start.sh` and `/handler.py` from RunPod's worker.

Normal mode uses CFG 1, Euler/simple, 25 passes. Turbo uses Viggle's **unmerged** `ViggleTurboLora` at strength 1, `BasicGuider` (no CFG), Euler and its latent-aware `ViggleTurboSigmas` with raw nodes `1.0, 0.9375, 0.875, 0.75, 0.5, 0.25` plus terminal zero. This is not six ordinary Euler/simple steps. We disable the optional prompt enhancer: model-facing text is precisely user text (apart from JSON escaping). The app has no blacklist, classifier, content-filter service, censorship negative prompt or safety rewrite; RunPod's own policies and model behavior remain in effect. No additional hidden system prompt.

### Build and publish

GitHub Actions `Build and publish amd64 worker` is **manual only** (`workflow_dispatch`) and pushes `ghcr.io/protech1/qwen-image-runpod-serverless:0.1.0` for `linux/amd64`. Its `GITHUB_TOKEN` has package-write scope; no registry secrets are committed. For a local Linux/amd64 Docker builder instead:

```sh
docker build --platform linux/amd64 -t ghcr.io/protech1/qwen-image-runpod-serverless:0.1.0 .
```

Downloads occur at build time; no Hugging Face token was needed for the selected public files. Keep GHCR package public for unauthenticated RunPod pulls (or configure a private registry credential). Expect a large image: the official base is already ~14.67 GB unpacked and the four model assets total ~14.9 GB. Do not mistake registry transfer size for unpacked container disk. The published amd64 digest and final image size must be recorded in [`DEPLOYMENT_NOTES.md`](DEPLOYMENT_NOTES.md) after the build.

### RunPod configuration

Queue endpoint, image tag/digest from the successful build, NVIDIA `AMPERE_24` pool (RTX 3090 if pinned), one GPU, workers min **0**, max **1**, idle timeout **5s**, `flashboot=FLASHBOOT` if supported, no network volume, no S3 env, no public port. Allow an adequately sized ephemeral container disk (at least 45 GB for the unpacked CUDA base and models). The RTX 3090 was listed at **$0.69/hour serverless** during preparation; verify live pricing before deployment. No background services or other recurring RunPod resources are required. A queue endpoint normally requires an API key; do not share it.

To delete: RunPod Console → Serverless → select this endpoint → Delete; deletion is permanent. Scaling min 0 eliminates intentionally standing GPU cost but does not delete the endpoint. Avoid raising max >1 or adding a paid network volume without an explicit cost decision. Large baked images can increase cold pull time; FlashBoot and host cache availability affect it.

## Request and CLI

Set `RUNPOD_API_KEY` and `RUNPOD_ENDPOINT_ID` in your shell (never commit `.env`). Use Python 3.10+ and standard library only:

```sh
python scripts/generate.py --prompt 'a cat sitting on a windowsill' --turbo --width 1024 --height 1024
python scripts/generate.py --prompt 'a red ceramic mug on a white table' --no-turbo --seed 12345
```

Experimental one-reference editing (normal or Turbo uses the same base weights):

```sh
python scripts/generate.py --prompt 'change the shirt to blue' --image ./reference.png --turbo
```

The client sends a base64 image through the official worker's `input.images` field. Edit output size derives from the reference (the Qwen text encoder uses a 1024-pixel resolution target); explicit nondefault `--width` and `--height` are rejected rather than silently ignored. References must be PNG/JPEG/WebP and fit the `/run` payload limit. Editing has its own normal and Turbo workflow; live editing proof is recorded separately in the deployment notes.

Results go under `outputs/` and the CLI prints queue/execution timing and an approximate charge based on the configured hourly price. The default is Turbo. `scripts/prepare_request.py` converts a simple request such as `examples/request-normal.json` or `examples/request-turbo.json` into the official worker shape `{ "input": { "workflow": {...}, "images": [...] } }` so clients need not edit node IDs. `scripts/test_endpoint.py` provides static validation and optional endpoint exercise. RunPod's direct HTTP API always accepts a workflow; the simple `{prompt,width,height,seed,turbo}` shape is **client-side**, not a server-side JSON endpoint. A direct curl must POST the generated request body:

```sh
python scripts/prepare_request.py --prompt 'a red ceramic mug' --turbo > /tmp/qwen-job.json
curl -H "Authorization: Bearer $RUNPOD_API_KEY" -H 'Content-Type: application/json' \
  -d @/tmp/qwen-job.json "https://api.runpod.ai/v2/$RUNPOD_ENDPOINT_ID/run"
```

Poll `GET https://api.runpod.ai/v2/$RUNPOD_ENDPOINT_ID/status/<job-id>` until `COMPLETED`. Read `output.images[0].data` (base64), not the old pre-v5 `output.message` field. The CLI handles submission/polling/PNG decoding and technical failures. Run `python scripts/prepare_request.py examples/request-turbo.json` to prepare a saved example, or `python scripts/test_endpoint.py` for offline validation without a paid job.

## Limits and maintenance

The official Viggle ComfyUI port was tested with native INT8 model files, not with a GGUF Q4 transformer plus its unmerged LoRA. GGUF patcher hooks are structurally plausible but **inference compatibility must be proven by a live job**; static checks and image builds cannot establish it. Viggle reports ~26 GB resident peak with INT8 transformer/encoder and prompt enhancer at 1248×832, so a 24 GB card requires offloading and modest resolutions. Editing with reference images is supported only if corresponding edit workflows and a successful live edit test are present; do not claim otherwise. Very small text and complex identity edits are weaker in Turbo. Keep resolution conservative until GPU memory behavior is observed. RunPod job request size limits make large base64 reference images impractical.

To update Qwen/Viggle: inspect current source model card, license, actual filenames, node input schemas and schedule first; pin new revision + expected SHA256/byte count in `versions.json`, update workflows if necessary, rebuild amd64 manually under a **new tag**, validate CPU node imports, then deploy that digest and make one budgeted job. Never stack a full Viggle Turbo student checkpoint with the Viggle LoRA. See [`DEPLOYMENT_NOTES.md`](DEPLOYMENT_NOTES.md) for measured timings, billed costs, build issues and exact deployment state.
