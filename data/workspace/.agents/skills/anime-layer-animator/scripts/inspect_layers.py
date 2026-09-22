#!/usr/bin/env python3
"""
Inspect and validate layers extracted by See-Through.
Detects preview duplicate layers (e.g. 12_head), misclassified fragments, and computes exact pivot coordinates.
"""
import os
import sys
import glob
from PIL import Image

def inspect_layers(layer_dir: str):
    if not os.path.isdir(layer_dir):
        print(f"Directory not found: {layer_dir}")
        return

    files = sorted(glob.glob(os.path.join(layer_dir, "*.png")))
    print(f"[*] Found {len(files)} layers in {layer_dir}:")

    candidates = {}
    for f in files:
        bname = os.path.basename(f)
        try:
            with Image.open(f) as im:
                bbox = im.getbbox()
                if not bbox:
                    continue
                w = bbox[2] - bbox[0]
                h = bbox[3] - bbox[1]
                cx_pct = ((bbox[0] + bbox[2]) / 2 / im.width) * 100
                cy_pct = ((bbox[1] + bbox[3]) / 2 / im.height) * 100
                candidates[bname] = {
                    "path": f,
                    "bbox": bbox,
                    "size": (w, h),
                    "center_pct": (cx_pct, cy_pct),
                    "im_size": im.size
                }
                print(f"  {bname:20s}: size={w}x{h}, center=({cx_pct:.1f}%, {cy_pct:.1f}%), bbox={bbox}")
        except Exception as e:
            print(f"  Error reading {bname}: {e}")

    # Heuristics
    print("\n[!] Layer Heuristics & Recommendations:")
    for name, info in candidates.items():
        if "head" in name and not "headwear" in name:
            if info["size"][0] > 150 and info["size"][1] > 150:
                print(f"  ⚠️  [EXCLUDE] {name}: Likely merged preview head containing eyes/mouth. Exclude to prevent ghosting!")
        if "nose" in name:
            if info["size"][0] > 80 or info["size"][1] > 60:
                print(f"  ⚠️  [EXCLUDE] {name}: Unusually large for a nose ({info['size'][0]}x{info['size'][1]}). Likely hair shade or misclassified fragment.")
        if "irides" in name or "eyes" in name:
            print(f"  ✨ [EYE PIVOT] {name}: Pivot center = ({info['center_pct'][0]:.2f}%, {info['center_pct'][1]:.2f}%)")
        if "mouth" in name:
            print(f"  ✨ [MOUTH PIVOT] {name}: Pivot center = ({info['center_pct'][0]:.2f}%, {info['center_pct'][1]:.2f}%)")

if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "."
    inspect_layers(target)
