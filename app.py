import sqlite3
import os
import shutil
from typing import Optional, List
from fastapi import FastAPI, Request, UploadFile, File, Form
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
import pandas as pd
import io
import json

app = FastAPI()

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

def init_db():
    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS master_salesman (
            kode_salesman TEXT PRIMARY KEY,
            nama_salesman TEXT,
            nama_supervisor TEXT
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS promo_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kode_salesman TEXT,
            nama_salesman TEXT,
            nama_supervisor TEXT,
            brand_id TEXT,
            kode_product TEXT,
            promo_type_code TEXT,
            deskripsi_promo TEXT,
            tanggal_posting TEXT,
            mid_hadiah TEXT,
            hadiah_value TEXT,
            jumlah_hadiah TEXT,
            jumlah_claim INTEGER DEFAULT 0,
            setor_hologram INTEGER DEFAULT 0,
            fisik_real INTEGER DEFAULT 0,
            selisih INTEGER DEFAULT 0,
            selisih_selesai INTEGER DEFAULT 0,
            kerapian_claim INTEGER DEFAULT 1,
            keterangan TEXT DEFAULT '',
            foto_path TEXT DEFAULT '',
            status TEXT DEFAULT 'Pending',
            verifikator TEXT DEFAULT ''
        )
    ''')
    conn.commit()
    conn.close()

init_db()

def get_db():
    conn = sqlite3.connect("database.db")
    conn.row_factory = sqlite3.Row
    return conn

def parse_int_clean(val):
    if pd.isna(val) or val is None or val == "":
        return 0
    try:
        if isinstance(val, (int, float)):
            return int(val)
        val_str = str(val).strip()
        if "." in val_str:
            val_str = val_str.split(".")[0]
        if "," in val_str:
            val_str = val_str.split(",")[0]
        return int(val_str)
    except:
        return 0

def clean_str(val):
    if pd.isna(val) or val is None:
        return ""
    return " ".join(str(val).replace("\r", " ").replace("\n", " ").split()).strip()

@app.get("/", response_class=HTMLResponse)
def index():
    with open("index.html", "r", encoding="utf-8") as f:
        return f.read()

@app.get("/api/data-grouped")
def get_data_grouped(salesman: Optional[str] = None, tanggal: Optional[str] = None):
    conn = get_db()
    c = conn.cursor()
    query = "SELECT * FROM promo_data WHERE 1=1"
    params = []
    if salesman:
        query += " AND (kode_salesman LIKE ? OR nama_salesman LIKE ? OR nama_supervisor LIKE ?)"
        params.extend([f"%{salesman}%", f"%{salesman}%", f"%{salesman}%"])
    if tanggal:
        query += " AND tanggal_posting LIKE ?"
        params.append(f"%{tanggal}%")
    
    query += " ORDER BY kode_salesman ASC, id ASC"
    c.execute(query, params)
    rows = [dict(row) for row in c.fetchall()]
    conn.close()

    groups = {}
    for r in rows:
        key = f"{r['kode_salesman']}_{r['tanggal_posting']}"
        if key not in groups:
            groups[key] = {
                "group_key": key,
                "kode_salesman": r["kode_salesman"],
                "nama_salesman": r["nama_salesman"],
                "nama_supervisor": r["nama_supervisor"],
                "tanggal_posting": r["tanggal_posting"],
                "kerapian_claim": r["kerapian_claim"],
                "keterangan": r["keterangan"],
                "foto_path": r["foto_path"],
                "items": []
            }
        groups[key]["items"].append(r)

    return list(groups.values())

@app.post("/api/upload-master-salesman")
async def upload_master_salesman(file: UploadFile = File(...)):
    try:
        content = await file.read()
        df = pd.read_excel(io.BytesIO(content))
        df.columns = [clean_str(c) for c in df.columns]
        
        col_kode = next((c for c in df.columns if "kode" in c.lower() and "sales" in c.lower()), df.columns[0])
        col_nama = next((c for c in df.columns if "nama" in c.lower() and "sales" in c.lower()), df.columns[1] if len(df.columns) > 1 else None)
        col_spv = next((c for c in df.columns if "spv" in c.lower() or "supervisor" in c.lower()), df.columns[2] if len(df.columns) > 2 else None)
        
        conn = get_db()
        c = conn.cursor()
        count = 0
        for _, row in df.iterrows():
            kode = clean_str(row.get(col_kode, "")).upper()
            nama = clean_str(row.get(col_nama, "-")) if col_nama else "-"
            spv = clean_str(row.get(col_spv, "-")) if col_spv else "-"
            
            if kode and kode != 'NAN':
                c.execute('''
                    INSERT INTO master_salesman (kode_salesman, nama_salesman, nama_supervisor)
                    VALUES (?, ?, ?)
                    ON CONFLICT(kode_salesman) DO UPDATE SET
                        nama_salesman = excluded.nama_salesman,
                        nama_supervisor = excluded.nama_supervisor
                ''', (kode, nama, spv))
                
                c.execute('''
                    UPDATE promo_data 
                    SET nama_salesman = ?, nama_supervisor = ?
                    WHERE UPPER(TRIM(kode_salesman)) = ?
                ''', (nama, spv, kode))
                count += 1
                
        conn.commit()
        conn.close()
        return {"status": "success", "total_salesman": count}
    except Exception as e:
        return JSONResponse(status_code=500, content={"message": f"Error: {str(e)}"})

@app.post("/api/upload-excel")
async def upload_excel(file: UploadFile = File(...), reset: str = Form("false")):
    try:
        content = await file.read()
        df = pd.read_excel(io.BytesIO(content))
        df.columns = [clean_str(c) for c in df.columns]

        conn = get_db()
        c = conn.cursor()

        if reset.lower() == "true":
            c.execute("DELETE FROM promo_data")

        c.execute("SELECT kode_salesman, nama_salesman, nama_supervisor FROM master_salesman")
        sales_map = {clean_str(row['kode_salesman']).upper(): (clean_str(row['nama_salesman']), clean_str(row['nama_supervisor'])) for row in c.fetchall()}

        # Cari kolom secara spesifik dan ketat
        col_kode = next((c for c in df.columns if clean_str(c).lower() == 'kode salesman'), None)
        if not col_kode:
            col_kode = next((c for c in df.columns if "kode" in c.lower() and "sales" in c.lower()), df.columns[0])

        col_desk = next((c for c in df.columns if "deskripsi" in c.lower()), None)
        col_type = next((c for c in df.columns if "type" in c.lower() or "promotype" in c.lower()), None)
        col_setor = next((c for c in df.columns if "setor" in c.lower()), 'Setor Hologram')
        col_claim = next((c for c in df.columns if "claim" in c.lower()), 'Jumlah Claim')
        col_tgl = next((c for c in df.columns if "posting" in c.lower() or "tanggal" in c.lower()), 'Tanggal Posting')
        col_brand = next((c for c in df.columns if clean_str(c).lower() == 'brand id'), 'Brand ID')
        col_prod = next((c for c in df.columns if "product" in c.lower()), 'Kode Product')

        count = 0
        for _, row in df.iterrows():
            kode_sales = clean_str(row.get(col_kode, '')).upper()
            if not kode_sales or kode_sales == 'NAN':
                continue

            deskripsi = clean_str(row.get(col_desk, '')) if col_desk else ''
            tipe_promo = clean_str(row.get(col_type, '')) if col_type else ''

            if not deskripsi and not tipe_promo:
                continue

            # Prioritaskan deskripsi promo panjang (HADIAH 1PCS FROSTBITE JASUKE, dsb)
            judul_promo = deskripsi if deskripsi else tipe_promo

            nama_sales, nama_spv = sales_map.get(kode_sales, ("-", "-"))
            setor = parse_int_clean(row.get(col_setor, 0))
            claim = parse_int_clean(row.get(col_claim, 0))

            tgl_raw = row.get(col_tgl, '')
            tgl_str = clean_str(str(tgl_raw).split(" ")[0]) if not pd.isna(tgl_raw) else "-"

            c.execute('''
                INSERT INTO promo_data (
                    kode_salesman, nama_salesman, nama_supervisor, brand_id, kode_product, promo_type_code,
                    deskripsi_promo, tanggal_posting, mid_hadiah, hadiah_value, jumlah_hadiah,
                    jumlah_claim, setor_hologram, fisik_real, selisih
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                kode_sales,
                nama_sales,
                nama_spv,
                clean_str(row.get(col_brand, '')),
                clean_str(row.get(col_prod, '')),
                tipe_promo,
                judul_promo,
                tgl_str,
                clean_str(row.get('MID Hadiah', '')),
                clean_str(row.get('Hadiah Value', '0')),
                clean_str(row.get('Jumlah Hadiah', '1')),
                claim,
                setor,
                0,
                0 - setor
            ))
            count += 1

        conn.commit()
        conn.close()
        return {"status": "success", "total_rows": count}
    except Exception as e:
        return JSONResponse(status_code=500, content={"message": f"Error: {str(e)}"})

@app.post("/api/save-group")
async def save_group(
    items_json: str = Form(...),
    kerapian_claim: int = Form(1),
    keterangan: str = Form(""),
    foto: Optional[UploadFile] = File(None)
):
    items = json.loads(items_json)
    if not items:
        return JSONResponse(status_code=400, content={"message": "Data kosong"})

    first_id = items[0]["id"]
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT foto_path FROM promo_data WHERE id = ?", (first_id,))
    row = c.fetchone()
    foto_path = row["foto_path"] if row else ""

    if foto and foto.filename:
        filename = f"sales_{first_id}_{foto.filename}"
        filepath = os.path.join(UPLOAD_DIR, filename)
        with open(filepath, "wb") as buffer:
            shutil.copyfileobj(foto.file, buffer)
        foto_path = f"/uploads/{filename}"

    for it in items:
        item_id = it["id"]
        fisik = int(it.get("fisik_real", 0))
        setor = int(it.get("setor_hologram", 0))
        selesai = int(it.get("selisih_selesai", 0))
        selisih = fisik - setor
        status = "Sesuai" if selisih == 0 else "Selisih"

        c.execute('''
            UPDATE promo_data 
            SET fisik_real = ?, selisih = ?, selisih_selesai = ?, 
                kerapian_claim = ?, keterangan = ?, foto_path = ?, status = ?
            WHERE id = ?
        ''', (fisik, selisih, selesai, kerapian_claim, keterangan, foto_path, status, item_id))

    conn.commit()
    conn.close()
    return {"status": "success", "foto_path": foto_path}

@app.get("/api/download-excel")
def download_excel():
    conn = get_db()
    df = pd.read_sql_query("SELECT * FROM promo_data", conn)
    conn.close()
    output_path = "rekap_verifikasi.xlsx"
    df.to_excel(output_path, index=False)
    return FileResponse(output_path, filename="rekap_verifikasi.xlsx")