#!/usr/bin/env python3
"""Test various approaches to decrypt WeChat WCDB database."""
import ctypes
import os

WCDB_PATH = "/Applications/WeChat.app/Contents/Frameworks/WCDB.framework/Versions/A/WCDB"
DB_PATH = os.path.expanduser(
    "~/Library/Containers/com.tencent.xinWeChat/Data/Library/Application Support/"
    "com.tencent.xinWeChat/2.0b4.0.9/cd115c7f9a41375233480bbd6f050167/Message/msg_0.db"
)

RAW_KEY_HEX = "cafecafe09467df1235159c37f23ebcd6fe518b080cd82a26a5842a244eb70c5514a511617c96f1439b0d44962b1"
KEY_AFTER_CAFE = "09467df1235159c37f23ebcd6fe518b080cd82a26a5842a244eb70c5514a511617c96f1439b0d44962b1"
KEY_32 = "09467df1235159c37f23ebcd6fe518b080cd82a26a5842a244eb70c5514a5116"

SQLITE_OK = 0

wcdb = ctypes.CDLL(WCDB_PATH)
wcdb.sqlite3_open.argtypes = [ctypes.c_char_p, ctypes.POINTER(ctypes.c_void_p)]
wcdb.sqlite3_open.restype = ctypes.c_int
wcdb.sqlite3_key_raw.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int]
wcdb.sqlite3_key_raw.restype = ctypes.c_int
wcdb.sqlite3_exec.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_char_p)]
wcdb.sqlite3_exec.restype = ctypes.c_int
wcdb.sqlite3_close.argtypes = [ctypes.c_void_p]
wcdb.sqlite3_close.restype = ctypes.c_int
wcdb.sqlite3_errmsg.argtypes = [ctypes.c_void_p]
wcdb.sqlite3_errmsg.restype = ctypes.c_char_p

# sqlcipher_codec_ctx_set_raw(codec_ctx, raw)
wcdb.sqlcipher_codec_ctx_set_raw.argtypes = [ctypes.c_void_p, ctypes.c_int]
wcdb.sqlcipher_codec_ctx_set_raw.restype = ctypes.c_int

# Try to find sqlcipher_find_db_index and sqlcipher_codec_get_ctx
try:
    wcdb.sqlite3Pager_get_codec.argtypes = [ctypes.c_void_p]
    wcdb.sqlite3Pager_get_codec.restype = ctypes.c_void_p
except:
    pass


def try_open(label, key_bytes, pragmas_before=None, pragmas_after=None):
    """Try to open with given key and PRAGMAs."""
    db = ctypes.c_void_p()
    rc = wcdb.sqlite3_open(DB_PATH.encode(), ctypes.byref(db))
    if rc != SQLITE_OK:
        print(f"  [{label}] open failed: {rc}")
        return

    errmsg = ctypes.c_char_p()

    # Run pre-key PRAGMAs
    if pragmas_before:
        for p in pragmas_before:
            wcdb.sqlite3_exec(db, p.encode(), None, None, ctypes.byref(errmsg))

    # Set key
    key_buf = ctypes.create_string_buffer(key_bytes)
    rc = wcdb.sqlite3_key_raw(db, key_buf, len(key_bytes))

    # Run post-key PRAGMAs
    if pragmas_after:
        for p in pragmas_after:
            rc2 = wcdb.sqlite3_exec(db, p.encode(), None, None, ctypes.byref(errmsg))
            if rc2 != SQLITE_OK and errmsg.value:
                pass  # ignore PRAGMA errors silently

    # Try to read
    rc = wcdb.sqlite3_exec(db, b"SELECT count(*) FROM sqlite_master;", None, None, ctypes.byref(errmsg))
    err = errmsg.value.decode() if errmsg.value else ""
    if rc == SQLITE_OK:
        print(f"  [{label}] SUCCESS!")
    else:
        print(f"  [{label}] FAIL rc={rc} err={err}")

    wcdb.sqlite3_close(db)


def try_pragma_key(label, pragma_key_sql, pragmas_after=None):
    """Try using PRAGMA key instead of sqlite3_key_raw."""
    db = ctypes.c_void_p()
    rc = wcdb.sqlite3_open(DB_PATH.encode(), ctypes.byref(db))
    if rc != SQLITE_OK:
        print(f"  [{label}] open failed: {rc}")
        return

    errmsg = ctypes.c_char_p()

    # Set key via PRAGMA
    rc = wcdb.sqlite3_exec(db, pragma_key_sql.encode(), None, None, ctypes.byref(errmsg))
    if rc != SQLITE_OK and errmsg.value:
        print(f"  [{label}] PRAGMA key err: {errmsg.value.decode()}")

    # Post-key PRAGMAs
    if pragmas_after:
        for p in pragmas_after:
            wcdb.sqlite3_exec(db, p.encode(), None, None, ctypes.byref(errmsg))

    # Try to read
    rc = wcdb.sqlite3_exec(db, b"SELECT count(*) FROM sqlite_master;", None, None, ctypes.byref(errmsg))
    err = errmsg.value.decode() if errmsg.value else ""
    if rc == SQLITE_OK:
        print(f"  [{label}] SUCCESS!")
    else:
        print(f"  [{label}] FAIL rc={rc} err={err}")

    wcdb.sqlite3_close(db)


print("=== Method A: sqlite3_key_raw with various PRAGMAs ===")

# A1: Full 46-byte key, then page_size
try_open("A1: full key + page 1024",
         bytes.fromhex(RAW_KEY_HEX),
         pragmas_after=["PRAGMA cipher_page_size = 1024;"])

# A2: Full 46-byte key, then page_size 4096
try_open("A2: full key + page 4096",
         bytes.fromhex(RAW_KEY_HEX),
         pragmas_after=["PRAGMA cipher_page_size = 4096;"])

# A3: Key after cafecafe (42 bytes), page 1024
try_open("A3: 42-byte key + page 1024",
         bytes.fromhex(KEY_AFTER_CAFE),
         pragmas_after=["PRAGMA cipher_page_size = 1024;"])

# A4: First 32 bytes, page 1024
try_open("A4: 32-byte key + page 1024",
         bytes.fromhex(KEY_32),
         pragmas_after=["PRAGMA cipher_page_size = 1024;"])

# A5: Full key with cipher_use_hmac OFF
try_open("A5: full key + no hmac",
         bytes.fromhex(RAW_KEY_HEX),
         pragmas_after=["PRAGMA cipher_page_size = 1024;", "PRAGMA cipher_use_hmac = OFF;"])

# A6: Full key with kdf_iter = 4000
try_open("A6: full key + kdf 4000",
         bytes.fromhex(RAW_KEY_HEX),
         pragmas_after=["PRAGMA cipher_page_size = 1024;", "PRAGMA kdf_iter = 4000;"])

# A7: Full key with kdf_iter = 64000
try_open("A7: full key + kdf 64000",
         bytes.fromhex(RAW_KEY_HEX),
         pragmas_after=["PRAGMA cipher_page_size = 1024;", "PRAGMA kdf_iter = 64000;"])

# A8: Full key, no extra PRAGMAs (use defaults)
try_open("A8: full key, defaults",
         bytes.fromhex(RAW_KEY_HEX))

# A9: 42-byte key, no extra PRAGMAs
try_open("A9: 42-byte key, defaults",
         bytes.fromhex(KEY_AFTER_CAFE))

# A10: 32-byte key, no extra PRAGMAs
try_open("A10: 32-byte key, defaults",
         bytes.fromhex(KEY_32))


print("\n=== Method B: PRAGMA key (hex-encoded) ===")

# B1: PRAGMA key with x'...' (full 46 bytes)
try_pragma_key("B1: PRAGMA key x'full'",
               f"PRAGMA key = \"x'{RAW_KEY_HEX}'\";",
               ["PRAGMA cipher_page_size = 1024;"])

# B2: PRAGMA key with x'...' (42 bytes after cafecafe)
try_pragma_key("B2: PRAGMA key x'42b'",
               f"PRAGMA key = \"x'{KEY_AFTER_CAFE}'\";",
               ["PRAGMA cipher_page_size = 1024;"])

# B3: PRAGMA key with x'...' (32 bytes)
try_pragma_key("B3: PRAGMA key x'32b'",
               f"PRAGMA key = \"x'{KEY_32}'\";",
               ["PRAGMA cipher_page_size = 1024;"])

# B4: PRAGMA key as string passphrase
try_pragma_key("B4: PRAGMA key passphrase",
               f"PRAGMA key = '{KEY_AFTER_CAFE}';",
               ["PRAGMA cipher_page_size = 1024;"])

# B5: Full 46 bytes, page 4096
try_pragma_key("B5: PRAGMA key x'full' p4096",
               f"PRAGMA key = \"x'{RAW_KEY_HEX}'\";",
               ["PRAGMA cipher_page_size = 4096;"])

# B6: 32 bytes, page 4096
try_pragma_key("B6: PRAGMA key x'32b' p4096",
               f"PRAGMA key = \"x'{KEY_32}'\";",
               ["PRAGMA cipher_page_size = 4096;"])

# B7-B8: Try with defaults (no page size PRAGMA)
try_pragma_key("B7: PRAGMA key x'full' defaults",
               f"PRAGMA key = \"x'{RAW_KEY_HEX}'\";")

try_pragma_key("B8: PRAGMA key x'32b' defaults",
               f"PRAGMA key = \"x'{KEY_32}'\";")

print("\n=== Method C: page_size before key ===")

# C1: Set page_size BEFORE key
try_open("C1: page1024 BEFORE full key",
         bytes.fromhex(RAW_KEY_HEX),
         pragmas_before=["PRAGMA cipher_page_size = 1024;"])

# C2: Set page_size BEFORE 42-byte key
try_open("C2: page1024 BEFORE 42b key",
         bytes.fromhex(KEY_AFTER_CAFE),
         pragmas_before=["PRAGMA cipher_page_size = 1024;"])
