import copy
from dataclasses import fields
import tempfile
import unittest
from astrbot_plugin_sharemarket.config import CFG
from astrbot_plugin_sharemarket.runtime import MarketRuntime

class RuntimeConfigTests(unittest.TestCase):
    def test_database_name_cannot_escape_state_directory(self):
        original=copy.deepcopy(CFG)
        try:
            with tempfile.TemporaryDirectory() as directory:
                for value in ('','.', '..', '../outside.sqlite', '/tmp/outside.sqlite', 'nested/db.sqlite', None):
                    with self.subTest(value=value), self.assertRaises(ValueError):
                        MarketRuntime(directory,options={'databaseName':value})
                runtime=MarketRuntime(directory,options={'databaseName':'test.sqlite'})
                self.assertEqual(runtime.db.path,str(runtime.path/'test.sqlite'))
        finally:
            for field in fields(CFG):setattr(CFG,field.name,getattr(original,field.name))
