#!/usr/bin/env python3
"""Convert plain generation requests to worker-comfyui 5.x API-workflow input.

A request is {"prompt": str, "width": int, "height": int, "seed": int,
"turbo": bool, "images": [local_image_path_or_base64, ...]}. No server-side
handler or prompt transformation is involved. Relative image paths in a JSON
request are resolved relative to that JSON file.
"""

import argparse
import binascii
import base64
import json
import mimetypes
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / "workflows"
WORKFLOW_NAMES = {
    (False, False): "qwen-normal-api.json",
    (True, False): "qwen-turbo-api.json",
    (False, True): "qwen-normal-edit-api.json",
    (True, True): "qwen-turbo-edit-api.json",
}
PROMPT_NODE = "4"
SIZE_NODE = "8"
SEED_NODE = "7"
MAX_IMAGE_BYTES = 6 * 1024 * 1024  # Base64 expands by 4/3; /run has a ~10 MB limit.
MAX_REQUEST_BYTES = 9 * 1024 * 1024


class RequestError(ValueError):
    """Invalid user request, local image, or workflow template."""


def load_plain_request(path):
    source = Path(path).expanduser().resolve()
    try:
        request = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RequestError(f"Cannot read request JSON at {source}: {exc}") from exc
    if not isinstance(request, dict):
        raise RequestError("Request JSON must be an object")
    if isinstance(request.get("images"), list):
        request["images"] = [
            (image if _looks_inline(image) else str((source.parent / image).resolve()))
            if isinstance(image, str) else image
            for image in request["images"]
        ]
    return request

def _looks_inline(value):
    return (isinstance(value, str) and
            (value.startswith(("data:image/", "iVBORw", "/9j/", "UklGR")) or len(value) > 512))

def _positive_dimension(value, name):
    if type(value) is not int or not 32 <= value <= 2048 or value % 32:
        raise RequestError(f"{name} must be a multiple of 32 between 32 and 2048")
    return value


def validate_plain_request(request):
    if not isinstance(request, dict):
        raise RequestError("Request must be a JSON object")
    unknown = set(request) - {"prompt", "width", "height", "seed", "turbo", "images"}
    if unknown:
        raise RequestError(f"Unknown request fields: {', '.join(sorted(unknown))}")
    prompt = request.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise RequestError("prompt must be a non-empty string")
    width = _positive_dimension(request.get("width", 1024), "width")
    height = _positive_dimension(request.get("height", 1024), "height")
    seed = request.get("seed", 42)
    if type(seed) is not int or not 0 <= seed < 2**64:
        raise RequestError("seed must be an unsigned 64-bit integer")
    turbo = request.get("turbo", True)
    if type(turbo) is not bool:
        raise RequestError("turbo must be a boolean")
    images = request.get("images", [])
    if not isinstance(images, list) or any(not isinstance(image, str) or not image for image in images):
        raise RequestError("images must be a list of image paths or base64 strings")
    return {"prompt": prompt, "width": width, "height": height, "seed": seed,
            "turbo": turbo, "images": images}


def _node(workflow, node_id, class_type, keys):
    node = workflow.get(node_id)
    if not isinstance(node, dict) or node.get("class_type") != class_type:
        raise RequestError(f"Workflow node {node_id} must be {class_type}")
    inputs = node.get("inputs")
    if not isinstance(inputs, dict) or not set(keys) <= inputs.keys():
        raise RequestError(f"Workflow node {node_id} requires inputs: {', '.join(keys)}")
    return inputs


def validate_workflow(workflow, *, turbo=True, editing=False):
    """Reject UI exports, dangling links, and templates missing caller-controlled nodes."""
    if not isinstance(workflow, dict) or not workflow:
        raise RequestError("Workflow must be a non-empty API-format node object")
    _node(workflow, PROMPT_NODE, "TextEncodeQwenImage21", ("prompt",))
    if not editing:
        _node(workflow, SIZE_NODE, "EmptyLatentImage", ("width", "height"))
    _node(workflow, SEED_NODE, "RandomNoise" if turbo else "KSampler",
          ("noise_seed",) if turbo else ("seed",))
    if not any(isinstance(node, dict) and node.get("class_type") == "SaveImage"
               for node in workflow.values()):
        raise RequestError("Workflow must contain SaveImage")
    image_nodes = []
    for node_id, node in workflow.items():
        if not isinstance(node_id, str) or not node_id.isdecimal() or not isinstance(node, dict):
            raise RequestError("Workflow must use numeric string node IDs and node objects")
        inputs = node.get("inputs")
        if not isinstance(node.get("class_type"), str) or not isinstance(inputs, dict):
            raise RequestError(f"Workflow node {node_id} needs class_type and inputs")
        if node["class_type"] == "LoadImage":
            if "image" not in inputs:
                raise RequestError(f"LoadImage node {node_id} needs image input")
            image_nodes.append(node_id)
        for key, value in inputs.items():
            if (isinstance(value, list) and len(value) == 2
                    and isinstance(value[0], str) and value[0].isdecimal()
                    and type(value[1]) is int and value[0] not in workflow):
                raise RequestError(f"Node {node_id}.{key} links to absent node {value[0]}")
    if editing and not image_nodes:
        raise RequestError("Edit workflow must have at least one LoadImage node")
    if not editing and image_nodes:
        raise RequestError("Text-to-image workflow must not require input images")
    return sorted(image_nodes, key=int)


def load_workflow(turbo=True, editing=False, workflow_dir=WORKFLOWS):
    filename = WORKFLOW_NAMES[(turbo, editing)]
    path = Path(workflow_dir) / filename
    try:
        workflow = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RequestError(f"Cannot read workflow {path}: {exc}") from exc
    validate_workflow(workflow, turbo=turbo, editing=editing)
    return workflow


def _image_mime(raw):
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png", ".png"
    if raw.startswith(b"\xff\xd8\xff"):
        return "image/jpeg", ".jpg"
    if raw.startswith(b"RIFF") and raw[8:12] == b"WEBP":
        return "image/webp", ".webp"
    raise RequestError("Input image must contain PNG, JPEG or WebP bytes")


def _encode_images(images):
    uploads = []
    for index, source in enumerate(images, start=1):
        if _looks_inline(source):
            encoded = source
            if encoded.startswith("data:"):
                prefix, separator, encoded = encoded.partition(",")
                if not separator or not prefix.endswith(";base64"):
                    raise RequestError(f"Image {index} needs a base64 data URI")
            if len(encoded) > (MAX_IMAGE_BYTES + 2) * 4 // 3:
                raise RequestError(f"Image {index} exceeds {MAX_IMAGE_BYTES} decoded bytes")
            try:
                raw = base64.b64decode(encoded, validate=True)
            except (binascii.Error, ValueError) as exc:
                raise RequestError(f"Image {index} has invalid base64") from exc
        else:
            path = Path(source).expanduser()
            try:
                if not path.is_file():
                    raise RequestError(f"Input image not found: {path}")
                if path.stat().st_size > MAX_IMAGE_BYTES:
                    raise RequestError(f"Input image exceeds {MAX_IMAGE_BYTES} bytes: {path}")
                raw = path.read_bytes()
            except OSError as exc:
                raise RequestError(f"Cannot read input image {path}: {exc}") from exc
            claimed_mime, _ = mimetypes.guess_type(path.name)
            if claimed_mime not in ("image/png", "image/jpeg", "image/webp"):
                raise RequestError(f"Input image must be a PNG, JPEG or WebP file: {path}")
        mime, suffix = _image_mime(raw)
        if not _looks_inline(source) and claimed_mime != mime:
            raise RequestError(f"Input image signature does not match its extension: {path}")
        if len(raw) > MAX_IMAGE_BYTES:
            raise RequestError(f"Image {index} exceeds {MAX_IMAGE_BYTES} bytes")
        name = f"input_image_{index}{suffix}"
        uploads.append({"name": name, "image": f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"})
    return uploads


def prepare_request(request, workflow_dir=WORKFLOWS):
    plain = validate_plain_request(request)
    editing = bool(plain["images"])
    if editing and (plain["width"] != 1024 or plain["height"] != 1024):
        raise RequestError("Edit workflow derives image dimensions from the input; only default width/height 1024 are accepted")
    workflow = load_workflow(plain["turbo"], editing, workflow_dir)
    workflow[PROMPT_NODE]["inputs"]["prompt"] = plain["prompt"]
    if not editing:
        workflow[SIZE_NODE]["inputs"].update(width=plain["width"], height=plain["height"])
    seed_key = "noise_seed" if plain["turbo"] else "seed"
    workflow[SEED_NODE]["inputs"][seed_key] = plain["seed"]
    # The default per-job deadline can expire while a large image is cold-pulling.
    payload = {"input": {"workflow": workflow}, "policy": {"executionTimeout": 1_200_000}}
    if editing:
        image_nodes = validate_workflow(workflow, turbo=plain["turbo"], editing=True)
        if len(image_nodes) != len(plain["images"]):
            raise RequestError(f"Edit workflow requires {len(image_nodes)} input image(s); "
                               f"received {len(plain['images'])}")
        uploads = _encode_images(plain["images"])
        for node_id, upload in zip(image_nodes, uploads):
            workflow[node_id]["inputs"]["image"] = upload["name"]
        payload["input"]["images"] = uploads
    if len(json.dumps(payload, separators=(",", ":")).encode("utf-8")) > MAX_REQUEST_BYTES:
        raise RequestError("Payload exceeds safe async /run size (~9 MB); use smaller images")
    return payload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("request", nargs="?", help="Plain JSON request file (image paths relative to this file)")
    parser.add_argument("--prompt", help="Text prompt passed unchanged")
    parser.add_argument("--width", type=int, help="Image width (default 1024)")
    parser.add_argument("--height", type=int, help="Image height (default 1024)")
    parser.add_argument("--seed", type=int, help="Unsigned seed (default 42)")
    parser.add_argument("--turbo", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--image", action="append", dest="images", help="Local image; repeat to supply more")
    parser.add_argument("--output", type=Path, help="Write worker payload here instead of stdout")
    args = parser.parse_args()
    try:
        request = load_plain_request(args.request) if args.request else {}
        for name in ("prompt", "width", "height", "seed", "turbo", "images"):
            value = getattr(args, name)
            if value is not None:
                request[name] = value
        payload = prepare_request(request)
        formatted = json.dumps(payload, indent=2) + "\n"
        if args.output:
            args.output.write_text(formatted, encoding="utf-8")
        else:
            print(formatted, end="")
    except (RequestError, OSError) as exc:
        parser.exit(2, json.dumps({"error": str(exc), "type": "request_error"}) + "\n")


if __name__ == "__main__":
    main()
