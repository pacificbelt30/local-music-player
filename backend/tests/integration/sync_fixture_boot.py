"""Container-only deterministic media adapter; production Celery/Redis/DB stay real.

Mounted by test_sync_lifecycle.py; never loaded by the application's normal entrypoint.
"""
import json
from pathlib import Path
import subprocess
import sys
import time
from urllib.parse import parse_qs, urlparse

from app.services import ytdlp_service

root = Path('/fixtures')


def playlist(url):
    pid = parse_qs(urlparse(url).query)['list'][0]
    entries = json.loads((root / f'{pid}.json').read_text())
    return {'playlist_id':pid,'playlist_title':pid,'entries':entries}


def download(*, youtube_id, base_path, audio_format="mp3", progress_hook=None, **kwargs):
    with (root/'events.jsonl').open('a') as file:
        file.write(json.dumps({'id':youtube_id,'event':'start'})+'\n')
    deadline = time.monotonic()+90
    while (root/f'hold-{youtube_id}').exists():
        if time.monotonic()>deadline: raise TimeoutError('fixture gate not released')
        if progress_hook: progress_hook({'status':'downloading','total_bytes':100,'downloaded_bytes':10})
        time.sleep(.1)
    path = Path(base_path)/f'{youtube_id}.{audio_format}'
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','sine=frequency=440:duration=0.2','-y',str(path)],check=True)
    with (root/'events.jsonl').open('a') as file:
        file.write(json.dumps({'id':youtube_id,'event':'end'})+'\n')
    return {'title':youtube_id,'file_path':str(path),'file_format':audio_format,'file_size_bytes':path.stat().st_size}


ytdlp_service.get_playlist_info = playlist
ytdlp_service.download_track = download

if sys.argv[1] == 'api':
    import uvicorn
    uvicorn.run('app.main:app',host='0.0.0.0',port=8000)
else:
    from app.tasks.celery_app import celery_app
    celery_app.worker_main(['worker','--loglevel=INFO','--concurrency=2','-Q','downloads,scheduler','--hostname=fixture@worker'])
