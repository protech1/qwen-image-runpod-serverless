"""Stream a single pinned Hugging Face artifact into the image without a second HF cache."""
import hashlib
import json
import os
from pathlib import Path
import sys
from urllib.parse import quote
from urllib.request import urlopen


def main(index: int) -> None:
    manifest = json.loads(Path('/app/versions.json').read_text())
    item = manifest['models'][index]
    destination = Path('/comfyui/models') / item['target']
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = destination.with_suffix(destination.suffix + '.partial')
    url = f"https://huggingface.co/{item['repo']}/resolve/{item['revision']}/{quote(item['file'])}"
    digest = hashlib.sha256()
    size = 0
    try:
        with urlopen(url, timeout=120) as response, temp.open('wb') as output:
            while chunk := response.read(4 * 1024 * 1024):
                output.write(chunk)
                digest.update(chunk)
                size += len(chunk)
        if size != item['bytes'] or digest.hexdigest() != item['sha256']:
            raise ValueError(f"{item['target']}: size or SHA256 mismatch ({size} bytes, {digest.hexdigest()})")
        os.replace(temp, destination)
        print(f"Verified {item['target']}: {size} bytes, sha256={digest.hexdigest()}", flush=True)
    finally:
        temp.unlink(missing_ok=True)


if __name__ == '__main__':
    main(int(sys.argv[1]))
