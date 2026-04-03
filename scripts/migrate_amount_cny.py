"""Migrate amount_usd column to amount_cny in funding_events table."""
import sqlite3

conn = sqlite3.connect('data/fund_job_radar.db')
cursor = conn.cursor()

# 1. Add new column amount_cny
cursor.execute('ALTER TABLE funding_events ADD COLUMN amount_cny REAL NOT NULL DEFAULT 0')

# 2. Migrate data from amount_usd to amount_cny
cursor.execute('UPDATE funding_events SET amount_cny = amount_usd')

# 3. Recreate table without amount_usd column
cursor.execute('''
CREATE TABLE funding_events_new (
    id TEXT PRIMARY KEY,
    company_name TEXT NOT NULL,
    company_domain TEXT DEFAULT "",
    round_type TEXT NOT NULL,
    amount_cny REAL NOT NULL,
    announcement_date DATETIME NOT NULL,
    investors TEXT DEFAULT "",
    source_url TEXT DEFAULT "",
    source TEXT NOT NULL,
    industry_group TEXT DEFAULT "",
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
)
''')

# 4. Copy data to new table
cursor.execute('''
INSERT INTO funding_events_new 
SELECT id, company_name, company_domain, round_type, amount_cny, 
       announcement_date, investors, source_url, source, industry_group, created_at 
FROM funding_events
''')

# 5. Drop old table
cursor.execute('DROP TABLE funding_events')

# 6. Rename new table
cursor.execute('ALTER TABLE funding_events_new RENAME TO funding_events')

# 7. Rebuild indexes
cursor.execute('CREATE INDEX IF NOT EXISTS idx_funding_announcement ON funding_events(announcement_date)')
cursor.execute('CREATE INDEX IF NOT EXISTS idx_funding_company ON funding_events(company_name)')
cursor.execute('CREATE INDEX IF NOT EXISTS idx_funding_source ON funding_events(source)')

conn.commit()

# Verify
cursor.execute('PRAGMA table_info(funding_events)')
print('New schema:')
for row in cursor.fetchall():
    print(f'  {row[1]} {row[2]}')

cursor.execute('SELECT id, company_name, amount_cny, source FROM funding_events LIMIT 3')
print('\nSample data:')
for row in cursor.fetchall():
    print(f'  {row}')

conn.close()
print('\nMigration complete.')
