"""
tools/import_pending.py - CLI utilities for the registry.

  python tools/import_pending.py pdf                 # import the pending-persons PDF
  python tools/import_pending.py csv data/applicants.csv
  python tools/import_pending.py export              # dump registry -> data/applicants.csv
  python tools/import_pending.py numbers phones.csv  # bulk import whatsapp numbers
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import init_db                      # noqa: E402
import registry as R                              # noqa: E402
from config import PENDING_PDF, APPLICANTS_CSV    # noqa: E402


def main():
    init_db()
    cmd = sys.argv[1] if len(sys.argv) > 1 else "pdf"
    path = sys.argv[2] if len(sys.argv) > 2 else None

    if cmd == "pdf":
        print(R.import_pending("pdf", path or PENDING_PDF))
        p, n = R.export_applicants_csv()
        print(f"registry exported -> {p} ({n} rows). Fill in the 'whatsapp' column.")
    elif cmd == "csv":
        print(R.import_pending("csv", path or APPLICANTS_CSV))
    elif cmd == "export":
        p, n = R.export_applicants_csv(path)
        print(f"exported {n} rows -> {p}")
    elif cmd == "numbers":
        print({"updated": R.import_whatsapp_numbers(path)})
    elif cmd == "stats":
        print(R.stats())
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
