#!/usr/bin/env python3
"""
See-Through Remote Inference Runner
Calls HuggingFace Space (24yearsold/see-through-demo) Gradio API to decompose a single 2D character
illustration into fully-inpainted layers and layered PSD.
"""
import sys
import os
import json
import time
import argparse
import requests

SPACE_URL = "https://24yearsold-see-through-demo.hf.space"
UPLOAD_URL = f"{SPACE_URL}/gradio_api/upload"
CALL_URL = f"{SPACE_URL}/gradio_api/call/inference"


def decompose_image(image_path: str, output_dir: str, resolution: int = 768, seed: int = 42, tblr_split: bool = True):
    if not os.path.exists(image_path):
        raise FileNotFoundError(f"Image not found: {image_path}")

    os.makedirs(output_dir, exist_ok=True)
    filename = os.path.basename(image_path)
    stem = os.path.splitext(filename)[0]

    print(f"[*] Uploading {image_path} to See-Through Space...")
    with open(image_path, "rb") as f:
        files = {"files": (filename, f, "image/png")}
        r_up = requests.post(UPLOAD_URL, files=files, timeout=60)

    if r_up.status_code != 200:
        raise RuntimeError(f"Upload failed ({r_up.status_code}): {r_up.text}")

    uploaded_files = r_up.json()
    uploaded_path = uploaded_files[0]
    print(f"[+] Uploaded as: {uploaded_path}")

    payload = {
        "data": [
            {"path": uploaded_path, "meta": {"_type": "gradio.FileData"}},
            resolution,
            seed,
            tblr_split
        ]
    }

    print("[*] Triggering inference...")
    r_call = requests.post(CALL_URL, json=payload, timeout=60)
    if r_call.status_code != 200:
        raise RuntimeError(f"Inference trigger failed: {r_call.text}")

    event_id = r_call.json().get("event_id")
    print(f"[+] Event ID: {event_id}")

    stream_url = f"{CALL_URL}/{event_id}"
    print(f"[*] Awaiting results from SSE stream...")

    start_time = time.time()
    with requests.get(stream_url, stream=True, timeout=600) as r_stream:
        for line in r_stream.iter_lines():
            if not line:
                continue
            decoded = line.decode("utf-8", errors="ignore")
            if decoded.startswith("data:"):
                data_str = decoded[5:].strip()
                try:
                    data_obj = json.loads(data_str)
                    if isinstance(data_obj, list) and len(data_obj) >= 2:
                        psd_info = data_obj[0]
                        gallery_info = data_obj[1]
                        print(f"[+] Inference complete in {int(time.time() - start_time)}s!")

                        # 1. Download PSD
                        if isinstance(psd_info, dict) and psd_info.get("url"):
                            psd_url = psd_info["url"]
                            if psd_url.startswith("/"):
                                psd_url = f"{SPACE_URL}{psd_url}"
                            print(f"[*] Downloading PSD: {psd_url}")
                            r_psd = requests.get(psd_url, timeout=120)
                            psd_dest = os.path.join(output_dir, f"{stem}.psd")
                            with open(psd_dest, "wb") as pf:
                                pf.write(r_psd.content)
                            print(f"[+] Saved PSD: {psd_dest} ({len(r_psd.content)} bytes)")

                        # 2. Download Layers
                        if isinstance(gallery_info, list):
                            print(f"[*] Downloading {len(gallery_info)} decomposed layers...")
                            for idx, item in enumerate(gallery_info):
                                img_data = item.get("image") or item
                                caption = item.get("caption") or f"layer_{idx:02d}"
                                if isinstance(img_data, dict) and img_data.get("url"):
                                    l_url = img_data["url"]
                                    if l_url.startswith("/"):
                                        l_url = f"{SPACE_URL}{l_url}"
                                    r_l = requests.get(l_url, timeout=60)
                                    clean_caption = "".join(c for c in caption if c.isalnum() or c in ("-", "_")).strip()
                                    l_dest = os.path.join(output_dir, f"{idx:02d}_{clean_caption}.png")
                                    with open(l_dest, "wb") as lf:
                                        lf.write(r_l.content)
                                    print(f"  - [{idx:02d}] {clean_caption} ({len(r_l.content)} B)")
                        return
                except Exception as e:
                    pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="See-Through AI layer decomposition")
    parser.add_argument("image", help="Path to input image (PNG/JPG)")
    parser.add_argument("-o", "--output", default="layers_out", help="Output directory")
    parser.add_argument("-r", "--resolution", type=int, default=768, help="Resolution (default: 768)")
    parser.add_argument("-s", "--seed", type=int, default=42, help="Seed (default: 42)")
    parser.add_argument("--no-split", action="store_true", help="Disable left/right limb split")
    args = parser.parse_args()

    decompose_image(args.image, args.output, resolution=args.resolution, seed=args.seed, tblr_split=not args.no_split)
