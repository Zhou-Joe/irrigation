import win32com.client
import os

mdb_path = os.path.abspath(r'C:\Users\czhou7\PythonProjects\irrigation\Database\Maxicom2.mdb')
password = 'RLM6808'

print(f"Python bitness: {os.environ.get('PROCESSOR_ARCHITECTURE', 'unknown')}")
print(f"File exists: {os.path.exists(mdb_path)}")
print(f"File size: {os.path.getsize(mdb_path)} bytes")

# Try using DAO DBEngine directly (no Access GUI needed)
print("\n--- Attempting via DAO.DBEngine.36 ---")
try:
    db_engine = win32com.client.Dispatch("DAO.DBEngine.36")
    # OpenDatabase(DatabasePath, Exclusive, ReadOnly, ConnectString)
    # For password-protected Access, use connect string ";pwd=PASSWORD"
    db = db_engine.OpenDatabase(mdb_path, False, True, f";pwd={password}")
    
    print(f"Database opened successfully!")
    print(f"Table count: {db.TableDefs.Count}")
    
    for i in range(db.TableDefs.Count):
        table = db.TableDefs(i)
        if table.Name.startswith('MSys') or table.Name.startswith('~'):
            continue
        print(f"\n  === {table.Name} ===")
        
        fields = []
        for j in range(table.Fields.Count):
            field = table.Fields(j)
            fields.append(f"{field.Name}({field.Type})")
        print(f"    Fields: {', '.join(fields)}")
        
        # Get first 3 records
        try:
            rs = db.OpenRecordset(table.Name)
            count = 0
            while not rs.EOF and count < 3:
                vals = []
                for j in range(rs.Fields.Count):
                    vals.append(f"{rs.Fields(j).Name}={rs.Fields(j).Value}")
                print(f"    Row {count}: {', '.join(vals)}")
                rs.MoveNext()
                count += 1
            rs.Close()
        except Exception as ex:
            print(f"    (Error reading rows: {ex})")
    
    db.Close()
    print("\nSUCCESS!")

except Exception as e:
    print(f"DAO Error: {e}")
    
    # Try DAO.DBEngine.120
    print("\n--- Attempting via DAO.DBEngine.120 ---")
    try:
        db_engine = win32com.client.Dispatch("DAO.DBEngine.120")
        db = db_engine.OpenDatabase(mdb_path, False, True, f";pwd={password}")
        
        print(f"Database opened successfully!")
        print(f"Table count: {db.TableDefs.Count}")
        
        for i in range(db.TableDefs.Count):
            table = db.TableDefs(i)
            if table.Name.startswith('MSys') or table.Name.startswith('~'):
                continue
            print(f"\n  === {table.Name} ===")
            
            fields = []
            for j in range(table.Fields.Count):
                field = table.Fields(j)
                fields.append(f"{field.Name}({field.Type})")
            print(f"    Fields: {', '.join(fields)}")
            
            try:
                rs = db.OpenRecordset(table.Name)
                count = 0
                while not rs.EOF and count < 3:
                    vals = []
                    for j in range(rs.Fields.Count):
                        vals.append(f"{rs.Fields(j).Name}={rs.Fields(j).Value}")
                    print(f"    Row {count}: {', '.join(vals)}")
                    rs.MoveNext()
                    count += 1
                rs.Close()
            except Exception as ex:
                print(f"    (Error reading rows: {ex})")
        
        db.Close()
        print("\nSUCCESS!")
    except Exception as e2:
        print(f"DAO.120 Error: {e2}")