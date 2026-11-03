"""Opt-in real API + Celery + Redis + SQLite + FFmpeg container lifecycle tests.

SYNC_DOCKER_TESTS=1 SYNC_APP_TEST_IMAGE=<freshly-built-image> pytest -s ...
The remote YouTube/media boundary is deterministic; no real YouTube calls occur.
Only test-owned containers, network and temporary bind directories are touched.
"""
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.error
import urllib.request
import uuid

import pytest

pytestmark = pytest.mark.skipif(os.environ.get('SYNC_DOCKER_TESTS') != '1',reason='Opt-in Docker integration test')


def wait(check, timeout=35):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        try:
            result=check()
            if result:return result
        except (OSError,KeyError,subprocess.CalledProcessError):pass
        time.sleep(.15)
    raise AssertionError('container scenario did not complete before its deadline')


class Stack:
    def __init__(self,directory):
        self.root=directory; self.name='sync-test-'+uuid.uuid4().hex[:10]
        self.names=[]; self.image=os.environ['SYNC_APP_TEST_IMAGE']
        self.env={k:v for k,v in os.environ.items() if k not in ('DOCKER_HOST','DOCKER_CONTEXT','DOCKER_TLS','DOCKER_TLS_VERIFY','DOCKER_CERT_PATH')}
        for part in ('data','downloads','fixtures'):(directory/part).mkdir()
        self.docker('network','create',self.name)
    def docker(self,*args):
        return subprocess.check_output(['docker','--host=unix:///var/run/docker.sock',*args],env=self.env,text=True,stderr=subprocess.PIPE).strip()
    def run(self,node,*args):
        name=self.name+'-'+node
        if name not in self.names:self.names.append(name)
        return self.docker('run','-d','--name',name,'--network',self.name,'--network-alias',node,*args)
    def start(self):
        self.run('redis','redis:7-alpine')
        wait(lambda:self.docker('exec',self.name+'-redis','redis-cli','ping')=='PONG')
        self.start_app('api');self.start_app('worker')
    def start_app(self,node):
        args=[]
        for part in ('data','downloads','fixtures'):args+=['--mount',f'type=bind,src={self.root/part},dst=/{part}']
        args+=['--mount',f'type=bind,src={Path(__file__).with_name("sync_fixture_boot.py")},dst=/test-boot.py,readonly']
        for key,value in {'DATABASE_URL':'sqlite:////data/music.db','DATA_PATH':'/data','DOWNLOADS_PATH':'/downloads','REDIS_URL':'redis://redis:6379/0','REDIS_RESULT_BACKEND':'redis://redis:6379/1','SECRET_TOKEN':'','PYTHONPATH':'/app/backend','SYNC_LOCK_TIMEOUT_SECONDS':'6'}.items():args+=['-e',f'{key}={value}']
        if node=='api':args+=['-p',f'127.0.0.1:{getattr(self,"port","")}:8000']
        self.run(node,*args,self.image,'python','/test-boot.py',node)
        if node=='api':
            self.port=int(self.docker('port',self.name+'-api','8000/tcp').rsplit(':',1)[1]);wait(lambda:self.request('GET','/settings'))
        else:wait(lambda:self.docker('exec',self.name+'-api','python','-c',"from app.tasks.celery_app import celery_app; print(bool(celery_app.control.ping(timeout=1)))")=='True')
    def request(self,method,path,body=None):
        req=urllib.request.Request(f'http://127.0.0.1:{self.port}/api/v1{path}',method=method,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json'})
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req,timeout=10) as response:
            data=response.read();return json.loads(data) if data else None
    def remote(self,pid,ids):
        file=self.root/'fixtures'/f'{pid}.json';tmp=file.with_suffix('.tmp')
        tmp.write_text(json.dumps([{'youtube_id':vid,'title':vid,'position':i} for i,vid in enumerate(ids)]));tmp.replace(file)
    def hold(self,vid):p=self.root/'fixtures'/f'hold-{vid}';p.touch();return p
    def starts(self,vid):
        path=self.root/'fixtures'/'events.jsonl'
        return sum(json.loads(line)=={'id':vid,'event':'start'} for line in path.read_text().splitlines()) if path.exists() else 0
    def add(self,pid):return self.request('POST','/youtube/syncs',{'source_type':'url','source_url':f'https://www.youtube.com/playlist?list={pid}'})
    def tracks(self,sync):return self.request('GET',f'/youtube/syncs/{sync["id"]}/tracks')
    def send_track(self,track):
        code="from app.tasks.celery_app import celery_app; celery_app.send_task('app.tasks.sync_playlist.download_playlist_sync_track',args=["+str(track)+"],queue='downloads')"
        self.docker('exec',self.name+'-api','python','-c',code)
    def restart(self,node):
        self.docker('rm','-f',self.name+'-'+node);self.start_app(node)
    def clean(self):
        for name in self.names:
            result=subprocess.run(["docker","--host=unix:///var/run/docker.sock","logs","--tail","200",name],env=self.env,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
            (self.root/(name+".log")).write_text(result.stdout)
        for name in reversed(self.names):
            try:self.docker('rm','-f',name)
            except subprocess.CalledProcessError:pass
        self.docker('network','rm',self.name)
        # Test-owned bind mounts may have been written by the image's root user.
        self.docker('run','--rm','--mount',f'type=bind,src={self.root},dst=/test-data','--entrypoint','sh',self.image,'-c',f'chown -R {os.getuid()}:{os.getgid()} /test-data')


@pytest.fixture(scope='module')
def stack(tmp_path_factory):
    if not os.environ.get('SYNC_APP_TEST_IMAGE'):pytest.fail('Set SYNC_APP_TEST_IMAGE to a freshly built application image')
    stack=Stack(tmp_path_factory.mktemp('sync-stack'))
    try:
        stack.start();yield stack
    finally:stack.clean()


def test_simultaneous_manual_and_worker_tasks_download_once(stack):
    gate=stack.hold('duplicate');stack.remote('PLduplicate',['duplicate']);sync=stack.add('PLduplicate')
    wait(lambda:stack.starts('duplicate')==1)
    track=stack.tracks(sync)[0]
    for _ in range(2):
        stack.request('POST',f'/youtube/syncs/{sync["id"]}/run');stack.send_track(track['id'])
    # Redis proves that renewed leases remain held beyond one TTL.
    wait(lambda:stack.docker('exec',stack.name+'-redis','redis-cli','ttl',f'lmp:playlist-track:{track["id"]}') not in ('-1','-2'))
    time.sleep(7)
    assert stack.starts('duplicate')==1
    gate.unlink();wait(lambda:stack.tracks(sync)[0]['status']=='complete')
    assert len(list((stack.root/'downloads'/'PLduplicate').glob('*.mp3')))==1


def test_pause_leaves_queued_track_for_resume_and_manual_run_works(stack):
    stack.remote('PLpause',[]);sync=stack.add('PLpause')
    stack.request('PATCH',f'/youtube/syncs/{sync["id"]}',{'enabled':False})
    stack.remote('PLpause',['manual-paused'])
    stack.request('POST',f'/youtube/syncs/{sync["id"]}/run')
    wait(lambda:stack.tracks(sync) and stack.tracks(sync)[0]['status']=='complete')
    assert stack.starts('manual-paused')==1
    assert not next(s for s in stack.request('GET','/youtube/syncs') if s['id']==sync['id'])['enabled']
    code = "from app.database import SessionLocal; from app.models import PlaylistSyncTrack; from app.tasks.sync_playlist import enqueue_playlist_track; s=SessionLocal(); t=PlaylistSyncTrack(playlist_sync_id="+str(sync['id'])+",youtube_id='queued-paused',title='Queued',status='pending'); s.add(t); s.commit(); enqueue_playlist_track(s,t); print(t.celery_task_id)"
    task_id=stack.docker('exec',stack.name+'-api','python','-c',code).splitlines()[-1]
    wait(lambda:stack.docker('exec',stack.name+'-api','python','-c',"from app.tasks.celery_app import celery_app; print(celery_app.AsyncResult('"+task_id+"').ready())")=='True')
    assert stack.starts('queued-paused')==0
    stack.remote('PLpause',['manual-paused','queued-paused'])
    stack.request('PATCH',f'/youtube/syncs/{sync["id"]}',{'enabled':True})
    stack.request('POST',f'/youtube/syncs/{sync["id"]}/run')
    wait(lambda:len(stack.tracks(sync))==2 and all(t['status']=='complete' for t in stack.tracks(sync)))
    assert stack.starts('queued-paused')==1


def test_api_and_worker_recreation_preserve_settings_and_recover_interrupted_download(stack):
    gate=stack.hold('restart');stack.remote('PLrestart',['restart']);sync=stack.add('PLrestart')
    wait(lambda:stack.starts('restart')==1);track=stack.tracks(sync)[0]
    stack.request('PATCH','/settings',{'default_audio_quality':'320'})
    stack.restart('worker');stack.restart('api')
    assert stack.request('GET','/settings')['default_audio_quality']=='320'
    # Dead worker locks expire without deleting unrelated Redis keys.
    wait(lambda:stack.docker('exec',stack.name+'-redis','redis-cli','exists',f'lmp:playlist-track:{track["id"]}')=='0')
    gate.unlink();stack.request('POST',f'/youtube/syncs/{sync["id"]}/run')
    wait(lambda:stack.tracks(sync)[0]['status']=='complete')
    assert stack.starts('restart')==2
    assert len(list((stack.root/'downloads'/'PLrestart').glob('*.mp3')))==1


def test_delete_during_download_does_not_resurrect_files_or_rows(stack):
    gate=stack.hold('delete');stack.remote('PLdelete',['delete']);sync=stack.add('PLdelete')
    wait(lambda:stack.starts('delete')==1)
    stack.request('DELETE',f'/youtube/syncs/{sync["id"]}?delete_files=true');gate.unlink()
    directory=stack.root/'downloads'/'PLdelete'
    wait(lambda:not list(directory.glob('.lmp-*')))
    assert not list(directory.glob('*.mp3'))
    assert not any(s['id']==sync['id'] for s in stack.request('GET','/youtube/syncs'))


def test_batch_profile_history_and_retained_restore_through_real_api(stack):
    stack.remote('PLexperience',['profile-first','profile-second'])
    profile=stack.request('POST','/workspace/profiles',{'name':'My phone','audio_format':'m4a','audio_quality':'192'})
    plan=stack.request('POST','/workspace/intake/preview',{'text':'https://www.youtube.com/playlist?list=PLexperience','profile_id':profile['id']})
    result=stack.request('POST','/workspace/intake/commit',{'token':plan['token'],'indices':[0]})
    sync={'id':result['results']['0']['id']}
    wait(lambda:len(stack.tracks(sync))==2 and all(t['status']=='complete' for t in stack.tracks(sync)))
    directory=stack.root/'downloads'/'PLexperience'
    assert len(list(directory.glob('*.m4a')))==2
    stack.remote('PLexperience',['profile-first']);stack.request('POST',f'/youtube/syncs/{sync["id"]}/run')
    wait(lambda:len(stack.tracks(sync))==1)
    history=stack.request('GET',f'/workspace/syncs/{sync["id"]}/history')
    removed=history['retained'][0];assert removed['file_retained']
    assert stack.request('POST',f'/workspace/syncs/{sync["id"]}/tracks/{removed["id"]}/restore')['redownload'] is False
    stack.request('POST',f'/youtube/syncs/{sync["id"]}/run')
    wait(lambda:len(stack.tracks(sync))==2)
    state=stack.request('POST','/workspace/profiles/-2/preview',{'sync_ids':[sync['id']]})
    assert state['redownload_count']==2
    stack.request('POST','/workspace/profiles/apply',{'token':state['token']})
    wait(lambda:all(t['status']=='complete' and t['file_format']=='flac' for t in stack.tracks(sync)))
    assert len(list(directory.glob('*.m4a')))==2 # Previous formats are retained.
    assert len(list(directory.glob('*.flac')))==2
    assert stack.request('GET',f'/workspace/syncs/{sync["id"]}/history')['events'][0]['kind']=='profile'


def test_progress_stream_does_not_hold_other_api_requests_while_redis_waits(stack):
    code = "from app.database import SessionLocal; from app.models import DownloadJob; from app.api.queue import _redis; s=SessionLocal(); jobs=[DownloadJob(youtube_id=f'perf-stream-{i}',status='pending') for i in range(20)]; s.add_all(jobs); s.commit(); _redis.mset({f'job:{j.id}:progress':'45' for j in jobs}); s.close()"
    stack.docker('exec',stack.name+'-api','python','-c',code)
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(f'http://127.0.0.1:{stack.port}/api/v1/queue/events',timeout=10) as stream:
        assert stream.headers['X-Accel-Buffering']=='no'
        events=json.loads(stream.readline().decode().removeprefix('data: '))
        selected=[event for event in events if event['youtube_id'].startswith('perf-stream-')]
        assert len(selected)==20 and all(event['progress_pct']==45 for event in selected)
        stream.readline() # SSE blank separator
        stack.docker('exec',stack.name+'-redis','redis-cli','CLIENT','PAUSE','5000','ALL')
        time.sleep(1.3) # The next SSE tick is now waiting for Redis.
        started=time.monotonic()
        assert isinstance(stack.request('GET','/youtube/syncs'),list)
        elapsed=time.monotonic()-started
        assert elapsed<2, f'API blocked by progress stream for {elapsed:.2f}s'
        assert stream.readline().startswith(b'data: ')
    stack.docker('exec',stack.name+'-api','python','-c',"from app.database import SessionLocal; from app.models import DownloadJob; s=SessionLocal(); s.query(DownloadJob).filter(DownloadJob.youtube_id.like('perf-stream-%')).delete(synchronize_session=False); s.commit(); s.close()")


def test_large_sync_details_use_bounded_pages_and_search_on_real_database(stack):
    code = "from app.database import SessionLocal; from app.models import YoutubePlaylistSync,PlaylistSyncTrack; s=SessionLocal(); p=YoutubePlaylistSync(playlist_id='PLlargepages',playlist_name='Large page test',enabled=False); s.add(p); s.flush(); s.add_all([PlaylistSyncTrack(playlist_sync_id=p.id,youtube_id=f'pg-{i}',title=f'Track {i}',artist='Artist',position=i,status='failed' if i%3==0 else 'complete') for i in range(6000)]); s.commit(); print(p.id); s.close()"
    sid=int(stack.docker('exec',stack.name+'-api','python','-c',code).splitlines()[-1])
    first=stack.request('GET',f'/youtube/syncs/{sid}/tracks/page')
    second=stack.request('GET',f'/youtube/syncs/{sid}/tracks/page?offset=50')
    assert first['total']==second['total']==6000
    assert len(first['items'])==len(second['items'])==50
    assert not set(t['id'] for t in first['items'])&set(t['id'] for t in second['items'])
    selected=stack.request('GET',f'/youtube/syncs/{sid}/tracks/page?search=99&status=failed')
    assert selected['total']>0
    assert all('99' in t['title'] and t['status']=='failed' for t in selected['items'])
    assert len(stack.request('GET',f'/youtube/syncs/{sid}/tracks'))==6000
