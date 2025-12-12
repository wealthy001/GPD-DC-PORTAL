# db_converter.py
import os
import sqlite3
import pandas as pd
from werkzeug.security import generate_password_hash


class DatabaseConverter:
    def __init__(self, database_path, upload_folder):
        self.database_path = database_path
        self.upload_folder = upload_folder
        self.allowed_extensions = {"xlsx", "xls", "csv"}
        os.makedirs(upload_folder, exist_ok=True)
        os.makedirs(os.path.dirname(database_path), exist_ok=True)

    def init_db(self):
        conn = sqlite3.connect(self.database_path)
        cur = conn.cursor()

        fields = '''
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            region TEXT,
            designation TEXT,
            name TEXT UNIQUE NOT NULL,
            kc_id TEXT,
            blw_zone TEXT,
            chapter TEXT,
            group_name TEXT,
            image_path TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        '''

        cur.execute(f"CREATE TABLE IF NOT EXISTS regional_pastors ({fields})")
        cur.execute(f"CREATE TABLE IF NOT EXISTS zonal_pastors ({fields})")
        cur.execute(f"CREATE TABLE IF NOT EXISTS group_pastors ({fields})")
        cur.execute(f"CREATE TABLE IF NOT EXISTS chapter_pastors ({fields})")
        cur.execute(f"CREATE TABLE IF NOT EXISTS rzm_pastors ({fields})")

        cur.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL
            )
        ''')

        cur.execute("SELECT id FROM users WHERE username = 'super'")
        if not cur.fetchone():
            cur.execute("INSERT INTO users (username, password) VALUES ('super', ?)",
                        (generate_password_hash('superuser'),))
            print("SUPER USER: super / superuser")

        conn.commit()
        conn.close()

    def add_image_path_column_if_missing(self):
        conn = sqlite3.connect(self.database_path)
        cur = conn.cursor()
        tables = ['regional_pastors', 'zonal_pastors', 'group_pastors', 'chapter_pastors', 'rzm_pastors']
        for table in tables:
            cur.execute(f"PRAGMA table_info({table})")
            columns = [row[1] for row in cur.fetchall()]
            if 'image_path' not in columns:
                cur.execute(f"ALTER TABLE {table} ADD COLUMN image_path TEXT")
        conn.commit()
        conn.close()

    def allowed_file(self, filename):
        return '.' in filename and filename.rsplit('.', 1)[1].lower() in self.allowed_extensions

    def map_columns(self, df):
        df = df.copy()
        df.columns = [str(c).lower().strip() for c in df.columns]
        mapping = {
            'region': ['region', 'area'],
            'designation': ['designation', 'title'],
            'name': ['name', 'full name', 'person'],
            'kc_id': ['kc id', 'kingschat number', 'kcid'],
            'blw_zone': ['zone', 'blw zone'],
            'chapter': ['chapter'],
            'group_name': ['group', 'group name']
        }
        result = pd.DataFrame()
        for target, sources in mapping.items():
            for src in sources:
                if src in df.columns:
                    result[target] = df[src]
                    break
            else:
                result[target] = ''
        result['name'] = result['name'].str.strip()
        return result

    def convert_excel_to_sql(self, filepath):
        try:
            df_dict = pd.read_excel(filepath, sheet_name=None)
            conn = sqlite3.connect(self.database_path)
            cur = conn.cursor()
            total = 0

            # AUTO SORT BY SHEET NAME
            for sheet_name, df in df_dict.items():
                df = df.dropna(how='all').fillna('')
                df_mapped = self.map_columns(df)

                table = 'regional_pastors'  # default
                s = sheet_name.lower()
                if any(x in s for x in ['regional', 'region', 'nigeria', 'west', 'south', 'east', 'europe', 'usa', 'canada', 'mid-east']):
                    table = 'regional_pastors'
                elif any(x in s for x in ['zonal', 'zone']):
                    table = 'zonal_pastors'
                elif any(x in s for x in ['group']):
                    table = 'group_pastors'
                elif any(x in s for x in ['chapter']):
                    table = 'chapter_pastors'
                elif any(x in s for x in ['rzm', 'dsp', 'special']):
                    table = 'rzm_pastors'

                inserted = 0
                for _, row in df_mapped.iterrows():
                    name = row['name']
                    if not name: continue
                    try:
                        cur.execute(f'''
                            INSERT INTO {table} 
                            (region, designation, name, kc_id, blw_zone, chapter, group_name)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                        ''', (
                            row['region'], row['designation'], name,
                            row['kc_id'], row['blw_zone'], row['chapter'], row['group_name']
                        ))
                        inserted += 1
                        total += 1
                    except sqlite3.IntegrityError:
                        pass  # duplicate skipped

                print(f"Sheet '{sheet_name}' → {table}: {inserted} records")

            conn.commit()
            conn.close()
            return {'success': True, 'records_inserted': total, 'message': f"{total} records added automatically"}
        except Exception as e:
            return {'success': False, 'error': str(e)}