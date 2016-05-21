import re
import unittest
import mudclientprotocol as mcp


class TestMcpMessage(unittest.TestCase):
    pkg = 'com-belfry-test'
    valdata = []

    def clearvals(self):
        self.valdata = []

    def appendval(self, val):
        self.valdata.append(val)

    def test_init(self):
        msg = mcp.McpMessage(self.pkg)
        self.assertIsNotNone(msg)
        self.assertEqual(len(msg), 0)
        self.assertEqual(msg.name, self.pkg)
        msg = mcp.McpMessage(self.pkg, foo=42, bar='Quack')
        self.assertIsNotNone(msg)
        self.assertEqual(len(msg), 2)
        self.assertEqual(msg.name, self.pkg)
        self.assertEqual(msg['foo'], 42)
        self.assertEqual(msg['bar'], 'Quack')

    def test_repr(self):
        msg = mcp.McpMessage(self.pkg, foo=42, bar='Quack')
        self.assertEqual(
            repr(msg),
            "<McpMessage('%s', bar='Quack', foo=42)>" % self.pkg
        )

    def test_in(self):
        msg = mcp.McpMessage(self.pkg, foo=42, bar='Quack')
        self.assertTrue('foo' in msg)
        self.assertFalse('flea' in msg)

    def test_index(self):
        msg = mcp.McpMessage(self.pkg, foo=42, bar='Quack')
        self.assertEqual(msg['foo'], 42)
        self.assertEqual(msg['bar'], 'Quack')
        self.assertEqual(msg.get('foo'), 42)
        self.assertEqual(msg.get('bar'), 'Quack')
        self.assertIsNone(msg.get('blah'))
        msg['blah'] = 'Zorch'
        self.assertEqual(msg.get('blah'), 'Zorch')

    def test_send(self):
        self.clearvals()
        msg = mcp.McpMessage(self.pkg, foo=42, bar='Quack')
        msg.send('AUTHSTR', self.appendval)
        self.assertEqual(
            self.valdata,
            ['#$#%s AUTHSTR bar: Quack foo: 42' % self.pkg]
        )

    def test_send_multiline(self):
        self.clearvals()
        msg = mcp.McpMessage(self.pkg, foo=42, bar='Quack\nQuack2')
        msg.send('AUTHSTR', self.appendval)
        pat = r'#\$#[a-z0-9_-]+ AUTHSTR bar\*: "" foo: 42 _data_tag: ([^ ]+)$'
        m = re.match(pat, self.valdata[0], re.I)
        self.assertTrue(m)
        data_tag = m.group(1)
        m = re.match(
            r'#\$#\* %s bar: Quack$' % data_tag,
            self.valdata[1], re.I
        )
        self.assertTrue(m)
        m = re.match(
            r'#\$#\* %s bar: Quack2$' % data_tag,
            self.valdata[2], re.I
        )
        self.assertTrue(m)
        m = re.match(r'#\$#: %s$' % data_tag, self.valdata[3], re.I)
        self.assertTrue(m)
