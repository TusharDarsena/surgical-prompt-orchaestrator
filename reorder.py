import sys

path = r'c:\Users\TUSHAR\Desktop\surgical prompt orchaestrator\spo_frontend\pages\2_Source_Library.py'
with open(path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

sec1_start = 0
sec2_start = 0
sec3_start = 0

for i, line in enumerate(lines):
    if 'SECTION 1' in line and 'INDEX CARD CREATOR' in line:
        # Go up one line to catch the divider
        sec1_start = i - 1
    elif 'SECTION 2' in line and 'ADD SOURCE GROUP' in line:
        sec2_start = i - 1
    elif 'SECTION 3' in line and 'SOURCE LIBRARY BROWSER' in line:
        sec3_start = i - 1

if not (sec1_start and sec2_start and sec3_start):
    print(f"Error finding sections: s1={sec1_start}, s2={sec2_start}, s3={sec3_start}")
    sys.exit(1)

header = lines[:sec1_start]
sec1 = lines[sec1_start:sec2_start]
sec2 = lines[sec2_start:sec3_start]
sec3 = lines[sec3_start:]

# Modify the titles
for i, line in enumerate(sec3):
    if 'SECTION 3' in line and 'SOURCE LIBRARY BROWSER' in line:
        sec3[i] = '# SECTION 1 — SOURCE LIBRARY BROWSER (existing)\n'

for i, line in enumerate(sec2):
    if 'SECTION 2' in line and 'ADD SOURCE GROUP' in line:
        sec2[i] = '# SECTION 2 — ADD SOURCE GROUP (existing import tab + manual form)\n'

for i, line in enumerate(sec1):
    if 'SECTION 1' in line and 'INDEX CARD CREATOR' in line:
        sec1[i] = '# SECTION 3 — INDEX CARD CREATOR\n'

new_content = header + sec3 + sec2 + sec1

with open(path, 'w', encoding='utf-8') as f:
    f.writelines(new_content)

print(f"Successfully reordered. sec1:{sec1_start}, sec2:{sec2_start}, sec3:{sec3_start}")
