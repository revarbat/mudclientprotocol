import os
import copy
import base64


registered_packages = {}


class McpError(Exception):
    pass


class McpCordError(McpError):
    pass


def mktoken():
    s = base64.b64encode(os.urandom(9)).decode()
    return s.replace('+', '_').replace('/', '_')


def vers_cmp(a, b):
    a = [int(x) for x in a.split('.', 1)]
    b = [int(x) for x in b.split('.', 1)]
    return (a > b) - (a < b)


def max_shared_version(amin, amax, bmin, bmax):
    if vers_cmp(amax, bmin) < 0:
        return None
    if vers_cmp(bmax, amin) < 0:
        return None
    return amax if vers_cmp(amax, bmax) < 0 else bmax


class McpMessage(dict):
    def __init__(self, name, **kwargs):
        self.name = name
        dict.__init__(self, **kwargs)

    def __repr__(self):
        kws = ", ".join(
            [
                "%s=%s" % (k, repr(self[k]))
                for k in sorted(list(self.keys()))
            ]
        )
        if kws:
            kws = ", " + kws
        return "<McpMessage('%s'%s)>" % (self.name, kws)

    def _normalize_args(self):
        mults = []
        outdata = {}
        for key, val in self.items():
            if isinstance(val, str):
                if "\n" in val:
                    val = val.split("\n")
            elif not isinstance(val, list):
                val = str(val)
            outdata[key] = val
            if isinstance(val, list):
                mults.append(key)
        return (outdata, mults)

    def _quote(self, key, val):
        if isinstance(val, list):
            key += '*'
            val = ""
        if not val or " " in val or '"' in val or '\\' in val:
            val = val.replace('\\', '\\\\')
            val = val.replace('"', '\\"')
            val = '"%s"' % val
        return "%s: %s" % (key, val)

    def send(self, auth, write_cb):
        out = "#$#%s " % self.name
        if auth:
            out += "%s " % auth
        (outdata, mults) = self._normalize_args()
        out += " ".join(
            [self._quote(k, outdata[k]) for k in sorted(list(outdata.keys()))]
        )
        if mults:
            data_tag = mktoken()
            out += ' ' + self._quote('_data_tag', data_tag)
        write_cb(out)
        for key in sorted(mults):
            lines = outdata[key]
            for line in lines:
                if not isinstance(line, str):
                    line = str(line)
                write_cb("#$#* %s %s: %s" % (data_tag, key, line))
        if mults:
            write_cb("#$#: %s" % data_tag)

    def get(self, key, dflt=None, type_=None):
        val = dict.get(self, key, dflt)
        try:
            if type_ is not None:
                val = type_(val)
        except ValueError:
            val = dflt
        return val


class McpPackage(object):
    def __init__(self, name, minver, maxver):
        self.name = name
        self.minver = minver
        self.maxver = maxver
        self.connection = None
        self.negotiated_version = None
        registered_packages[name] = self

    def process_message(self, msg):
        pass


class McpNegotiatePkg(McpPackage):
    def __init__(self):
        McpPackage.__init__(self, 'mcp-negotiate', '1.0', '2.0')

    def process_message(self, msg):
        con = self.connection
        if msg.name == 'mcp-negotiate-end':
            msg = McpMessage('mcp-negotiate-end')
            con.negotiated = True
        elif msg.name == 'mcp-negotiate-can':
            try:
                pkgname = msg['package']
                minver = msg['min-version']
                maxver = msg['max-version']
            except:
                return
            if pkgname not in registered_packages:
                return
            pkg = registered_packages[pkgname]
            ver = max_shared_version(pkg.minver, pkg.maxver, minver, maxver)
            if not ver:
                return
            conpkg = copy.copy(pkg)
            conpkg.connection = con
            conpkg.negotiated_version = ver
            con.supported_packages[pkgname] = conpkg
            if not con.is_server:
                msg = McpMessage('mcp-negotiate-can', package=pkgname)
                msg['min-version'] = pkg.minver
                msg['max-version'] = pkg.maxver
                con.send_message(msg)

    def advertise_packages(self):
        con = self.connection
        msg = McpMessage('mcp-negotiate-can', package='mcp-negotiate')
        msg['min-version'] = '1.0'
        msg['max-version'] = '2.0'
        con.send_message(msg)
        for pkgname, pkg in registered_packages.items():
            if pkgname == 'mcp-negotiate':
                continue
            msg = McpMessage('mcp-negotiate-can', package=pkgname)
            msg['min-version'] = pkg.minver
            msg['max-version'] = pkg.maxver
            con.send_message(msg)
        msg = McpMessage('mcp-negotiate-end')
        con.send_message(msg)

McpNegotiatePkg()


class McpCordPkg(McpPackage):
    def __init__(self):
        self.open_cords = {}
        self.cord_handlers = {}
        McpPackage.__init__(self, 'mcp-cord', '1.0', '1.0')

    def process_message(self, msg):
        if msg.name == 'mcp-cord-open':
            cord_id = msg['_id']
            cord_type = msg['_type']
            if cord_type not in self.cord_handlers:
                return
            handler = self.cord_handlers[cord_type]
            self.open_cords[cord_id] = handler
            handler.opened(cord_id, cord_type)
        elif msg.name == 'mcp-cord':
            cord_id = msg['_id']
            if cord_id not in self.open_cords:
                return
            cord_msg = msg['_message']
            cord_args = dict(msg)
            del cord_args['_id']
            del cord_args['_message']
            handler = self.open_cords[cord_id]
            handler.received(cord_id, cord_msg, cord_args)
        elif msg.name == 'mcp-cord-close':
            cord_id = msg['_id']
            if cord_id not in self.open_cords:
                return
            handler = self.open_cords[cord_id]
            handler.closed(cord_id)
            del self.open_cords[cord_id]

    def register_cord_handler(self, cord_type, callback):
        if cord_type in self.cord_handlers:
            raise McpCordError(
                "Cord handler alrady exists for '%s'"
                % cord_type
            )
        self.cord_handlers[cord_type] = callback

    def open_cord(self, cord_type, handler=None):
        cord_id = mktoken()
        if handler:
            self.open_cords[cord_id] = handler
        elif cord_type in self.cord_handlers:
            handler = self.cord_handlers[cord_type]
            self.open_cords[cord_id] = handler
        con = self.connection
        msg = McpMessage('mcp-cord-open', _id=cord_id, _type=cord_type)
        con.send_message(msg)

    def close_cord(self, cord_id):
        if cord_id not in self.open_cords:
            return
        con = self.connection
        msg = McpMessage('mcp-cord-close', _id=cord_id)
        con.send_message(msg)
        del self.open_cords[cord_id]

    def send_message(self, cord_id, mesg, argsdict):
        if cord_id not in self.open_cords:
            return
        con = self.connection
        msg = McpMessage('mcp-cord', _id=cord_id, _message=mesg)
        for k, v in argsdict.items():
            msg[k] = v
        con.send_message(msg)

McpCordPkg()


class McpConnection(object):
    def __init__(self, write_cb, is_server=False):
        self.write_cb = write_cb
        self.is_server = is_server
        self.partials = {}
        self.supported_packages = {}
        self.negotiated = False
        self.auth_key = None
        negpkg = copy.copy(registered_packages['mcp-negotiate'])
        negpkg.connection = self
        negpkg.negotiated_version = '1.0'
        self.supported_packages[negpkg.name] = negpkg

    def startup(self):
        self.partials = {}
        self.negotiated = False
        self.auth_key = None
        if self.is_server:
            self.write_cb('#$#mcp version: 2.1 to: 2.1')

    def process_input(self, line):
        if line.startswith('#$"'):
            return line[3:]
        if line.startswith('#$#'):
            msg = self.parse_line(line)
            if msg.name == 'mcp':
                self._negotiate_startup(msg)
                return None
            longest = None
            for pkgname, pkg in self.supported_packages.items():
                if msg.name == pkgname or msg.name.startswith(pkgname + '-'):
                    if not longest or len(pkgname) > len(longest):
                        longest = pkgname
            if longest:
                pkg = self.supported_packages[longest]
                pkg.process_message(msg)
            return None
        return line

    def _negotiate_startup(self, msg):
        try:
            ver = msg['version']
            to = msg['to']
            if vers_cmp(ver, '2.1') > 0 or vers_cmp(to, '2.1') < 0:
                # Version out of range.
                return
        except ValueError:
            # Malformed version.
            return
        if self.is_server:
            self.auth_key = msg['authentication-key']
            negpkg = self.supported_packages['mcp-negotiate']
            negpkg.advertise_packages(self)
        else:
            self.auth_key = mktoken()
            self.write_cb(
                '#$#mcp authentication-key: %s version: 2.1 to: 2.1'
                % self.auth_key
            )

    def write_inband(self, line):
        if line.startswith('#$#'):
            line = '#$"' + line
        self.write_cb(line)

    def write_out_of_band(self, line):
        self.write_cb(line)

    def send_message(self, msg):
        msg.send(self.auth_key, self.write_cb)

    def _parse_value(self, line):
        if not line.startswith('"'):
            if ' ' in line:
                return line.split(' ', 1)
            return (line, '')
        line = line[1:]
        val = ''
        while line and not line.startswith('"'):
            spos = len(line) if '\\' not in line else line.index('\\')
            qpos = len(line) if '"' not in line else line.index('"')
            pos = max(spos, qpos)
            val += line[:pos]
            line = line[pos:]
            if line.startswith('\\'):
                val += line[1]
                line = line[2:]
        if line.startswith('"'):
            line = line[1:]
        return (val, line)

    def parse_line(self, line):
        if line.startswith("#$#: "):
            # Completion
            dtag = line[5:].strip()
            if dtag in self.partials:
                return self.partials[dtag]
            return None
        elif line.startswith("#$#* "):
            # Continuation
            dtag, line = line[5:].lstrip().split(' ', 1)
            line = line.lstrip()
            key, val = line.lstrip().split(': ', 1)
            if dtag in self.partials:
                msg = self.partials[dtag]
                msg[key].append(val)
            return None
        elif line.startswith("#$#"):
            # New message start
            cmd, line = line[3:].lstrip().split(' ', 1)
            line = line.lstrip()
            if cmd == 'mcp':
                # mcp command startup negotiation has no auth key.
                self.auth_key = None
                self.partials = {}
                self.negotiated = False
            else:
                auth, line = line.split(' ', 1)
                line = line.lstrip()
                if not self.auth_key or auth != self.auth_key:
                    # Reject if auth key wrong or never negotiated.
                    return None
            msg = McpMessage(cmd)
            complete = True
            while line:
                key, line = line.split(': ', 1)
                line = line.lstrip()
                val, line = self._parse_value(line)
                line = line.lstrip()
                if key.endswith('*'):
                    key = key[:-1]
                    msg[key] = []
                    complete = False
                else:
                    msg[key] = val
            if complete:
                return msg
            else:
                return None
        return None


# vim: expandtab tabstop=4 shiftwidth=4 softtabstop=4 nowrap
