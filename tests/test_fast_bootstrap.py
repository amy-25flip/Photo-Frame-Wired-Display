# SPDX-License-Identifier: GPL-2.0-or-later
import importlib.util,sys,types,unittest
from pathlib import Path
from unittest.mock import patch

class BootstrapTests(unittest.TestCase):
    def load_with(self,replies):
        spec=importlib.util.spec_from_file_location('bootstrap_test',Path(__file__).resolve().parents[1]/'v100display'/'fast_bootstrap.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        events=[]
        class USB:
            def read(self,*args,**kw):events.append('read');return replies.pop(0)
        raw=USB();device=types.SimpleNamespace(device=raw)
        class Session:
            def __init__(self,*args,**kw):pass
            def getinfo(self):events.append('identity')
            def upload(self,image):events.append(('upload',len(image)))
            def execute(self):events.append('execute')
        mods={'adfu_tool':types.ModuleType('adfu_tool'),
              'adfu_tool.device':types.SimpleNamespace(open_single_adfu=lambda:device),
              'adfu_tool.protocol':types.SimpleNamespace(Session=Session,SUCCESS_CSW=b'USBS'+bytes(9)),
              'adfu_tool.codec':types.SimpleNamespace(encode=lambda b:b)}
        with patch.dict(sys.modules,mods),patch.object(module.Path,'read_bytes',return_value=bytes(2048)):
            result=module.load()
        return result,raw,events
    def test_waits_for_ready_after_optional_csw(self):
        result,raw,events=self.load_with([b'USBS'+bytes(9),b'RDY1'+bytes(28)])
        self.assertIs(result,raw)
        self.assertEqual(events,['identity',('upload',2048),'execute','read','read'])
    def test_accepts_direct_ready(self):
        _,_,events=self.load_with([b'RDY1'+bytes(28)])
        self.assertEqual(events.count('read'),1)
    def test_rejects_wrong_response(self):
        with self.assertRaises(RuntimeError):self.load_with([b'bad'])

if __name__=='__main__':unittest.main()
