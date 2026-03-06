#!/usr/bin/env python3
"""Decrypt WeChat macOS database using WCDB framework from WeChat.app"""

import ctypes
import ctypes.util
import os
import sys
import shutil

# WCDB framework path from WeChat.app
WCDB_PATH = "/Applications/WeChat.app/Contents/Frameworks/WCDB.framework/Versions/A/WCDB"

# Raw key extracted from LLDB (46 bytes including cafecafe prefix)
RAW_KEY_HEX = "cafecafe09467df1235159c37f23ebcd6fe518b080cd82a26a5842a244eb70c5514a511617c96f1439b0d44962b1"
RAW_KEY = bytes.fromhex(RAW_KEY_HEX)

# WeChat data paths
WECHAT_BASE = os.path.expanduser(
    "~/Library/Containers/com.tencent.xinWeChat/Data/Library/Application Support/"
    "com.tencent.xinWeChat/2.0b4.0.9/cd115c7f9a41375233480bbd6f050167"
)

# SQLite constants
SQLITE_OK = 0
SQLITE_ROW = 100
SQLITE_DONE = 101


def load_wcdb():
    """Load WCDB framework and set up function signatures."""
    wcdb = ctypes.CDLL(WCDB_PATH)

    # sqlite3_open(filename, &db) -> int
    wcdb.sqlite3_open.argtypes = [ctypes.c_char_p, ctypes.POINTER(ctypes.c_void_p)]
    wcdb.sqlite3_open.restype = ctypes.c_int

    # sqlite3_key_raw(db, key, key_len) -> int
    wcdb.sqlite3_key_raw.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int]
    wcdb.sqlite3_key_raw.restype = ctypes.c_int

    # sqlite3_exec(db, sql, callback, arg, &errmsg) -> int
    wcdb.sqlite3_exec.argtypes = [
        ctypes.c_void_p, ctypes.c_char_p, ctypes.c_void_p,
        ctypes.c_void_p, ctypes.POINTER(ctypes.c_char_p)
    ]
    wcdb.sqlite3_exec.restype = ctypes.c_int

    # sqlite3_prepare_v2(db, sql, nbyte, &stmt, &tail) -> int
    wcdb.sqlite3_prepare_v2 = getattr(wcdb, 'sqlite3_prepare', None)
    if wcdb.sqlite3_prepare_v2:
        wcdb.sqlite3_prepare_v2.argtypes = [
            ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int,
            ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_char_p)
        ]
        wcdb.sqlite3_prepare_v2.restype = ctypes.c_int

    # sqlite3_step(stmt) -> int
    wcdb.sqlite3_step.argtypes = [ctypes.c_void_p]
    wcdb.sqlite3_step.restype = ctypes.c_int

    # sqlite3_column_count(stmt) -> int
    wcdb.sqlite3_column_count.argtypes = [ctypes.c_void_p]
    wcdb.sqlite3_column_count.restype = ctypes.c_int

    # sqlite3_column_text(stmt, col) -> char*
    wcdb.sqlite3_column_text.argtypes = [ctypes.c_void_p, ctypes.c_int]
    wcdb.sqlite3_column_text.restype = ctypes.c_char_p

    # sqlite3_column_name(stmt, col) -> char*
    wcdb.sqlite3_column_name.argtypes = [ctypes.c_void_p, ctypes.c_int]
    wcdb.sqlite3_column_name.restype = ctypes.c_char_p

    # sqlite3_column_type(stmt, col) -> int
    wcdb.sqlite3_column_type.argtypes = [ctypes.c_void_p, ctypes.c_int]
    wcdb.sqlite3_column_type.restype = ctypes.c_int

    # sqlite3_column_blob(stmt, col) -> void*
    wcdb.sqlite3_column_blob.argtypes = [ctypes.c_void_p, ctypes.c_int]
    wcdb.sqlite3_column_blob.restype = ctypes.c_void_p

    # sqlite3_column_bytes(stmt, col) -> int
    wcdb.sqlite3_column_bytes.argtypes = [ctypes.c_void_p, ctypes.c_int]
    wcdb.sqlite3_column_bytes.restype = ctypes.c_int

    # sqlite3_column_int(stmt, col) -> int
    wcdb.sqlite3_column_int.argtypes = [ctypes.c_void_p, ctypes.c_int]
    wcdb.sqlite3_column_int.restype = ctypes.c_int

    # sqlite3_column_int64(stmt, col) -> int64
    wcdb.sqlite3_column_int64.argtypes = [ctypes.c_void_p, ctypes.c_int]
    wcdb.sqlite3_column_int64.restype = ctypes.c_longlong

    # sqlite3_column_double(stmt, col) -> double
    wcdb.sqlite3_column_double.argtypes = [ctypes.c_void_p, ctypes.c_int]
    wcdb.sqlite3_column_double.restype = ctypes.c_double

    # sqlite3_finalize(stmt) -> int
    wcdb.sqlite3_finalize.argtypes = [ctypes.c_void_p]
    wcdb.sqlite3_finalize.restype = ctypes.c_int

    # sqlite3_close(db) -> int
    wcdb.sqlite3_close.argtypes = [ctypes.c_void_p]
    wcdb.sqlite3_close.restype = ctypes.c_int

    # sqlite3_errmsg(db) -> char*
    wcdb.sqlite3_errmsg.argtypes = [ctypes.c_void_p]
    wcdb.sqlite3_errmsg.restype = ctypes.c_char_p

    return wcdb


def open_encrypted_db(wcdb, db_path):
    """Open an encrypted WeChat database using WCDB framework."""
    db = ctypes.c_void_p()
    rc = wcdb.sqlite3_open(db_path.encode('utf-8'), ctypes.byref(db))
    if rc != SQLITE_OK:
        print(f"  Failed to open database: rc={rc}")
        return None

    # Set the cipher key (full 46 bytes including cafecafe prefix)
    key_buf = ctypes.create_string_buffer(RAW_KEY)
    rc = wcdb.sqlite3_key_raw(db, key_buf, len(RAW_KEY))
    if rc != SQLITE_OK:
        errmsg = wcdb.sqlite3_errmsg(db)
        print(f"  Failed to set key: rc={rc}, err={errmsg}")
        wcdb.sqlite3_close(db)
        return None

    # Verify we can read
    errmsg = ctypes.c_char_p()
    rc = wcdb.sqlite3_exec(db, b"SELECT count(*) FROM sqlite_master;", None, None, ctypes.byref(errmsg))
    if rc != SQLITE_OK:
        err = errmsg.value.decode('utf-8') if errmsg.value else 'unknown'
        print(f"  Key verification failed: rc={rc}, err={err}")
        wcdb.sqlite3_close(db)
        return None

    print(f"  Database opened and decrypted successfully!")
    return db


def query_tables(wcdb, db):
    """List all tables in the database."""
    stmt = ctypes.c_void_p()
    tail = ctypes.c_char_p()
    sql = b"SELECT name, type FROM sqlite_master WHERE type='table' ORDER BY name;"
    rc = wcdb.sqlite3_prepare_v2(db, sql, -1, ctypes.byref(stmt), ctypes.byref(tail))
    if rc != SQLITE_OK:
        print(f"  Failed to prepare query: rc={rc}")
        return []

    tables = []
    while wcdb.sqlite3_step(stmt) == SQLITE_ROW:
        name = wcdb.sqlite3_column_text(stmt, 0)
        if name:
            tables.append(name.decode('utf-8'))
    wcdb.sqlite3_finalize(stmt)
    return tables


def export_to_plain_sqlite(wcdb, encrypted_db, tables, output_path):
    """Export decrypted data to a plain SQLite database."""
    import sqlite3

    if os.path.exists(output_path):
        os.remove(output_path)

    plain_db = sqlite3.connect(output_path)
    cursor = plain_db.cursor()

    for table_name in tables:
        # Get CREATE TABLE statement
        stmt = ctypes.c_void_p()
        tail = ctypes.c_char_p()
        sql = f"SELECT sql FROM sqlite_master WHERE name='{table_name}' AND type='table';".encode('utf-8')
        rc = wcdb.sqlite3_prepare_v2(encrypted_db, sql, -1, ctypes.byref(stmt), ctypes.byref(tail))
        if rc != SQLITE_OK:
            continue

        create_sql = None
        if wcdb.sqlite3_step(stmt) == SQLITE_ROW:
            text = wcdb.sqlite3_column_text(stmt, 0)
            if text:
                create_sql = text.decode('utf-8')
        wcdb.sqlite3_finalize(stmt)

        if not create_sql:
            continue

        # Create table in plain db
        try:
            cursor.execute(create_sql)
        except sqlite3.OperationalError as e:
            print(f"  Warning: {table_name}: {e}")
            continue

        # Copy data
        stmt = ctypes.c_void_p()
        tail = ctypes.c_char_p()
        sql = f"SELECT * FROM [{table_name}];".encode('utf-8')
        rc = wcdb.sqlite3_prepare_v2(encrypted_db, sql, -1, ctypes.byref(stmt), ctypes.byref(tail))
        if rc != SQLITE_OK:
            continue

        col_count = wcdb.sqlite3_column_count(stmt)
        row_count = 0

        while wcdb.sqlite3_step(stmt) == SQLITE_ROW:
            row = []
            for i in range(col_count):
                col_type = wcdb.sqlite3_column_type(stmt, i)
                if col_type == 5:  # SQLITE_NULL
                    row.append(None)
                elif col_type == 1:  # SQLITE_INTEGER
                    row.append(wcdb.sqlite3_column_int64(stmt, i))
                elif col_type == 2:  # SQLITE_FLOAT
                    row.append(wcdb.sqlite3_column_double(stmt, i))
                elif col_type == 4:  # SQLITE_BLOB
                    blob_ptr = wcdb.sqlite3_column_blob(stmt, i)
                    blob_size = wcdb.sqlite3_column_bytes(stmt, i)
                    if blob_ptr and blob_size > 0:
                        row.append(ctypes.string_at(blob_ptr, blob_size))
                    else:
                        row.append(None)
                else:  # SQLITE_TEXT (3)
                    text = wcdb.sqlite3_column_text(stmt, i)
                    row.append(text.decode('utf-8') if text else None)

            placeholders = ','.join(['?'] * col_count)
            try:
                cursor.execute(f"INSERT INTO [{table_name}] VALUES ({placeholders})", row)
            except Exception:
                pass
            row_count += 1

        wcdb.sqlite3_finalize(stmt)
        if row_count > 0:
            print(f"  Exported {table_name}: {row_count} rows")

    plain_db.commit()
    plain_db.close()


def main():
    print("=== WeChat Database Decryptor ===\n")
    print(f"Key (hex): {RAW_KEY_HEX}")
    print(f"Key length: {len(RAW_KEY)} bytes\n")

    wcdb = load_wcdb()
    print(f"WCDB framework loaded from: {WCDB_PATH}\n")

    # Database files to decrypt
    msg_dir = os.path.join(WECHAT_BASE, "Message")
    db_files = sorted([f for f in os.listdir(msg_dir) if f.endswith('.db') and not f.endswith('-backup')])

    output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "decrypted_dbs")
    os.makedirs(output_dir, exist_ok=True)

    for db_file in db_files:
        db_path = os.path.join(msg_dir, db_file)
        print(f"Processing: {db_file}")

        db = open_encrypted_db(wcdb, db_path)
        if db is None:
            continue

        tables = query_tables(wcdb, db)
        print(f"  Tables: {tables}")

        if tables:
            output_path = os.path.join(output_dir, db_file.replace('.db', '_decrypted.db'))
            export_to_plain_sqlite(wcdb, db, tables, output_path)
            print(f"  -> Saved to: {output_path}")

        wcdb.sqlite3_close(db)
        print()

    # Also try Contact and Session databases
    for sub in ["Contact", "Group", "Session"]:
        sub_dir = os.path.join(WECHAT_BASE, sub)
        if not os.path.isdir(sub_dir):
            continue
        for f in os.listdir(sub_dir):
            if f.endswith('.db') and not f.endswith(('-backup', '-shm', '-wal')):
                db_path = os.path.join(sub_dir, f)
                print(f"Processing: {sub}/{f}")
                db = open_encrypted_db(wcdb, db_path)
                if db is None:
                    continue
                tables = query_tables(wcdb, db)
                print(f"  Tables: {tables}")
                if tables:
                    output_path = os.path.join(output_dir, f"{sub}_{f.replace('.db', '_decrypted.db')}")
                    export_to_plain_sqlite(wcdb, db, tables, output_path)
                    print(f"  -> Saved to: {output_path}")
                wcdb.sqlite3_close(db)
                print()

    print("Done! Decrypted databases saved to:", output_dir)


if __name__ == "__main__":
    main()
