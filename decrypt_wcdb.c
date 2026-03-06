// decrypt_wcdb.c - Decrypt WeChat database using WCDB framework internals
// Compile: clang -o decrypt_wcdb decrypt_wcdb.c -ldl -framework Foundation
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>

#define SQLITE_OK 0
#define SQLITE_ROW 100
#define SQLITE_DONE 101

// Function pointer types
typedef int (*sqlite3_open_fn)(const char*, void**);
typedef int (*sqlite3_close_fn)(void*);
typedef int (*sqlite3_key_raw_fn)(void*, const void*, int);
typedef int (*sqlite3_exec_fn)(void*, const char*, void*, void*, char**);
typedef const char* (*sqlite3_errmsg_fn)(void*);
typedef int (*sqlite3_prepare_fn)(void*, const char*, int, void**, const char**);
typedef int (*sqlite3_step_fn)(void*);
typedef int (*sqlite3_finalize_fn)(void*);
typedef int (*sqlite3_column_count_fn)(void*);
typedef const char* (*sqlite3_column_text_fn)(void*, int);
typedef const char* (*sqlite3_column_name_fn)(void*, int);
typedef void* (*sqlite3BtreePager_fn)(void*);
typedef void* (*sqlite3PagerGetCodec_fn)(void*);
typedef int (*sqlcipher_codec_ctx_set_raw_fn)(void*, int);
typedef int (*sqlcipher_codec_ctx_set_pagesize_fn)(void*, int);
typedef int (*sqlcipher_codec_ctx_set_kdf_iter_fn)(void*, int);
typedef int (*sqlcipher_codec_ctx_set_use_hmac_fn)(void*, int);
typedef int (*sqlcipher_codec_ctx_get_pagesize_fn)(void*);
typedef int (*sqlcipher_codec_ctx_get_kdf_iter_fn)(void*);
typedef int (*sqlcipher_codec_ctx_get_use_hmac_fn)(void*);
typedef int (*sqlcipher_codec_ctx_get_reservesize_fn)(void*);
typedef int (*sqlcipher_codec_key_derive_fn)(void*);

static void *wcdb_lib = NULL;
static sqlite3_open_fn fn_open;
static sqlite3_close_fn fn_close;
static sqlite3_key_raw_fn fn_key_raw;
static sqlite3_exec_fn fn_exec;
static sqlite3_errmsg_fn fn_errmsg;
static sqlite3_prepare_fn fn_prepare;
static sqlite3_step_fn fn_step;
static sqlite3_finalize_fn fn_finalize;
static sqlite3_column_count_fn fn_col_count;
static sqlite3_column_text_fn fn_col_text;
static sqlite3_column_name_fn fn_col_name;
static sqlite3BtreePager_fn fn_btree_pager;
static sqlite3PagerGetCodec_fn fn_pager_get_codec;
static sqlcipher_codec_ctx_set_raw_fn fn_set_raw;
static sqlcipher_codec_ctx_set_pagesize_fn fn_set_pagesize;
static sqlcipher_codec_ctx_set_kdf_iter_fn fn_set_kdf_iter;
static sqlcipher_codec_ctx_set_use_hmac_fn fn_set_use_hmac;
static sqlcipher_codec_ctx_get_pagesize_fn fn_get_pagesize;
static sqlcipher_codec_ctx_get_kdf_iter_fn fn_get_kdf_iter;
static sqlcipher_codec_ctx_get_use_hmac_fn fn_get_use_hmac;
static sqlcipher_codec_ctx_get_reservesize_fn fn_get_reservesize;
static sqlcipher_codec_key_derive_fn fn_key_derive;

int load_wcdb() {
    wcdb_lib = dlopen("/Applications/WeChat.app/Contents/Frameworks/WCDB.framework/Versions/A/WCDB", RTLD_NOW);
    if (!wcdb_lib) { fprintf(stderr, "Failed to load WCDB: %s\n", dlerror()); return -1; }

    fn_open = dlsym(wcdb_lib, "sqlite3_open");
    fn_close = dlsym(wcdb_lib, "sqlite3_close");
    fn_key_raw = dlsym(wcdb_lib, "sqlite3_key_raw");
    fn_exec = dlsym(wcdb_lib, "sqlite3_exec");
    fn_errmsg = dlsym(wcdb_lib, "sqlite3_errmsg");
    fn_prepare = dlsym(wcdb_lib, "sqlite3_prepare");
    fn_step = dlsym(wcdb_lib, "sqlite3_step");
    fn_finalize = dlsym(wcdb_lib, "sqlite3_finalize");
    fn_col_count = dlsym(wcdb_lib, "sqlite3_column_count");
    fn_col_text = dlsym(wcdb_lib, "sqlite3_column_text");
    fn_col_name = dlsym(wcdb_lib, "sqlite3_column_name");
    fn_btree_pager = dlsym(wcdb_lib, "sqlite3BtreePager");
    fn_pager_get_codec = dlsym(wcdb_lib, "sqlite3PagerGetCodec");
    fn_set_raw = dlsym(wcdb_lib, "sqlcipher_codec_ctx_set_raw");
    fn_set_pagesize = dlsym(wcdb_lib, "sqlcipher_codec_ctx_set_pagesize");
    fn_set_kdf_iter = dlsym(wcdb_lib, "sqlcipher_codec_ctx_set_kdf_iter");
    fn_set_use_hmac = dlsym(wcdb_lib, "sqlcipher_codec_ctx_set_use_hmac");
    fn_get_pagesize = dlsym(wcdb_lib, "sqlcipher_codec_ctx_get_pagesize");
    fn_get_kdf_iter = dlsym(wcdb_lib, "sqlcipher_codec_ctx_get_kdf_iter");
    fn_get_use_hmac = dlsym(wcdb_lib, "sqlcipher_codec_ctx_get_use_hmac");
    fn_get_reservesize = dlsym(wcdb_lib, "sqlcipher_codec_ctx_get_reservesize");
    fn_key_derive = dlsym(wcdb_lib, "sqlcipher_codec_key_derive");

    if (!fn_open || !fn_close || !fn_key_raw || !fn_exec) {
        fprintf(stderr, "Failed to find required symbols\n");
        return -1;
    }
    return 0;
}

// Try to get codec context from sqlite3 handle by probing internal structs
// sqlite3 -> aDb[0].pBt -> sqlite3BtreePager() -> sqlite3PagerGetCodec()
void* get_codec_ctx(void *db) {
    if (!fn_btree_pager || !fn_pager_get_codec) return NULL;

    // The sqlite3 struct has aDb pointer. We need to find its offset.
    // Try common offsets for SQLite/WCDB on arm64:
    // Typically: pVfs(8) + pVdbe(8) + pDfltColl(8) + mutex(8) = offset 32
    // But might vary. Try several offsets.
    int offsets[] = {32, 40, 48, 24, 56, 64};
    int num_offsets = sizeof(offsets) / sizeof(offsets[0]);

    for (int i = 0; i < num_offsets; i++) {
        int offset = offsets[i];
        // Read aDb pointer
        void **aDb_ptr = (void**)((char*)db + offset);
        void *aDb = *aDb_ptr;
        if (!aDb) continue;

        // In Db struct, pBt is at offset 8 (after zDbSName char*)
        void *pBt = *(void**)((char*)aDb + 8);
        if (!pBt) continue;

        // Get pager from btree
        void *pager = fn_btree_pager(pBt);
        if (!pager) continue;

        // Get codec from pager
        void *codec = fn_pager_get_codec(pager);
        if (!codec) continue;

        printf("  Found codec at db+%d: aDb=%p, pBt=%p, pager=%p, codec=%p\n",
               offset, aDb, pBt, pager, codec);

        // Try to read page size from codec to verify it's valid
        if (fn_get_pagesize) {
            int ps = fn_get_pagesize(codec);
            printf("  Codec page_size=%d, ", ps);
        }
        if (fn_get_kdf_iter) {
            int kdf = fn_get_kdf_iter(codec);
            printf("kdf_iter=%d, ", kdf);
        }
        if (fn_get_use_hmac) {
            int hmac = fn_get_use_hmac(codec);
            printf("use_hmac=%d, ", hmac);
        }
        if (fn_get_reservesize) {
            int rs = fn_get_reservesize(codec);
            printf("reserve_size=%d", rs);
        }
        printf("\n");
        return codec;
    }
    return NULL;
}

int try_decrypt(const char *db_path, const unsigned char *key, int key_len, int set_raw) {
    void *db = NULL;
    int rc;
    char *errmsg = NULL;

    rc = fn_open(db_path, &db);
    if (rc != SQLITE_OK) {
        printf("  open failed: %d\n", rc);
        return -1;
    }

    // Set the key
    rc = fn_key_raw(db, key, key_len);
    printf("  sqlite3_key_raw rc=%d\n", rc);

    if (set_raw) {
        // Try to get codec and set raw mode
        void *codec = get_codec_ctx(db);
        if (codec && fn_set_raw) {
            rc = fn_set_raw(codec, 1);
            printf("  set_raw rc=%d\n", rc);

            // Re-derive key after setting raw mode
            if (fn_key_derive) {
                rc = fn_key_derive(codec);
                printf("  key_derive rc=%d\n", rc);
            }
        } else {
            printf("  Could not get codec context\n");
        }
    }

    // Try to query
    rc = fn_exec(db, "SELECT count(*) FROM sqlite_master;", NULL, NULL, &errmsg);
    if (rc == SQLITE_OK) {
        printf("  *** SUCCESS! Database decrypted! ***\n");

        // List tables
        void *stmt = NULL;
        const char *tail = NULL;
        rc = fn_prepare(db, "SELECT name FROM sqlite_master WHERE type='table';", -1, &stmt, &tail);
        if (rc == SQLITE_OK) {
            printf("  Tables: ");
            while (fn_step(stmt) == SQLITE_ROW) {
                printf("%s ", fn_col_text(stmt, 0));
            }
            printf("\n");
            fn_finalize(stmt);
        }
    } else {
        printf("  FAIL: rc=%d err=%s\n", rc, errmsg ? errmsg : "");
    }

    fn_close(db);
    return rc == SQLITE_OK ? 0 : -1;
}

int main(int argc, char *argv[]) {
    if (load_wcdb() != 0) return 1;
    printf("WCDB framework loaded.\n\n");

    const char *db_path;
    if (argc > 1) {
        db_path = argv[1];
    } else {
        // Default path
        char path[1024];
        const char *home = getenv("HOME");
        snprintf(path, sizeof(path),
            "%s/Library/Containers/com.tencent.xinWeChat/Data/Library/Application Support/"
            "com.tencent.xinWeChat/2.0b4.0.9/cd115c7f9a41375233480bbd6f050167/Message/msg_0.db", home);
        db_path = strdup(path);
    }

    printf("Database: %s\n\n", db_path);

    // Full 46-byte key with cafecafe prefix
    unsigned char key_full[] = {
        0xca,0xfe,0xca,0xfe,0x09,0x46,0x7d,0xf1,
        0x23,0x51,0x59,0xc3,0x7f,0x23,0xeb,0xcd,
        0x6f,0xe5,0x18,0xb0,0x80,0xcd,0x82,0xa2,
        0x6a,0x58,0x42,0xa2,0x44,0xeb,0x70,0xc5,
        0x51,0x4a,0x51,0x16,0x17,0xc9,0x6f,0x14,
        0x39,0xb0,0xd4,0x49,0x62,0xb1
    };

    // 42-byte key after cafecafe
    unsigned char key_42[] = {
        0x09,0x46,0x7d,0xf1,0x23,0x51,0x59,0xc3,
        0x7f,0x23,0xeb,0xcd,0x6f,0xe5,0x18,0xb0,
        0x80,0xcd,0x82,0xa2,0x6a,0x58,0x42,0xa2,
        0x44,0xeb,0x70,0xc5,0x51,0x4a,0x51,0x16,
        0x17,0xc9,0x6f,0x14,0x39,0xb0,0xd4,0x49,
        0x62,0xb1
    };

    // 32-byte key
    unsigned char key_32[] = {
        0x09,0x46,0x7d,0xf1,0x23,0x51,0x59,0xc3,
        0x7f,0x23,0xeb,0xcd,0x6f,0xe5,0x18,0xb0,
        0x80,0xcd,0x82,0xa2,0x6a,0x58,0x42,0xa2,
        0x44,0xeb,0x70,0xc5,0x51,0x4a,0x51,0x16
    };

    printf("=== Test 1: full 46-byte key, with raw mode ===\n");
    try_decrypt(db_path, key_full, 46, 1);

    printf("\n=== Test 2: 42-byte key, with raw mode ===\n");
    try_decrypt(db_path, key_42, 42, 1);

    printf("\n=== Test 3: 32-byte key, with raw mode ===\n");
    try_decrypt(db_path, key_32, 32, 1);

    printf("\n=== Test 4: full 46-byte key, no raw mode ===\n");
    try_decrypt(db_path, key_full, 46, 0);

    printf("\n=== Test 5: 42-byte key, no raw mode ===\n");
    try_decrypt(db_path, key_42, 42, 0);

    printf("\n=== Test 6: 32-byte key, no raw mode ===\n");
    try_decrypt(db_path, key_32, 32, 0);

    if (wcdb_lib) dlclose(wcdb_lib);
    return 0;
}
