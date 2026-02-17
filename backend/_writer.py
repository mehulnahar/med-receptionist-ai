import sys, base64
with open("D:/AI Reciption/backend/_e2e_test.py", "wb") as f:
    for line in sys.stdin:
        f.write(base64.b64decode(line.strip()))
print("Done")
