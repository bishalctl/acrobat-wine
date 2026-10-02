"""Diagnostic: run with the embedded Windows Python through Wine."""

import ctypes
import json
import sys
from pathlib import Path
from ctypes import wintypes

library = ctypes.WinDLL("mspatcha", use_last_error=True)
apply_patch = library.ApplyPatchToFileW
apply_patch.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.ULONG]
apply_patch.restype = wintypes.BOOL
patch, original, output = (str(Path(p).absolute()) for p in sys.argv[1:4])
result = apply_patch(patch, original, output, 0)
error = ctypes.get_last_error()
print(json.dumps({"success": bool(result), "error": error, "error_hex": hex(error), "message": ctypes.FormatError(error)}))
sys.exit(0 if result else 1)
