from pyairtable import Api
from dotenv import load_dotenv
import os

load_dotenv()

api = Api(os.getenv("AIRTABLE_PAT"))
base_id = os.getenv("AIRTABLE_BASE_ID")
table_name = "Videos"

print("✅ Connected! Fetching records...")

table = api.table(base_id, table_name)
records = table.all(max_records=1)
print("🎉 Success!", records[0] if records else "No records found.")
