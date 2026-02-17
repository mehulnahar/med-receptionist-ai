import base64,sys
data=base64.b64decode(sys.argv[1])
open(r"D:\AI Reciptionackend\_e2e_test.py","wb").write(data)
print("Written",len(data),"bytes")
