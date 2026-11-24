import contextlib
import copy
import http.client
import io
import json
import logging
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

import facekeys_server as f
from windows_input import WindowsInput


class FakeInput:
    def __init__(self):
        self.events = []
        self.process = "Game.EXE"

    def key(self, key, up=False):
        self.events.append(("key", key, up))

    def mouse(self, button, up=False):
        self.events.append(("mouse", button, up))

    def scroll(self, steps):
        self.events.append(("scroll", steps))

    def foreground(self):
        return self.process


class TestConfig(unittest.TestCase):
    def test_defaults(self):
        c = f.validate_config(f.starter_config())
        self.assertEqual(set(c['mappings']), {'blink','smile','frown','mouth','tongue'})
        self.assertEqual([(c['mappings'][k].get('button') or c['mappings'][k]['steps']) for k in ('blink','smile','frown','mouth','tongue')], ['left','right',1,-1,'middle'])
        self.assertFalse(c['restrict_foreground'])
        self.assertEqual(c['global_cooldown_ms'], 0)

    def test_version(self):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            with self.assertRaises(SystemExit) as cm:
                f.main(["--version"])
        self.assertEqual(cm.exception.code, 0)
        self.assertEqual(output.getvalue().strip(), "VN FaceKeys 0.2.0")

    def test_random_token(self):
        self.assertNotEqual(f.starter_config()['token'], f.starter_config()['token'])

    def test_invalid_fields(self):
        for field, value in [('port', True), ('restrict_foreground', 'false'), ('allowed_processes', ['C:\\x.exe']), ('token','短'*20), ('logging', {'level':'TRACE'}), ('listen','localhost'), ('global_cooldown_ms',-1)]:
            with self.subTest(field=field):
                c = f.starter_config(); c[field] = value
                with self.assertRaises(ValueError): f.validate_config(c)

    def test_action_validation(self):
        for spec in [{'type':'scroll','steps':0}, {'type':'scroll','steps':True}, {'type':'mouse','button':'oops'}, {'type':'hotkey','keys':['CTRL','CONTROL']}, {'type':'key','key':'INVALID'}, {'type':'mouse','count':4}, {'type':'key','key':'A','enabled':1}, {'type':'mouse','typo':1}, {'type':'sequence','steps':[{'type':'key','key':'A'}, {'type':'key','key':'???'}]}, {'type':'sequence','steps':[{'type':'wait','ms':2000}]*6}]:
            with self.subTest(spec=spec), self.assertRaises(ValueError): f.validate_action(spec,'test')

    def test_legacy_config(self):
        c = {'token':'X'*32, 'mappings':{'old':{'type':'scroll','steps':1}}}
        result = f.validate_config(c)
        self.assertFalse(result['restrict_foreground'])
        self.assertEqual(result['mappings']['old']['steps'], 1)

    def test_duplicate_json(self):
        with self.assertRaises(ValueError): f.parse_config(b'{"token":"a","token":"b"}')

    def test_check_does_not_create_or_inject(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/'config.json'
            with patch.object(f,'setup_logging'), patch.object(f,'WindowsInput') as win, contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(f.main(['--check','--config',str(path)]),1)
                self.assertFalse(path.exists())
                f.ensure_config(path)
                self.assertEqual(f.main(['--check','--config',str(path),'--loglevel','error']),0)
                win.assert_not_called()

    def test_instance_lock(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)/'instance'
            with f.instance_lock(p):
                with self.assertRaises(RuntimeError):
                    with f.instance_lock(p): pass
            with f.instance_lock(p): pass


class TestExecute(unittest.TestCase):
    def test_sequence_and_release_order(self):
        backend = FakeInput()
        spec = {'type':'sequence','steps':[{'type':'hotkey','keys':['CTRL','S']},{'type':'wait','ms':10},{'type':'scroll','steps':-2}]}
        f.validate_action(spec,'test')
        f.execute(spec,backend,sleep=lambda _:None)
        self.assertEqual(backend.events,[('key','CTRL',False),('key','S',False),('key','S',True),('key','CTRL',True),('scroll',-2)])

    def test_release_after_press_failure(self):
        backend = FakeInput(); original = backend.key
        def fail(key, up=False):
            if key == 'S' and not up: raise OSError('failure')
            original(key,up)
        backend.key = fail
        with self.assertRaises(OSError): f.execute({'type':'hotkey','keys':['CTRL','S']},backend)
        self.assertEqual(backend.events,[('key','CTRL',False),('key','CTRL',True)])

    def test_release_all_even_if_first_release_fails(self):
        backend = FakeInput(); original = backend.key
        def fail(key, up=False):
            original(key,up)
            if key == 'S' and up: raise OSError('failure')
        backend.key = fail
        with self.assertLogs(f.LOG,level='ERROR'), self.assertRaises(OSError):
            f.execute({'type':'hotkey','keys':['CTRL','S'],'hold_ms':0},backend)
        self.assertEqual(backend.events[-1],('key','CTRL',True))

    def test_native_wheel_encoding(self):
        # Test packing independently of the actual Win32 call.
        backend = WindowsInput.__new__(WindowsInput)
        events=[]; backend.send=events.append
        backend.scroll(1); backend.scroll(-1)
        self.assertEqual(events[0].data.mi.mouseData,120)
        self.assertEqual(events[1].data.mi.mouseData,2**32-120)
        self.assertEqual(events[0].data.mi.dwFlags,0x0800)


class TestState(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'config.json'; self.cfg=f.starter_config()
        self.write(); self.backend=FakeInput(); self.now=10
        self.state=f.State(f.ConfigStore(self.path),self.backend,clock=lambda:self.now)

    def write(self): self.path.write_text(json.dumps(self.cfg),encoding='utf-8')
    def call(self,path,method='POST',token=None):
        return self.state.response(method,path,self.cfg['token'] if token is None else token)

    def test_auth_and_status(self):
        self.assertEqual(self.call('/health','GET','bad')[0],403)
        self.assertEqual(self.call('/health','GET')[0],200)
        self.assertEqual(self.call('/status','GET')[1]['paused'],False)
        self.assertEqual(self.call('/action/nope')[0],404)

    def test_action_route_replaces_legacy_route(self):
        self.assertEqual(self.call('/press/blink')[0], 404)
        self.assertEqual(self.call('/action/blink', 'GET')[0], 404)
        self.assertEqual(self.backend.events, [])
        self.assertEqual(self.call('/action/blink')[0], 204)
        self.assertEqual(self.backend.events, [('mouse', 'left', False), ('mouse', 'left', True)])

    def test_pause_resume_toggle(self):
        self.assertEqual(self.call('/pause')[1]['paused'],True)
        self.assertEqual(self.call('/action/blink')[1]['status'],'paused')
        self.assertEqual(self.backend.events,[])
        self.assertEqual(self.call('/resume')[1]['paused'],False)
        self.assertEqual(self.call('/toggle')[1]['paused'],True)
        self.assertEqual(self.call('/toggle')[1]['paused'],False)
        self.assertEqual(self.call('/action/blink')[0],204)

    def test_cooldowns(self):
        self.cfg['global_cooldown_ms']=300; self.write()
        self.assertEqual(self.call('/action/blink')[0],204)
        self.assertEqual(self.call('/action/blink')[1]['status'],'cooldown')
        self.now+=.26
        self.assertEqual(self.call('/action/frown')[1]['status'],'global_cooldown')
        self.now+=.10
        self.assertEqual(self.call('/action/frown')[0],204)
        self.assertEqual(self.backend.events[-1],('scroll',1))

    def test_whitelist_explicit_switch(self):
        self.cfg['allowed_processes']=['other.exe']; self.write()
        self.assertEqual(self.call('/action/mouth')[0],204)
        self.cfg['restrict_foreground']=True; self.cfg['allowed_processes']=[]; self.write()
        self.assertEqual(self.call('/action/blink')[1]['status'],'foreground_blocked')
        self.cfg['allowed_processes']=['game.exe']; self.write()
        self.assertEqual(self.call('/action/blink')[0],204)
        self.backend.process=None
        self.assertEqual(self.call('/action/smile')[1]['status'],'foreground_blocked')

    def test_reload_invalid_then_recover_and_disable(self):
        self.path.write_text('{',encoding='utf-8')
        self.assertEqual(self.call('/action/blink')[0],503)
        self.assertEqual(self.backend.events,[])
        self.cfg['mappings']['blink']['enabled']=False; self.write()
        self.assertEqual(self.call('/action/blink')[1]['status'],'disabled')
        self.cfg['mappings']['blink']={'type':'scroll','steps':-2}; self.write()
        self.assertEqual(self.call('/action/blink')[0],204)
        self.assertEqual(self.backend.events,[('scroll',-2)])

    def test_token_reload(self):
        old=self.cfg['token']; self.cfg['token']='Z'*32; self.write()
        self.assertEqual(self.call('/health','GET',old)[0],403)
        self.assertEqual(self.call('/health','GET')[0],200)

    def test_dry_run_and_full_log(self):
        self.state.dry_run=True
        with self.assertLogs(f.LOG,level='INFO') as logs:
            self.assertEqual(self.call('/action/blink')[1]['status'],'simulated')
        self.assertTrue(any('"button":"left"' in line for line in logs.output))
        self.assertEqual(self.backend.events,[])

    def test_busy_drop(self):
        self.state.input_lock.acquire()
        try: self.assertEqual(self.call('/action/blink')[1]['status'],'busy')
        finally: self.state.input_lock.release()
        self.assertEqual(self.backend.events,[])

    def test_pause_interrupts_macro_at_next_step(self):
        self.cfg['mappings']['macro']={'type':'sequence','steps':[{'type':'scroll','steps':1},{'type':'scroll','steps':-1}]}; self.write()
        old=self.backend.scroll
        def pause_on_scroll(n):
            old(n); self.call('/pause')
        self.backend.scroll=pause_on_scroll
        self.assertEqual(self.call('/action/macro')[1]['status'],'paused')
        self.assertEqual(self.backend.events,[('scroll',1)])

    def test_sendinput_failure_not_success(self):
        self.backend.scroll=lambda _: (_ for _ in ()).throw(OSError('failed'))
        with self.assertLogs(f.LOG,level='ERROR'):
            self.assertEqual(self.call('/action/frown')[0],500)
        self.assertNotIn('frown',self.state.last_fire)

    def test_http_real_socket(self):
        with f.Server(('127.0.0.1',0),self.state) as server:
            t=threading.Thread(target=server.serve_forever,daemon=True); t.start()
            def req(method,path,headers=None,body=None):
                conn=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=3)
                try:
                    conn.request(method,path,body,headers or {})
                    r=conn.getresponse(); return r.status,r.read()
                finally: conn.close()
            try:
                h={'X-Api-Key':self.cfg['token']}
                self.assertEqual(req('GET','/health')[0],403)
                self.assertEqual(req('GET','/health',h)[0],200)
                self.assertEqual(req('POST','/action/mouth',h,b'{}'),(204,b''))
                self.assertEqual(req('POST','/action/blink',h,b'x'*4097)[0],413)
                self.assertEqual(req('POST','/action/blink',{**h,'Transfer-Encoding':'chunked'})[0],400)
                self.assertEqual(req('POST','/pause',h)[0],200)
                self.assertEqual(req('POST','/action/blink',h)[0],202)
            finally:
                server.shutdown(); t.join(3)


class TestLogging(unittest.TestCase):
    def test_rotation(self):
        with tempfile.TemporaryDirectory() as d, patch.object(f,'ROOT',Path(d)):
            old_handlers=list(f.LOG.handlers); old_level=f.LOG.level
            # Directly exercise rotation using a tiny test limit.
            f.setup_logging(True,{'level':'INFO','max_bytes':512,'backup_count':3})
            try:
                for i in range(100): f.LOG.info('x'*100)
                names={p.name for p in (Path(d)/'logs').iterdir()}
                self.assertEqual(names,{'facekeys.log','facekeys.log.1','facekeys.log.2','facekeys.log.3'})
            finally:
                for h in list(f.LOG.handlers): f.LOG.removeHandler(h); h.close()
                for h in old_handlers: f.LOG.addHandler(h)
                f.LOG.setLevel(old_level)


if __name__=='__main__': unittest.main()
