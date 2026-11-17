"""Rename verified downloads while retaining package contents."""
import hashlib,json,os,subprocess,tempfile
from pathlib import Path
from make_repository import make
PAIRS=[('PlexConfigControlQuTShero_1.6.qpkg','PlexConfigControl_QuTShero_x86-64v1.6.qpkg','c60d72b13e3a5bca79454068a95e7bea39635b01d1566f6af888f0a89eac0376','SHA256SUMS_QNAP'),('PlexConfigControlTrueNAS_1.6.zip','PlexConfigControl_TrueNAS_x86-64v1.6.zip','3478321b33614b41c4d771eb725d7a64b760a4e15bdfc6eea4c7e226d8af566b','SHA256SUMS')]
def gh(*args):return subprocess.check_output(['gh',*args],text=True)
def main():
 repo=os.environ['GH_REPO']
 assets={a['name']:a for a in json.loads(gh('release','view','v1.6','--json','assets'))['assets']}
 with tempfile.TemporaryDirectory() as folder:
  out=Path(folder)
  for old,new,digest,_ in PAIRS:
   name=new if new in assets else old
   gh('release','download','v1.6','--pattern',name,'--dir',folder)
   path=out/name
   if hashlib.sha256(path.read_bytes()).hexdigest()!=digest:raise RuntimeError('Unexpected package '+name)
   if name!=new:path.rename(out/new)
  for old,new,digest,checksum in PAIRS:
   if new not in assets:gh('api',f"repos/{repo}/releases/assets/{assets[old]['id']}",'--method','PATCH','-f','name='+new)
   (out/checksum).write_text(digest+'  '+new+'\n')
  make(out/PAIRS[0][1],out/'qnap-repository.xml','en')
  make(out/PAIRS[0][1],out/'qnap-repository-pl.xml','pl')
  gh('release','upload','v1.6',*(str(out/n) for n in ('SHA256SUMS','SHA256SUMS_QNAP','qnap-repository.xml','qnap-repository-pl.xml')),'--clobber')
  gh('release','edit','v1.6','--notes-file',str(Path(__file__).resolve().parents[1]/'release-notes-1.6.md'))
  final={a['name']:a for a in json.loads(gh('release','view','v1.6','--json','assets'))['assets']}
  for _,name,digest,_ in PAIRS:assert final[name]['digest']=='sha256:'+digest
  print('Both downloads renamed; original package hashes confirmed; descriptions, checksums and feeds updated.')
if __name__=='__main__':main()
