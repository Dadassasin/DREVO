from pathlib import Path
import subprocess,zipfile,hashlib,shutil

root=Path(__file__).resolve().parent.parent
portable=Path('F:/Архив/.drevo')
assert (portable/'drevo.sqlite3').is_file()
names=subprocess.check_output(['git','ls-files','-z'],cwd=root).decode('utf-8').split('\0')
for name in filter(None,names):
    assert not any(part in ('.local','.venv','node_modules','.vercel') for part in Path(name).parts)
    assert Path(name).name not in ('.env','.env.local','server.env','signing.key','drevo.sqlite3')
archive=portable/'app-source.zip'
temp=portable/'app-source.zip.new'
with zipfile.ZipFile(temp,'w',zipfile.ZIP_DEFLATED) as package:
    for name in filter(None,names): package.write(root/name,name)
with zipfile.ZipFile(temp) as package:
    assert package.testzip() is None
    assert 'scripts/start_online.ps1' in package.namelist()
    count=len(package.namelist())
temp.replace(archive)
with archive.open('rb') as stream: checksum=hashlib.file_digest(stream,'sha256').hexdigest()
(portable/'app-source.sha256').write_text(checksum,encoding='ascii')
shutil.copyfile(root/'scripts/setup_second_pc.ps1',portable/'setup_second_pc.ps1')
shutil.copyfile(root/'docs/TWO-PCS.md',portable/'README.md')
wrapper='@echo off\r\nchcp 65001 >nul\r\npowershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0.drevo\\setup_second_pc.ps1"\r\npause\r\n'
(portable.parent/'Установить ДРЕВО на этом ПК.bat').write_bytes(wrapper.encode('ascii'))
print({'bundle':str(archive),'files':count,'bytes':archive.stat().st_size,'integrity':'ok'})
