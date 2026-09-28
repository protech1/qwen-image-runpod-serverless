# Deployment log

## Decisions (2026-09-27)

- RunPod account read: zero existing endpoints, zero network volumes. No resources were deleted or changed.
- Target pool `AMPERE_24`, one RTX 3090 (24 GB, serverless **$0.69/h** from live GPU catalog, community availability LOW). This avoids the RTX 4090 premium `ADA_24` pool ($1.10/h). Model weights: 4,189,343,904 B Q4 denoiser + 9,350,798,360 B INT8 encoder + 675,509,688 B VAE + 679,604,800 B r128 LoRA = **14,895,256,752 bytes**. Peak VRAM is unknown; ComfyUI offloading and ~1 MP input are required to test 24 GB viability.
- Base `runpod/worker-comfyui:5.10.0-base` registry digest `sha256:e9d18d3db15839ebb10c10c824109fc2956f31ef7bf21916220c008855b0d538` (official GitHub's newer 5.11.0 release has no confirmed published base image); upgrade ComfyUI 0.34 to Qwen-supported 0.37.0 during build.
- Prefer Abiray Q4_K_M (metadata + documented ComfyUI workflows) over Unsloth Q4_K_M (reputable but missing architecture metadata without an extra patch). Use official Comfy-Org quantized INT8 encoder instead of unverified GGUF VL-encoder/mmproj pairing. Exact revisions and SHA256 in `versions.json`.
- Bake weights into image rather than incur recurring network-volume charges. Use official worker unchanged as server-side handler; simple JSON translation runs locally. Viggle's runtime unmerged LoRA and six-node schedule are mandatory; no prompt enhancement or rewriting. Commercial use requires separate Qwen licensing.
- No Docker installed on local Apple Silicon workstation; GitHub Actions manual `linux/amd64` GHCR build is the free remote-builder route. GitHub CLI authentication was authorized by account holder. No RunPod GPU invoked yet.

## Build and deployment state

| Item | State |
|---|---|
| GitHub repository | In progress |
| Linux amd64 build | Not yet run |
| Final image tag/digest/size | Not yet measured |
| Endpoint name / ID | Not yet created |
| Selected pool / GPU | Target `AMPERE_24` / RTX 3090; not yet deployed |
| Qwen model and Viggle revisions | See `versions.json` |
| Idle workers / FlashBoot / scale-to-zero | Not yet tested |
| Normal, Turbo, cold-start, editing | Not yet tested |
| Initial remaining credits | Unknown; account credits balance not returned by current catalog reads |

## Paid runs and cost accounting

| Test | Billed duration | Estimated cost | Cumulative |
|---|---:|---:|---:|
| No paid tests yet | 0s | $0 | $0 |

If cumulative estimated spend approaches $3, avoid any nonessential GPU test. **Stop paid execution before $4**. Billing duration may differ from queue delay plus execution; use RunPod billing for final figures. Target < $2 total, leave at least ~$1 for user use.

## Known risks / troubleshooting

- Viggle's official ComfyUI port documents INT8/bf16 native transformer, not GGUF + unmerged LoRA. A successful import is not proof that the runtime hooks work on GGUF; read worker logs on a failed job before another GPU run.
- Official Viggle workflow with model resident and enhancer enabled peaks at 26 GB at 1248×832. This build omits the enhancer; rely on documented ComfyUI automatic offload on 24 GB and inspect actual errors before changing GPU.
- Published official base is already ~14.67 GB unpacked; baked files add ~14.9 GB. GitHub runner disk and GHCR per-layer 10 GB limit motivate runner cleanup and one file per layer. Any failed CI build should be diagnosed without starting RunPod workers.
- First cold worker may need substantial image-pull time. Only a completed real job proves the API contract, and scale-to-zero plus a subsequent cold Turbo generation prove intended operating mode.
