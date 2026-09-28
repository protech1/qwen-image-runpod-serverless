# Deployment log

## Decisions (2026-09-27)

- RunPod account read: zero existing endpoints, zero network volumes. No resources were deleted or changed.
- Target pool `AMPERE_24`, one RTX 3090 (24 GB, serverless **$0.69/h** from live GPU catalog, community availability LOW). This avoids the RTX 4090 premium `ADA_24` pool ($1.10/h). Model weights: 4,189,343,904 B Q4 denoiser + 9,350,798,360 B INT8 encoder + 675,509,688 B VAE + 679,604,800 B r128 LoRA = **14,895,256,752 bytes**. Peak VRAM is unknown; ComfyUI offloading and ~1 MP input are required to test 24 GB viability.
- Base `runpod/worker-comfyui:5.10.0-base` registry digest `sha256:e9d18d3db15839ebb10c10c824109fc2956f31ef7bf21916220c008855b0d538` (official GitHub's newer 5.11.0 release has no confirmed published base image); upgrade ComfyUI 0.34 to Qwen-supported 0.37.0 during build.
- Prefer Abiray Q4_K_M (metadata + documented ComfyUI workflows) over Unsloth Q4_K_M (reputable but missing architecture metadata without an extra patch). Use official Comfy-Org quantized INT8 encoder instead of unverified GGUF VL-encoder/mmproj pairing. Exact revisions and SHA256 in `versions.json`.
- Bake weights into image rather than incur recurring network-volume charges. Use official worker unchanged as server-side handler; simple JSON translation runs locally. Viggle's runtime unmerged LoRA and six-node schedule are mandatory; no prompt enhancement or rewriting. Commercial use requires separate Qwen licensing.
- No Docker installed on local Apple Silicon workstation; GitHub Actions manual `linux/amd64` GHCR build succeeded on GitHub-hosted Ubuntu 24.04 in 20m55s ([run 36366624691](https://github.com/protech1/qwen-image-runpod-serverless/actions/runs/36366624691)). All four weight bytes and SHA256 hashes passed in build logs; ComfyUI CPU import quick-test passed. GitHub CLI authentication was authorized by account holder.

## Build and deployment state

| Item | State |
|---|---|
| GitHub repository | https://github.com/protech1/qwen-image-runpod-serverless |
| Linux amd64 build | Successful, commit `295592f5d1e7d6940d24afcbf37c3aab6a98a361`, 20m55s |
| Final image tag/digest/size | `ghcr.io/protech1/qwen-image-runpod-serverless:0.1.0`, digest `sha256:90fdfc38cbccda7f63a12bbc3c8a356caee05479d4e8166dcf836b41a6ccde4b`, **28,445,445,893 compressed layer bytes** from public OCI manifest (35 layers, Linux amd64); unpacked size not yet measured |
| Endpoint name / ID | `qwen-image-2-1-viggle-turbo`, `w62793qc98rn7x`, Queue |
| Selected pool / GPU | `AMPERE_24`, RTX 3090 or RTX A5000 (both 24 GB, both $0.69/h serverless); RTX L4/MIG excluded. Initial RTX 3090 LOW stock, A5000 HIGH stock; first job ran on RTX 3090 at `EU-CZ-1` |
| Qwen model and Viggle revisions | See `versions.json` |
| Idle workers / FlashBoot / scale-to-zero | Final `min=0`, `max=1`, `idleTimeout=5`, `flashboot=FLASHBOOT`, 1 GPU, 45 GB ephemeral disk confirmed by get-endpoint. A brief 120s timeout during burst tests was restored to 5s afterward. System logs showed prior container stopped at 02:38:12Z and removed at 02:38:17Z; endpoint health reported 0 RUNNING workers (a THROTTLED worker record remained). Later Turbo job started a fresh container on worker `dw1rd5honlms17` after loading cached image, then completed. RunPod temporarily listed up to three worker records including THROTTLED during startup despite configured `max=1`; only one executing worker observed |
| Network volume | `networkVolumes=[]` on endpoint, account volume list empty |
| Normal, Turbo, cold-start, editing | First Turbo 512px `ae37198f-7641-4485-a1c8-cde63a049785-u1` **COMPLETED** (487.564s queue / 16.256s execution, base64 PNG). First normal `de344ae0-a48d-4a4f-9bc4-433c0d53e505-u1` **FAILED** `executionTimeout exceeded` after 563.962s queue + 12.277s execution; explicit 1,200,000ms per-job policy fixed the deadline. Normal retry `ac07cfbf-246b-467f-95f5-be8e05bee38a-u2` **COMPLETED** (12.313s queue / 24.899s execution, base64 PNG). Turbo one-reference edit `ba8dd5b5-a185-4600-9884-614f988c732a-u1` **COMPLETED** (0.127s queue / 17.235s execution, uploaded 512px PNG and received base64 PNG). Post-idle cold Turbo `88c8d0bf-dd6c-4d32-b838-853d6e6c57f6-u1` **COMPLETED** (610.659s queue / 15.017s execution, base64 PNG). Normal editing and local CLI authenticated submission were not exercised |
| Initial remaining credits | Unknown; available-credit balance not returned by catalog/billing reads |

## Paid runs and cost accounting

| Test | Reported execution / queue duration | Execution-only estimate at $0.69/h | Running estimate |
|---|---:|---:|---:|
| First Turbo 512px | 16.256s / 487.564s | $0.00312 | $0.00312 |
| First normal 512px (timed out) | 12.277s / 563.962s | $0.00235 | $0.00547 |
| Normal 512px (successful retry) | 24.899s / 12.313s | $0.00477 | $0.01024 |
| Turbo one-reference edit | 17.235s / 0.127s | $0.00330 | $0.01354 |
| Post-idle cold Turbo 512px | 15.017s / 610.659s | $0.00288 | $0.01642 |

**Actual RunPod Serverless billing** for this endpoint at the latest read: GPU **$0.05738480819854885**, disk **$0.0010416668374091387**, fee $0, **total $0.05842647503595799** for the current day. This is a point-in-time figure and may lag the final post-idle job. The execution-only estimate is not the bill: startup and warm-idle worker time add charges. No network volume exists, so no recurring network-volume cost. The first container ran from 02:18:26Z to 02:19:29Z; the initial 28.45 GB image pull drove ~8 minutes of queue delay, and a later cache hydration took ~10 minutes. Budget remains well under $2 and the hard $4 cap at the latest billing read.

If cumulative estimated spend approaches $3, avoid any nonessential GPU test. **Stop paid execution before $4**. Billing duration may differ from queue delay plus execution; use RunPod billing for final figures. Target < $2 total, leave at least ~$1 for user use.

## Known risks / troubleshooting

- Viggle's official ComfyUI port documents INT8/bf16 native transformer, not GGUF + unmerged LoRA; the live 512px Turbo and edit jobs here completed with the GGUF Q4 denoiser and unmerged LoRA. Other resolutions and extended prompts are not proven by these jobs.
- Official Viggle workflow with model resident and enhancer enabled peaks at 26 GB at 1248×832. This build omits the enhancer; rely on documented ComfyUI automatic offload on 24 GB and inspect actual errors before changing GPU.
- Published official base is already ~14.67 GB unpacked; baked files add ~14.9 GB. GitHub runner disk and GHCR per-layer 10 GB limit motivate runner cleanup and one file per layer. Any failed CI build should be diagnosed without starting RunPod workers.
- A cold worker may need substantial image-pull/cache hydration time. Set `policy.executionTimeout=1200000` per job and allow at least 1,500s local polling. The initial normal job used the implicit deadline and expired immediately after its long queue delay; the explicit-policy retry succeeded.
