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
| Idle workers / FlashBoot / scale-to-zero | `min=0`, `max=1`, `idleTimeout=120`, `flashboot=FLASHBOOT`, 1 GPU, disk 45 GB confirmed by get-endpoint. Initial 5s idle timeout caused the container to stop shortly after first job; increased to 120s to allow short bursts without standing workers. Initial startup had three worker records (two THROTTLED, one later executed) despite `max=1`; one executing worker was observed. Final scale-to-zero not yet observed |
| Network volume | `networkVolumes=[]` on endpoint, account volume list empty |
| Normal, Turbo, cold-start, editing | Turbo 512px job `ae37198f-7641-4485-a1c8-cde63a049785-u1` **COMPLETED**, base64 PNG, queue 487.564s / execution 16.256s. First normal job `de344ae0-a48d-4a4f-9bc4-433c0d53e505-u1` **FAILED** `executionTimeout exceeded` after 563.962s queue + 12.277s execution; implicit per-job deadline included queue delay. Retest normal job `ac07cfbf-246b-467f-95f5-be8e05bee38a-u2` **COMPLETED** with explicit 1,200,000ms policy: `normal_00001_.png`, queue 12.313s / execution 24.899s. Turbo reference edit `ba8dd5b5-a185-4600-9884-614f988c732a-u1` **COMPLETED**: uploaded 512px PNG, output `turbo_edit_00001_.png`, queue 0.127s / execution 17.235s. Post-idle cold start pending |
| Initial remaining credits | Unknown; available-credit balance not returned by catalog/billing reads |

## Paid runs and cost accounting

| Test | Billed duration | Estimated cost | Cumulative |
|---|---:|---:|---:|
| First Turbo 512px | 16.256s execution, 487.564s queue delay; separately billed startup unknown | $0.00312 GPU execution at $0.69/h, plus any billed startup/disk (RunPod billing reports $0 so far; lagging) | At least $0.00312 estimated |
| First normal 512px (timed out) | 12.277s execution, 563.962s queued | $0.00235 GPU execution, plus unknown startup/idle | At least $0.00547 estimated |
| Normal 512px (successful retry) | 24.899s execution, 12.313s queued | $0.00477 GPU execution + unknown startup/idle | At least $0.01024 estimated |
| Turbo one-reference edit | 17.235s execution, 0.127s queued | $0.00330 GPU execution + unknown startup/idle | At least $0.01354 estimated |

The first GPU container started at 02:18:26Z and stopped at 02:19:29Z (~63s), which bounds a simple $0.69/h whole-container GPU estimate near $0.0121 if all startup/idle seconds are billable. The eight-minute image pull occurred before its container started; billing endpoint has not yet reported this period. Do not interpret $0 returned from lagging billing as a free job.

If cumulative estimated spend approaches $3, avoid any nonessential GPU test. **Stop paid execution before $4**. Billing duration may differ from queue delay plus execution; use RunPod billing for final figures. Target < $2 total, leave at least ~$1 for user use.

## Known risks / troubleshooting

- Viggle's official ComfyUI port documents INT8/bf16 native transformer, not GGUF + unmerged LoRA. A successful import is not proof that the runtime hooks work on GGUF; read worker logs on a failed job before another GPU run.
- Official Viggle workflow with model resident and enhancer enabled peaks at 26 GB at 1248×832. This build omits the enhancer; rely on documented ComfyUI automatic offload on 24 GB and inspect actual errors before changing GPU.
- Published official base is already ~14.67 GB unpacked; baked files add ~14.9 GB. GitHub runner disk and GHCR per-layer 10 GB limit motivate runner cleanup and one file per layer. Any failed CI build should be diagnosed without starting RunPod workers.
- First cold worker may need substantial image-pull time. Only a completed real job proves the API contract, and scale-to-zero plus a subsequent cold Turbo generation prove intended operating mode.
