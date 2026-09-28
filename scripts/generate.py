#!/usr/bin/env python3
"""Submit a plain image request to a RunPod worker-comfyui endpoint.

Examples:
  python scripts/generate.py --prompt 'a red kite over water' --dry-run
  python scripts/generate.py --request examples/request-normal.json --dry-run
  RUNPOD_API_KEY=... RUNPOD_ENDPOINT_ID=... python scripts/generate.py --prompt 'a red kite'
"""

import argparse
import base64
import binascii
import json
import os
from pathlib import Path
import re
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from prepare_request import RequestError, load_plain_request, prepare_request

TERMINAL = {"COMPLETED", "FAILED", "CANCELLED", "TIMED_OUT"}
GPU_DOLLARS_PER_HOUR = 0.69


class JobError(Exception):
    """Serverless job failed or returned an invalid response."""


def _api_request(url, key, payload=None):
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(url, data=body, headers={
        "Authorization": f"Bearer {key}", "Content-Type": "application/json"
    }, method="POST" if body is not None else "GET")
    try:
        with urlopen(request, timeout=45) as response:
            result = json.load(response)
    except HTTPError as exc:
        # Do not log request or server response: either can contain credentials or image bytes.
        raise JobError(f"RunPod HTTP {exc.code} during {request.get_method()}") from exc
    except (URLError, TimeoutError, OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise JobError(f"RunPod request failed ({type(exc).__name__})") from exc
    if not isinstance(result, dict):
        raise JobError("RunPod returned a non-object JSON response")
    return result


def _job_id(result):
    job_id = result.get("id")
    if not isinstance(job_id, str) or not re.fullmatch(r"[\w-]{1,128}", job_id, re.ASCII):
        raise JobError("RunPod did not return a valid job ID")
    return job_id


def submit_and_poll(payload, key, endpoint_id, *, poll_interval=5, max_wait=1500):
    if not key:
        raise JobError("RUNPOD_API_KEY is required for a live job")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", endpoint_id or ""):
        raise JobError("RUNPOD_ENDPOINT_ID must be a valid endpoint ID")
    if poll_interval <= 0 or max_wait <= 0:
        raise JobError("poll_interval and max_wait must be positive")
    base = f"https://api.runpod.ai/v2/{endpoint_id}"
    started = time.monotonic()
    result = _api_request(base + "/run", key, payload)
    job_id = _job_id(result)
    status = result.get("status")
    while status not in TERMINAL:
        remaining = max_wait - (time.monotonic() - started)
        if remaining <= 0:
            raise JobError(f"Job {job_id} exceeded {max_wait:g}s polling limit; still {status}")
        time.sleep(min(poll_interval, remaining))
        result = _api_request(base + f"/status/{job_id}", key)
        status = result.get("status")
    if status != "COMPLETED":
        raise JobError(f"Job {job_id} ended with {status}; inspect endpoint worker logs")
    output = result.get("output")
    if not isinstance(output, dict):
        raise JobError(f"Job {job_id} completed without an output object")
    return result


def save_images(result, output_dir):
    """Decode the official worker-comfyui 5.x output.images[] structure."""
    output = result.get("output")
    images = output.get("images") if isinstance(output, dict) else None
    if not isinstance(images, list) or not images:
        raise JobError("Completed job has no output.images; inspect output.errors and worker logs")
    job_id = _job_id(result)
    output_dir = Path(output_dir)
    files = []
    for index, image in enumerate(images, start=1):
        if not isinstance(image, dict) or image.get("type") not in ("base64", "s3_url"):
            raise JobError(f"Image {index} has an unsupported output type")
        data = image.get("data")
        if not isinstance(data, str) or not data:
            raise JobError(f"Image {index} has no data")
        if image["type"] == "s3_url":
            files.append({"url": data})
            continue
        try:
            content = base64.b64decode(data.removeprefix("data:image/png;base64,").removeprefix(
                "data:image/jpeg;base64,").removeprefix("data:image/webp;base64,"), validate=True)
        except (binascii.Error, ValueError) as exc:
            raise JobError(f"Image {index} is not valid base64") from exc
        if not content:
            raise JobError(f"Image {index} decoded to an empty file")
        filename = image.get("filename")
        suffix = Path(filename).suffix.lower() if isinstance(filename, str) else ""
        if suffix not in (".png", ".jpg", ".jpeg", ".webp"):
            suffix = ".png" if content.startswith(b"\x89PNG") else ".bin"
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / f"{job_id}_{index:02d}{suffix}"
        try:
            with path.open("xb") as file:
                file.write(content)
        except OSError as exc:
            raise JobError(f"Could not save image to {path}: {exc}") from exc
        files.append({"path": str(path)})
    return files


def result_summary(result, files):
    summary = {"job_id": _job_id(result), "status": result["status"], "images": files}
    for key in ("delayTime", "executionTime"):
        value = result.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0:
            summary[key + "Ms"] = value
    if "executionTimeMs" in summary:
        summary["estimatedGpuCostUsd"] = round(
            summary["executionTimeMs"] / 3_600_000 * GPU_DOLLARS_PER_HOUR, 6
        )
        summary["costBasis"] = "$0.69/GPU-hour x reported executionTime; excludes startup, idle and other charges"
    if result.get("output", {}).get("errors"):
        summary["workerErrors"] = result["output"]["errors"]
    return summary


def run_job(plain_request, *, output_dir="outputs", poll_interval=5, max_wait=1500):
    payload = prepare_request(plain_request)
    result = submit_and_poll(payload, os.environ.get("RUNPOD_API_KEY"),
                             os.environ.get("RUNPOD_ENDPOINT_ID"),
                             poll_interval=poll_interval, max_wait=max_wait)
    return result_summary(result, save_images(result, output_dir))


def _parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, help="JSON plain request; image paths relative to file")
    parser.add_argument("--prompt", help="Text prompt passed unchanged to the Qwen encoder")
    parser.add_argument("--width", type=int, help="Image width (multiple of 32; default 1024)")
    parser.add_argument("--height", type=int, help="Image height (multiple of 32; default 1024)")
    parser.add_argument("--seed", type=int, help="Unsigned seed (default 42)")
    parser.add_argument("--turbo", action=argparse.BooleanOptionalAction, default=None,
                        help="Turbo on by default; --no-turbo selects the normal workflow")
    parser.add_argument("--image", action="append", dest="images", help="Local image file for edit mode; repeat for multiple inputs")
    parser.add_argument("--dry-run", action="store_true", help="Print official worker payload without submitting")
    parser.add_argument("--output-dir", type=Path, default=Path("outputs"))
    parser.add_argument("--poll-interval", type=float, default=5)
    parser.add_argument("--max-wait", type=float, default=1500)
    return parser


def main(argv=None):
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        request = load_plain_request(args.request) if args.request else {}
        for name in ("prompt", "width", "height", "seed", "turbo", "images"):
            value = getattr(args, name)
            if value is not None:
                request[name] = value
        payload = prepare_request(request)
        if args.dry_run:
            print(json.dumps(payload, indent=2))
        else:
            if args.poll_interval <= 0 or args.max_wait <= 0:
                raise RequestError("--poll-interval and --max-wait must be positive")
            print(json.dumps(run_job(request, output_dir=args.output_dir,
                                     poll_interval=args.poll_interval, max_wait=args.max_wait)))
        return 0
    except (RequestError, JobError) as exc:
        print(json.dumps({"error": str(exc), "type": "request_error" if isinstance(exc, RequestError)
                          else "job_error"}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
