import re, struct
import git
from helpers import *
from subprocess import Popen, PIPE

class ClientError(Exception):
    pass

class Client:
    def __init__(self, remote, create=False):
        self._busy = None
        self._indexes_synced = 0
        rs = remote.split(':', 1)
        if len(rs) == 1:
            (host, dir) = ('NONE', remote)
            argv = ['bup', 'server']
        else:
            (host, dir) = rs
            argv = ['ssh', host, '--', 'bup', 'server']
        (self.host, self.dir) = (host, dir)
        self.cachedir = git.repo('index-cache/%s'
                                 % re.sub(r'[^@:\w]', '_', 
                                          "%s:%s" % (host, dir)))
        self.p = p = Popen(argv, stdin=PIPE, stdout=PIPE)
        self.conn = conn = Conn(p.stdout, p.stdin)
        if dir:
            dir = re.sub(r'[\r\n]', ' ', dir)
            if create:
                conn.write('init-dir %s\n' % dir)
            else:
                conn.write('set-dir %s\n' % dir)
            conn.check_ok()

    def __del__(self):
        self.close()

    def close(self):
        if self.conn and not self._busy:
            self.conn.write('quit\n')
        if self.p:
            self.p.stdin.close()
            while self.p.stdout.read(65536):
                pass
            self.p.stdout.close()
            self.p.wait()
            rv = self.p.wait()
            if rv:
                raise ClientError('server tunnel returned exit code %d' % rv)
        self.conn = None
        self.p = None

    def check_busy(self):
        if self._busy:
            raise ClientError('already busy with command %r' % self._busy)
        
    def _not_busy(self):
        self._busy = None

    def sync_indexes(self):
        self.check_busy()
        conn = self.conn
        conn.write('list-indexes\n')
        packdir = git.repo('objects/pack')
        mkdirp(self.cachedir)
        all = {}
        needed = {}
        for line in linereader(conn):
            if not line:
                break
            all[line] = 1
            assert(line.find('/') < 0)
            if not os.path.exists(os.path.join(self.cachedir, line)):
                needed[line] = 1
        conn.check_ok()

        for f in os.listdir(self.cachedir):
            if f.endswith('.idx') and not f in all:
                log('pruning old index: %r\n' % f)
                os.unlink(os.path.join(self.cachedir, f))

        # FIXME this should be pipelined: request multiple indexes at a time, or
        # we waste lots of network turnarounds.
        for name in needed.keys():
            log('requesting %r\n' % name)
            conn.write('send-index %s\n' % name)
            n = struct.unpack('!I', conn.read(4))[0]
            assert(n)
            log('   expect %d bytes\n' % n)
            fn = os.path.join(self.cachedir, name)
            f = open(fn + '.tmp', 'w')
            for b in chunkyreader(conn, n):
                f.write(b)
            conn.check_ok()
            f.close()
            os.rename(fn + '.tmp', fn)

        self._indexes_synced = 1

    def new_packwriter(self):
        assert(self._indexes_synced)
        self.check_busy()
        self._busy = 'receive-objects'
        self.conn.write('receive-objects\n')
        objcache = git.MultiPackIndex(self.cachedir)
        return git.PackWriter_Remote(self.conn, objcache = objcache,
                                     onclose = self._not_busy)

    def read_ref(self, refname):
        self.check_busy()
        self.conn.write('read-ref %s\n' % refname)
        r = self.conn.readline().strip()
        self.conn.check_ok()
        if r:
            assert(len(r) == 40)   # hexified sha
            return r.decode('hex')
        else:
            return None   # nonexistent ref

    def update_ref(self, refname, newval, oldval):
        self.check_busy()
        self.conn.write('update-ref %s\n%s\n%s\n' 
                        % (refname, newval.encode('hex'),
                           (oldval or '').encode('hex')))
        self.conn.check_ok()

    def cat(self, id):
        self.check_busy()
        self._busy = 'cat'
        self.conn.write('cat %s\n' % re.sub(r'[\n\r]', '_', id))
        while 1:
            sz = struct.unpack('!I', self.conn.read(4))[0]
            if not sz: break
            yield self.conn.read(sz)
        self.conn.check_ok()
        self._not_busy()
