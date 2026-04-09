import sqlite3

db_path = r'C:\Users\czhou7\PythonProjects\irrigation\mdb_export\maxicom_integrated.db'
conn = sqlite3.connect(db_path)
c = conn.cursor()

# Check actual column names in SITE_CF
c.execute('PRAGMA table_info(SITE_CF)')
cols = [r[1] for r in c.fetchall()]
rain_cols = [x for x in cols if 'ain' in x.lower() or 'Rain' in x]
print('Rain-related columns:', rain_cols)

# Drop and recreate the v_site_summary view with correct column names
c.execute('DROP VIEW IF EXISTS v_site_summary')
c.execute('''
    CREATE VIEW v_site_summary AS
    SELECT 
        site.IndexNumber AS SiteID,
        site.IndexName AS SiteName,
        site.SiteNumber,
        site.SiteTimeZone,
        site.SiteWaterPricing,
        site.SiteWaterETCurrent,
        site.SiteWaterETDefault,
        (SELECT COUNT(*) FROM CTROL_CF ct WHERE ct.ControllerSiteNumber = site.IndexNumber) AS ControllerCount,
        (SELECT COUNT(*) FROM STATN_CF s WHERE s.StationSiteNumber = site.IndexNumber) AS StationCount,
        (SELECT COUNT(*) FROM SCHED_CF sc WHERE sc.ScheduleSiteNumber = site.IndexNumber) AS ScheduleCount
    FROM SITE_CF site
''')
conn.commit()
print('Fixed v_site_summary view')

# Test it
c.execute('SELECT * FROM v_site_summary LIMIT 5')
for row in c.fetchall():
    print(row)

conn.close()