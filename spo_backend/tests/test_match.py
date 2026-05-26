import sys
import os
sys.path.insert(0, os.path.abspath('spo_backend'))
from services import storage
scan = storage.read_misc('drive_scan_result')
print('Total keys:', len(scan.keys()))
print('First 10:', list(scan.keys())[:10])
