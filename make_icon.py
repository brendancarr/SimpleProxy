"""
Run this once to generate icon.ico for the build.
  python make_icon.py
"""
from PIL import Image, ImageDraw

def make_icon():
    sizes = [16, 32,48, 64, 128, 256]
    frames = []
    for size in sizes:
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        pad = max(1, size // 16)
        # Dark background circle
        draw.ellipse([pad, pad, size - pad, size - pad], fill=(30, 30, 40, 255))
        # Green ring
        ring = max(2, size // 12)
        draw.ellipse([pad, pad, size - pad, size - pad], outline=(52, 199, 89, 255), width=ring)
        # Arrow / forward symbol (triangle pointing right)
        cx, cy = size // 2, size // 2
        arrow_size = size // 3
        points = [
            (cx - arrow_size // 2, cy - arrow_size),
            (cx - arrow_size // 2, cy + arrow_size),
            (cx + arrow_size,      cy),
        ]
        draw.polygon(points, fill=(52, 199, 89, 255))
        frames.append(img)

    # Save as .ico with all sizes embedded
    frames[0].save(
        "icon.ico",
        format="ICO",
        sizes=[(s, s) for s in sizes],
        append_images=frames[1:],
    )
    print("icon.ico created successfully.")

if __name__ == "__main__":
    make_icon()
