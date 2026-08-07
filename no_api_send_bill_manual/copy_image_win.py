"""
Copy ຮູບໄປ Windows clipboard — ຕ້ອງຮັນດ້ວຍ Python ຢູ່ Windows (ໃຊ້ໂດຍ run_manual.py ຈາກ WSL)
ໃຊ້: python copy_image_win.py <path_to_image>
"""
import sys
import os

if sys.platform != "win32":
    print("ສະຄຣິບນີ້ໃຊ້ໄດ້ແຕ່ໃນ Windows (win32clipboard)")
    sys.exit(1)

if len(sys.argv) < 2:
    print("ໃຊ້: python copy_image_win.py <path_to_image>")
    sys.exit(1)

image_path = sys.argv[1]
if not os.path.isfile(image_path):
    print("ບໍ່ພົບໄຟລ໌ຮູບ:", image_path)
    sys.exit(1)

try:
    import win32clipboard
    from PIL import Image
    from io import BytesIO
except ImportError as e:
    print("ຕ້ອງຕິດຕັ້ງ: pip install Pillow pywin32")
    sys.exit(1)

im = Image.open(image_path)
if im.mode in ("RGBA", "P"):
    bg = Image.new("RGB", im.size, (255, 255, 255))
    if im.mode == "P":
        im = im.convert("RGBA")
    bg.paste(im, mask=im.split()[-1] if im.mode == "RGBA" else None)
    im = bg
elif im.mode != "RGB":
    im = im.convert("RGB")

out = BytesIO()
im.save(out, "BMP")
data = out.getvalue()[14:]
out.close()

win32clipboard.OpenClipboard()
win32clipboard.EmptyClipboard()
win32clipboard.SetClipboardData(win32clipboard.CF_DIB, data)
win32clipboard.CloseClipboard()
sys.exit(0)
