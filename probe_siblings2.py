"""兄弟端点第二轮：presigned 统一走 wrapper，POST 走各业务 host；修正 fitting/inpainting/remove-object 参数。"""
import json, sys, time, uuid
from pathlib import Path
import requests
sys.path.insert(0,'.')
from apero_client import AperoClient
requests.packages.urllib3.disable_warnings()
IMG=Path("D:/apk-analysis/fravix/in1.jpg").read_bytes()
W="https://api-img-gen-wrapper.aperogroup.ai"
H={"restore":"https://image-restore-core.aperogroup.ai","outpaint":"https://core-outpaint.aperogroup.ai",
   "objectrm":"https://objectremoval-core.aperogroup.ai","fitting":"https://fitting-core.aperogroup.ai"}
c=AperoClient(proxy="http://127.0.0.1:10808")
def up():
    l=c._req("GET",W+"/api/v5/presigned-link",headers=c.headers(),timeout=60).json()["data"]
    c._req("PUT",l["url"],data=IMG,headers={"Content-Type":"image/jpg"},timeout=90); return l["path"]
def call(tag,host,path,payload=None,files=None):
    t0=time.time()
    try:
        if files is not None:
            r=c._req("POST",H.get(host,W)+path,files=files,data=payload or {},headers={k:v for k,v in c.headers().items() if k.lower()!="content-type"},timeout=300)
        else:
            r=c._req("POST",H.get(host,W)+path,json=payload,headers=c.headers(),timeout=300)
        print(f"[{tag}] {r.status_code} {round((time.time()-t0)*1000)}ms :: {r.text[:260]}",flush=True)
        return {"tag":tag,"http":r.status_code,"body":r.text[:400],"ms":round((time.time()-t0)*1000)}
    except Exception as e:
        print(f"[{tag}] ERR {type(e).__name__} {e}",flush=True); return {"tag":tag,"error":str(e)[:200]}
res=[]
p=up()
res.append(call("restore","restore","/api/v5/image-restore",{"file":p}))
res.append(call("outpaint","outpaint","/api/v5/image-outpainting",{"file":p,"prompt":"extend the scene","upScale":0.5,"downScale":0.5,"leftScale":0.5,"rightScale":0.5,"guidanceScale":7}))
res.append(call("remove-bg","outpaint","/api/v5/remove-background",{"file":p}))
res.append(call("fitting-image","fitting","/api/v5/fitting",{"image":p,"prompt":"wear a blue shirt"}))
res.append(call("fitting-files","fitting","/api/v5/fitting",{"files":[p],"prompt":"wear a blue shirt"}))
# remove-object 需要 mask：再上传一张当 mask
l2=c._req("GET",W+"/api/v5/presigned-link",headers=c.headers(),timeout=60).json()["data"]
c._req("PUT",l2["url"],data=IMG,headers={"Content-Type":"image/jpg"},timeout=90)
res.append(call("remove-object","objectrm","/api/v5/remove-object",{"file":p,"mask":l2["path"]}))
# inpainting multipart
res.append(call("inpainting-mp","wrapper","/api/v1/image-inpainting",{"prompt":"remove the object","mask":l2["path"]}))
json.dump(res,open("probe_siblings2.json","w",encoding="utf8"),ensure_ascii=False,indent=1)
print("saved")
