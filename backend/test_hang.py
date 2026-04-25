import sys
import os
import time

sys.path.insert(0, r"c:\Users\rawal\OneDrive\Desktop\macs\macs-compressor\backend")
from compressors import image_compressor

print("Loading file...")
with open(r"c:\Users\rawal\OneDrive\Desktop\macs\macs-compressor\macs.png", "rb") as f:
    file_bytes = f.read()

print("Calling compress...")
start = time.time()
try:
    res = image_compressor.compress(file_bytes, "macs.png")
    print("Done in", time.time() - start)
except Exception as e:
    print("Error:", e)
