import sqlite3, json
from collections import Counter
import os

# ============================================================
# 统一数据目录：所有 SQLite / faiss / metadata 集中到 data/ 子目录
# 效果：NAS 部署只需备份 data/ 一个文件夹
# ============================================================
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
os.makedirs(DATA_DIR, exist_ok=True)

def _db(name: str) -> str:
    return os.path.join(DATA_DIR, name)

#############DATABASE###################

def startup_db_configurations():
    conn = sqlite3.connect(_db('settings.db'))
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            immich_server_url text, 
            api_key text, 
            images_folder text, 
            timeout number
        )
    ''')

    # Check if the table is empty
    c.execute('SELECT COUNT(*) FROM settings')
    if c.fetchone()[0] == 0:
        # Insert default settings, setting timeout to 1500 ms
        c.execute('''
            INSERT INTO settings (immich_server_url, api_key, images_folder, timeout)
            VALUES (?, ?, ?, ?)
        ''', ('', '', '', 2000))
    
    # Commit changes and close the connection
    conn.commit()
    conn.close()

def startup_processed_assets_db():
    conn = sqlite3.connect(_db('processed_assets.db'))  # Separate database for processed assets
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS processed_assets (
            asset_id TEXT PRIMARY KEY, 
            phash TEXT NOT NULL,
            asset_info TEXT
        )
    ''')
    conn.commit()
    conn.close()

def load_settings_from_db():
    conn = sqlite3.connect(_db('settings.db'))
    c = conn.cursor()
    c.execute("SELECT * FROM settings LIMIT 1")
    settings = c.fetchone()
    conn.close()
    return settings if settings else (None, None, None, None)

def save_settings_to_db(immich_server_url, api_key, images_folder, timeout):
    conn = sqlite3.connect(_db('settings.db'))
    c = conn.cursor()
    # This simple logic assumes one row of settings; adjust according to your needs
    c.execute("DELETE FROM settings")  # Clear existing settings
    c.execute("INSERT INTO settings VALUES (?, ?, ?, ?)", (immich_server_url, api_key, images_folder, timeout))
    conn.commit()
    conn.close()

def saveAssetInfoToDb(asset_id, phash, asset_info):
    conn = sqlite3.connect(_db('processed_assets.db'))
    c = conn.cursor()
    # Convert asset_info (a dict) to a string for storage; consider what info you need
    asset_info_str = json.dumps(asset_info)
    c.execute("INSERT OR REPLACE INTO processed_assets VALUES (?, ?, ?)",
              (asset_id, phash, asset_info_str))
    conn.commit()
    conn.close()

def isAssetProcessed(asset_id):
    conn = sqlite3.connect(_db('processed_assets.db'))
    c = conn.cursor()
    c.execute("SELECT 1 FROM processed_assets WHERE asset_id = ?", (asset_id,))
    result = c.fetchone()
    conn.close()
    return result is not None

def bytes_to_megabytes(bytes_size):
    """Convert bytes to megabytes (MB) and format to 3 decimal places."""
    if bytes_size is None:
        return "0.001 MB"  # Assuming you want to return this default value for None input
    megabytes = bytes_size / (1024 * 1024)
    return f"{megabytes:.3f} MB"

def countProcessedAssets():
    conn = sqlite3.connect(_db('processed_assets.db'))
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM processed_assets")
    count = c.fetchone()[0]
    conn.close()
    return count

def getHashFromDb(asset_id):
    conn = sqlite3.connect(_db('processed_assets.db'))
    c = conn.cursor()
    c.execute("SELECT phash FROM processed_assets WHERE asset_id = ?", (asset_id,))
    result = c.fetchone()
    conn.close()
    if result:
        return result[0]
    else:
        return None
    
def countDuplicates():
    conn = sqlite3.connect(_db('processed_assets.db'))
    c = conn.cursor()
    # Fetch all hashes from the database
    c.execute("SELECT phash FROM processed_assets")
    hashes = c.fetchall()
    conn.close()
    # Flatten the list of tuples to a list of strings
    hash_list = [item[0] for item in hashes]
    # Use Counter to count occurrences of each hash
    hash_counts = Counter(hash_list)
    # Filter out hashes that appear only once (no duplicates)
    duplicates = {hash_: count for hash_, count in hash_counts.items() if count > 1}
    return duplicates


####################### FAISS #############################
def startup_processed_duplicate_faiss_db():
    try:
        conn = sqlite3.connect(_db('duplicates.db'))
        cursor = conn.cursor()
        sql = '''CREATE TABLE IF NOT EXISTS duplicates(
           id INTEGER PRIMARY KEY,
           vector_id1 INT,
           vector_id2 INT,
           similarity FLOAT
        )'''
        cursor.execute(sql)
        conn.commit()
    except Exception as e:
        print("Error creating database/table:", e)
    finally:
        conn.close()

def save_duplicate_pair(vector_id1, vector_id2, similarity):
    similarity = float(similarity)
    try:
        conn = sqlite3.connect(_db('duplicates.db'))
        cursor = conn.cursor()

        # Check if the pair already exists in either order
        cursor.execute("SELECT * FROM duplicates WHERE (vector_id1 = ? AND vector_id2 = ?) OR (vector_id1 = ? AND vector_id2 = ?)",
                       (vector_id1, vector_id2, vector_id2, vector_id1))
        if cursor.fetchone():
            #print("Duplicate pair already exists.")
            return

        # If not, insert the new pair
        cursor.execute("INSERT INTO duplicates (vector_id1, vector_id2, similarity) VALUES (?, ?, ?)",
                       (vector_id1, vector_id2, similarity))
        conn.commit()
    except Exception as e:
        print("Error inserting duplicate pair:", e)
    finally:
        conn.close()

def delete_duplicate_pair(asset_id_1, asset_id_2):
    try:
        conn = sqlite3.connect(_db('duplicates.db'))
        cursor = conn.cursor()
        # Delete the specific duplicate entry involving the two asset IDs
        cursor.execute("DELETE FROM duplicates WHERE (vector_id1 = ? AND vector_id2 = ?) OR (vector_id1 = ? AND vector_id2 = ?)", (asset_id_1, asset_id_2, asset_id_2, asset_id_1))
        conn.commit()
        print("Deleted asset from db")
    except Exception as e:
        print(f"Error deleting duplicate entries for asset pair {asset_id_1}-{asset_id_2}:", e)
    finally:
        conn.close()

def load_duplicate_pairs(min_threshold, max_threshold):
    """Load duplicate pairs with a similarity between the specified minimum and maximum thresholds."""
    try:
        conn = sqlite3.connect(_db('duplicates.db'))
        cursor = conn.cursor()
        # Adjust the SQL query to filter duplicates within the specified range
        cursor.execute("""
            SELECT vector_id1, vector_id2 FROM duplicates
            WHERE similarity >= ? AND similarity <= ?""",
            (min_threshold, max_threshold))
        duplicates = cursor.fetchall()
        if not duplicates:
            print(f"No duplicates found within thresholds {min_threshold} and {max_threshold}")
        return duplicates
    except Exception as e:
        print("Error loading duplicates:", e)
    finally:
        if conn:
            conn.close()

def is_db_populated():
    """Check if the 'duplicates' table in the database has any entries."""
    conn = None
    try:
        conn = sqlite3.connect(_db('duplicates.db'))
        cursor = conn.cursor()
        # Check if there are any rows in the table
        cursor.execute("SELECT EXISTS(SELECT 1 FROM duplicates LIMIT 1)")
        exists = cursor.fetchone()[0]
        return exists == 1
    except Exception as e:
        print("Error checking database population:", e)
        return False
    finally:
        if conn:
            conn.close()


# ============================================================
# NEW TABLE 1: path_mapping（多路径映射配置）
# ============================================================
# 角色 role 枚举与 pathMapper 保持一致：
#   "缓存目录(/data)"  "内部库原图目录"  "Postgres数据库目录"  "外部媒体库"
def startup_path_mapping_db():
    conn = sqlite3.connect(_db('settings.db'))
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS path_mapping (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            container_path TEXT NOT NULL,
            nas_path TEXT NOT NULL,
            role TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        )
    ''')
    c.execute('''
        CREATE UNIQUE INDEX IF NOT EXISTS idx_path_mapping_cp
        ON path_mapping(container_path)
    ''')
    conn.commit()
    conn.close()


def insert_path_mapping(container_path: str, nas_path: str, role: str) -> int:
    conn = sqlite3.connect(_db('settings.db'))
    c = conn.cursor()
    c.execute(
        "INSERT INTO path_mapping(container_path, nas_path, role) VALUES (?, ?, ?)",
        (container_path, nas_path, role),
    )
    new_id = c.lastrowid
    conn.commit()
    conn.close()
    return new_id


def update_path_mapping(mapping_id: int, container_path: str, nas_path: str, role: str):
    conn = sqlite3.connect(_db('settings.db'))
    c = conn.cursor()
    c.execute(
        "UPDATE path_mapping SET container_path=?, nas_path=?, role=? WHERE id=?",
        (container_path, nas_path, role, mapping_id),
    )
    conn.commit()
    conn.close()


def delete_path_mapping(mapping_id: int):
    conn = sqlite3.connect(_db('settings.db'))
    c = conn.cursor()
    c.execute("DELETE FROM path_mapping WHERE id=?", (mapping_id,))
    conn.commit()
    conn.close()


def load_path_mappings():
    """ 返回所有映射行，按 container_path 长度降序（最长优先匹配）"""
    conn = sqlite3.connect(_db('settings.db'))
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute(
        "SELECT id, container_path, nas_path, role, created_at FROM path_mapping ORDER BY length(container_path) DESC, id ASC"
    )
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


# ============================================================
# NEW TABLE 2: operation_logs（删除操作审计日志）
# ============================================================
def startup_operation_logs_db():
    conn = sqlite3.connect(_db('settings.db'))
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS operation_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_id TEXT NOT NULL,
            dry_run INTEGER NOT NULL DEFAULT 1,    -- 1=DryRun 0=真实删除
            force INTEGER NOT NULL DEFAULT 0,      -- 1=永久删除 0=回收站
            timestamp TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            detail_json TEXT NOT NULL              -- 逐条资产详情 JSON
        )
    ''')
    c.execute('''
        CREATE INDEX IF NOT EXISTS idx_operation_logs_ts
        ON operation_logs(timestamp DESC)
    ''')
    conn.commit()
    conn.close()


def append_operation_log(batch_id: str, dry_run: int, force: int, detail_json) -> int:
    """ 写入一条日志；detail_json 接受 dict 或 JSON 字符串 """
    if isinstance(detail_json, (dict, list)):
        payload = json.dumps(detail_json, ensure_ascii=False)
    else:
        payload = str(detail_json)
    conn = sqlite3.connect(_db('settings.db'))
    c = conn.cursor()
    c.execute(
        "INSERT INTO operation_logs(batch_id, dry_run, force, detail_json) VALUES (?, ?, ?, ?)",
        (batch_id, 1 if dry_run else 0, 1 if force else 0, payload),
    )
    new_id = c.lastrowid
    conn.commit()
    conn.close()
    return new_id


def query_operation_logs(limit: int = 100, offset: int = 0,
                         batch_id: str = None, dry_run: int = None, force: int = None):
    conn = sqlite3.connect(_db('settings.db'))
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    sql = "SELECT id, batch_id, dry_run, force, timestamp, detail_json FROM operation_logs WHERE 1=1"
    params = []
    if batch_id is not None and batch_id != "":
        sql += " AND batch_id LIKE ?"
        params.append(f"%{batch_id}%")
    if dry_run is not None:
        sql += " AND dry_run = ?"
        params.append(1 if dry_run else 0)
    if force is not None:
        sql += " AND force = ?"
        params.append(1 if force else 0)
    sql += " ORDER BY id DESC LIMIT ? OFFSET ?"
    params += [int(limit), int(offset)]
    c.execute(sql, params)
    rows = []
    for r in c.fetchall():
        d = dict(r)
        try:
            d["detail_json"] = json.loads(d["detail_json"])
        except Exception:
            d["detail_json"] = {"raw": d["detail_json"]}
        rows.append(d)
    conn.close()
    return rows


def count_operation_logs(batch_id: str = None, dry_run: int = None, force: int = None) -> int:
    conn = sqlite3.connect(_db('settings.db'))
    c = conn.cursor()
    sql = "SELECT COUNT(*) FROM operation_logs WHERE 1=1"
    params = []
    if batch_id is not None and batch_id != "":
        sql += " AND batch_id LIKE ?"
        params.append(f"%{batch_id}%")
    if dry_run is not None:
        sql += " AND dry_run = ?"
        params.append(1 if dry_run else 0)
    if force is not None:
        sql += " AND force = ?"
        params.append(1 if force else 0)
    c.execute(sql, params)
    n = c.fetchone()[0]
    conn.close()
    return n
