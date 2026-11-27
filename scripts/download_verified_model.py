"""Download a pinned Hugging Face artifact in bounded ranges, verify its SHA256, then publish."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import time
import requests


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo")
    parser.add_argument("revision")
    parser.add_argument("filename")
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    # Large repository listings may paginate. Use the exact file's paths-info endpoint.
    info = requests.post(f"https://huggingface.co/api/models/{args.repo}/paths-info/{args.revision}",
                         json={"paths":[args.filename]}, timeout=30)
    info.raise_for_status()
    record = info.json()[0]
    size = record["size"]
    expected = record["lfs"]["oid"]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.is_file() and hashlib.file_digest(args.output.open("rb"), "sha256").hexdigest() == expected:
        print("Already verified", args.output)
        return
    parts = args.output.with_name(args.output.name + ".ranges")
    parts.mkdir(exist_ok=True)
    url = f"https://huggingface.co/{args.repo}/resolve/{args.revision}/{args.filename}"
    chunk = 8 * 1024**2

    def fetch(start):
        end = min(start + chunk, size) - 1
        path = parts / str(start)
        if path.exists() and path.stat().st_size == end-start+1:
            return
        partial = path.with_suffix(".part")
        for attempt in range(5):
            try:
                with requests.get(url, headers={"Range":f"bytes={start}-{end}"},
                                  stream=True, timeout=(20,45)) as response:
                    response.raise_for_status()
                    if response.status_code != 206 or response.headers.get("Content-Range") != f"bytes {start}-{end}/{size}":
                        raise ValueError("Server did not honor requested range")
                    with partial.open("wb") as output:
                        for block in response.iter_content(256 * 1024):
                            output.write(block)
                if partial.stat().st_size != end-start+1:
                    raise ValueError("Partial transfer")
                partial.replace(path)
                return
            except (requests.RequestException, ValueError):
                if attempt == 4:
                    raise
                time.sleep(attempt+1)
    starts = list(range(0,size,chunk))
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures=[pool.submit(fetch,s) for s in starts]
        for n,future in enumerate(as_completed(futures),1):
            future.result()
            if n%16 == 0:
                print(f"{n}/{len(starts)} ranges",flush=True)
    staging = args.output.with_name(args.output.name + ".verified-part")
    sha = hashlib.sha256()
    with staging.open("wb") as out:
        for start in starts:
            data=(parts/str(start)).read_bytes()
            sha.update(data)
            out.write(data)
    if sha.hexdigest()!=expected:
        raise ValueError("SHA256 mismatch; artifact was not installed")
    staging.replace(args.output)
    args.output.with_suffix(".provenance.json").write_text(json.dumps({
        "repository": args.repo, "revision": args.revision, "filename": args.filename,
        "sha256": expected, "size": size,
    }, indent=2), encoding="utf-8")
    for start in starts:
        (parts/str(start)).unlink()
    parts.rmdir()
    print("Verified", args.output, flush=True)


if __name__ == "__main__":
    main()
