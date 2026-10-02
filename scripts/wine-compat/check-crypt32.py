"""Check certificate signatures and store cleanup using a public root DER file.

Run with Windows Python under the isolated Wine test profile. All stores are
private memory stores; the installed trust store is never changed.
"""
import ctypes as C
from ctypes import wintypes as W
import json
from pathlib import Path
import sys

C.CDLL('msvcrt')._set_error_mode(1)  # assertions go to stderr, not a dialog
c = C.WinDLL('crypt32', use_last_error=True)
c.CertOpenStore.argtypes = [C.c_void_p, W.DWORD, C.c_void_p, W.DWORD, C.c_void_p]
c.CertOpenStore.restype = W.HANDLE
c.CertAddEncodedCertificateToStore.argtypes = [
    W.HANDLE, W.DWORD, C.c_void_p, W.DWORD, W.DWORD, C.POINTER(C.c_void_p)]
c.CertAddEncodedCertificateToStore.restype = W.BOOL
c.CertCreateCertificateContext.argtypes = [W.DWORD, C.c_void_p, W.DWORD]
c.CertCreateCertificateContext.restype = C.c_void_p
c.CertDuplicateCertificateContext.argtypes = [C.c_void_p]
c.CertDuplicateCertificateContext.restype = C.c_void_p
c.CertFreeCertificateContext.argtypes = [C.c_void_p]
c.CertFreeCertificateContext.restype = W.BOOL
c.CertVerifySubjectCertificateContext.argtypes = [C.c_void_p, C.c_void_p, C.POINTER(W.DWORD)]
c.CertVerifySubjectCertificateContext.restype = W.BOOL
c.CertCloseStore.argtypes = [W.HANDLE, W.DWORD]
c.CertCloseStore.restype = W.BOOL
der = Path(sys.argv[1]).read_bytes()

def memory_store():
    store = c.CertOpenStore(2, 0, None, 0, None)
    assert store, C.get_last_error()
    encoded = C.create_string_buffer(der)
    cert = C.c_void_p()
    assert c.CertAddEncodedCertificateToStore(
        store, 1, encoded, len(der), 1, C.byref(cert)), C.get_last_error()
    return store, cert

def signature_valid(cert, issuer):
    flags = W.DWORD(1)  # CERT_STORE_SIGNATURE_FLAG
    ok = c.CertVerifySubjectCertificateContext(cert, issuer, C.byref(flags))
    return bool(ok) and flags.value == 0

store, cert = memory_store()
assert signature_valid(cert, cert), 'Valid root signature rejected'
tampered = bytearray(der)
tampered[-1] ^= 1
buffer = C.create_string_buffer(bytes(tampered))
bad_cert = c.CertCreateCertificateContext(1, buffer, len(tampered))
assert bad_cert, C.get_last_error()
assert not signature_valid(bad_cert, cert), 'Invalid signature accepted'
assert c.CertFreeCertificateContext(bad_cert)

# A non-forced close reports the outstanding context and keeps it valid.
assert not c.CertCloseStore(store, 2)  # CERT_CLOSE_STORE_CHECK_FLAG
assert C.get_last_error() & 0xffffffff == 0x8009200f  # CRYPT_E_PENDING_CLOSE
assert signature_valid(cert, cert)
assert c.CertFreeCertificateContext(cert)

# A forced close must free outstanding references without an assertion.
store, cert = memory_store()
assert c.CertDuplicateCertificateContext(cert)
assert c.CertCloseStore(store, 1), C.get_last_error()

# Acrobat also uses DPAPI for its local settings and account storage.
class BLOB(C.Structure):
    _fields_ = [('size', W.DWORD), ('data', C.c_void_p)]

c.CryptProtectData.argtypes = [C.POINTER(BLOB), W.LPCWSTR, C.c_void_p,
                               C.c_void_p, C.c_void_p, W.DWORD, C.POINTER(BLOB)]
c.CryptProtectData.restype = W.BOOL
c.CryptUnprotectData.argtypes = [C.POINTER(BLOB), C.c_void_p, C.c_void_p,
                                 C.c_void_p, C.c_void_p, W.DWORD, C.POINTER(BLOB)]
c.CryptUnprotectData.restype = W.BOOL
k = C.WinDLL('kernel32', use_last_error=True)
k.LocalFree.argtypes = [C.c_void_p]
k.LocalFree.restype = C.c_void_p
payload = b'Acrobat Wine compatibility check'
buffer = C.create_string_buffer(payload)
plain = BLOB(len(payload), C.cast(buffer, C.c_void_p))
encrypted, recovered = BLOB(), BLOB()
assert c.CryptProtectData(C.byref(plain), None, None, None, None, 1,
                         C.byref(encrypted)), C.get_last_error()
try:
    assert c.CryptUnprotectData(C.byref(encrypted), None, None, None, None, 1,
                               C.byref(recovered)), C.get_last_error()
    assert C.string_at(recovered.data, recovered.size) == payload
finally:
    if recovered.data:
        k.LocalFree(recovered.data)
    k.LocalFree(encrypted.data)
print(json.dumps({
    'valid_signature': 'passed', 'invalid_signature_rejected': 'passed',
    'non_forced_close_preserves_context': 'passed',
    'forced_close_with_outstanding_references': 'passed',
    'dpapi_round_trip': 'passed',
}))
