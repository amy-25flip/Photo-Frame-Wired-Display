# SPDX-License-Identifier: GPL-2.0-or-later
"""Regression checks for frame selection and the proven transition protocol."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]/'v100display'
spec=importlib.util.spec_from_file_location('transition',ROOT/'win_enter_adfu.py')
t=importlib.util.module_from_spec(spec);spec.loader.exec_module(t)

class StartupTests(unittest.TestCase):
    def test_frame_requires_exact_live_usb_ancestor(self):
        self.assertTrue(t.matches_frame([r'USBSTOR\DISK&VEN_ACTIONS',r'USB\VID_10D6&PID_1101\PORT1']))
        self.assertFalse(t.matches_frame([r'USBSTOR\DISK&VEN_ACTIONS',r'USB\VID_1234&PID_1101\PORT1']))
        self.assertFalse(t.matches_frame([r'USB\VID_10D6&PID_11010\PORT1']))
        self.assertFalse(t.matches_frame([]))

    def test_recovery_request_has_correct_big_endian_length(self):
        self.assertEqual(len(t.MODE_CDB),12)
        self.assertEqual(t.MODE_CDB[:2],b'\xcb\x21')
        self.assertEqual(int.from_bytes(t.MODE_CDB[7:9],'big'),2)
        self.assertEqual(t.MODE_CDB[9:],bytes(3))

    def transition(self,reply,identity='120155534244000000000000000000000000',arrival=(False,True)):
        calls=[]
        def scsi(path,cdb,*args):
            calls.append(bytes(cdb))
            if cdb[0]==0xcc:return dict(ok=True,status=0,data=identity)
            if cdb[0]==0xcb:return reply
            return dict(ok=True,status=0,data='')
        target={'DeviceID':r'\\.\PHYSICALDRIVE4','Volumes':[r'\\.\G:']}
        with patch.object(t,'frame_targets',return_value=[target]),patch.object(t,'adfu_present',side_effect=arrival),patch.object(t,'scsi',side_effect=scsi),patch.object(t.time,'sleep'):
            result=t.transition(lambda *args:None,wait=.01)
        return result,calls

    def test_zero_reply_is_not_success_and_never_ejects(self):
        ok,calls=self.transition(dict(ok=True,status=0,data='0000'),arrival=(False,))
        self.assertFalse(ok)
        self.assertNotIn(t.EJECT_CDB,calls)

    def test_timeout_is_not_success_and_never_ejects(self):
        ok,calls=self.transition(dict(ok=False,status=0,data='',error=121),arrival=(False,))
        self.assertFalse(ok)
        self.assertNotIn(t.EJECT_CDB,calls)

    def test_unrecognized_identity_never_gets_vendor_reboot(self):
        ok,calls=self.transition({},identity=bytes(18).hex(),arrival=(False,))
        self.assertFalse(ok)
        self.assertTrue(all(cmd[0]==0xcc for cmd in calls))

    def test_verified_arrival_after_ack_and_eject(self):
        ok,calls=self.transition(dict(ok=True,status=0,data='ff00'))
        self.assertTrue(ok)
        self.assertEqual(calls[-2:],[t.MODE_CDB,t.EJECT_CDB])

    def test_already_adfu_does_not_touch_storage(self):
        with patch.object(t,'adfu_present',return_value=True),patch.object(t,'frame_targets') as find:
            self.assertTrue(t.transition(lambda *args:None))
            find.assert_not_called()

if __name__=='__main__':unittest.main()
