"""Install only pinned free CPU models/runtime, before exposing service credentials."""
import argparse
import hashlib
import os
from pathlib import Path
import shutil
import tarfile
import urllib.request
import zipfile

QWEN_REV='1cd86afb9a95c410a6038ab3b40d8b578c892266'
TURBO_REV='0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf'
SMALL_REV='536b0662742c02347bc0e980a01041f333bce120'
BINARIES={
 'nt':('llama-b11669-bin-win-cpu-x64.zip','37b3efcf962847ca869745fd4ccf7f5e7e8dacfeff9fa3523b4ca8cdc66d632b'),
 'posix':('llama-b11669-bin-ubuntu-x64.tar.gz','cf07c1c112d709bd67e522017471de57ed0ec8bea031d732c5422351c07f65ac')}

def sha(path):
 with Path(path).open('rb') as handle:return hashlib.file_digest(handle,'sha256').hexdigest()

def download(url,path,digest=None):
 path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
 if path.is_file() and (digest is None or sha(path)==digest):return
 temporary=path.with_suffix(path.suffix+'.downloading')
 with urllib.request.urlopen(url,timeout=45) as response,temporary.open('wb') as target:
  while chunk:=response.read(65536):target.write(chunk)
 if digest and sha(temporary)!=digest:raise RuntimeError('model_hash_mismatch')
 os.replace(temporary,path)

def install(folder):
 folder=Path(folder).resolve();folder.mkdir(parents=True,exist_ok=True)
 base='https://huggingface.co/Qwen/Qwen3-VL-4B-Instruct-GGUF/resolve/'+QWEN_REV+'/'
 download(base+'Qwen3VL-4B-Instruct-Q4_K_M.gguf',folder/'qwen3vl4b.gguf','66358cb18bb6b3b1b6675aa412c7a88ef01d228f481184d13668e5201c730a0a')
 download(base+'mmproj-Qwen3VL-4B-Instruct-Q8_0.gguf',folder/'mmproj.gguf','30ba2c7dd3127a4561b6cba9d13d0f711c91bdb38742e2f56d73c8cb596bd06d')
 for repo,rev,local,weight_sha in [
  ('mobiuslabsgmbh/faster-whisper-large-v3-turbo',TURBO_REV,'turbo','e76620f83d5f5b69efd3d87e3dc180c1bd21df9fbebacfd4335e5e1efcc018da'),
  ('Systran/faster-whisper-small',SMALL_REV,'small','3e305921506d8872816023e4c273e75d2419fb89b24da97b4fe7bce14170d671')]:
  vocabulary='vocabulary.txt' if local=='small' else 'vocabulary.json'
  for file in ('config.json','model.bin','tokenizer.json',vocabulary):
   download(f'https://huggingface.co/{repo}/resolve/{rev}/{file}',folder/local/file,weight_sha if file=='model.bin' else None)
 name,digest=BINARIES[os.name]
 archive=folder/name
 download('https://github.com/ggml-org/llama.cpp/releases/download/b11669/'+name,archive,digest)
 root=folder/'llama'
 marker=root/'verified-runtime.txt'
 if not marker.is_file() or marker.read_text()!=digest:
  root.mkdir(exist_ok=True)
  if os.name=='nt':
   with zipfile.ZipFile(archive) as bundle:
    for row in bundle.infolist():
     if not (root/row.filename).resolve().is_relative_to(root.resolve()):raise RuntimeError('unsafe_runtime_archive')
    bundle.extractall(root)
  else:
   with tarfile.open(archive) as bundle:bundle.extractall(root,filter='data')
   # Keep shared libraries next to the executable if the archive has a top directory.
   files=list(root.rglob('llama-server'))
   if len(files)!=1:raise RuntimeError('runtime_layout_invalid')
   if files[0].parent!=root:
    for path in files[0].parent.iterdir():
     if path.is_file():shutil.copy2(path,root/path.name)
  marker.write_text(digest)
 print('Free CPU quality models and runtime ready; no service credential used',flush=True)
 return folder

if __name__=='__main__':
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--dir',default='.tiktok14-models')
 install(parser.parse_args().dir)
