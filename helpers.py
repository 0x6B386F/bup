import sys, os, pwd, subprocess, errno, socket, select


def log(s):
    sys.stderr.write(s)


def mkdirp(d):
    try:
        os.makedirs(d)
    except OSError, e:
        if e.errno == errno.EEXIST:
            pass
        else:
            raise


def readpipe(argv):
    p = subprocess.Popen(argv, stdout=subprocess.PIPE)
    r = p.stdout.read()
    p.wait()
    return r


_username = None
def username():
    global _username
    if not _username:
        uid = os.getuid()
        try:
            _username = pwd.getpwuid(uid)[0]
        except KeyError:
            _username = 'user%d' % uid
    return _username


_userfullname = None
def userfullname():
    global _userfullname
    if not _userfullname:
        uid = os.getuid()
        try:
            _userfullname = pwd.getpwuid(uid)[4].split(',')[0]
        except KeyError:
            _userfullname = 'user%d' % uid
    return _userfullname


_hostname = None
def hostname():
    global _hostname
    if not _hostname:
        _hostname = socket.getfqdn()
    return _hostname


class Conn:
    def __init__(self, inp, outp):
        self.inp = inp
        self.outp = outp

    def read(self, size):
        self.outp.flush()
        return self.inp.read(size)

    def readline(self):
        self.outp.flush()
        return self.inp.readline()

    def write(self, data):
        #log('%d writing: %d bytes\n' % (os.getpid(), len(data)))
        self.outp.write(data)

    def has_input(self):
        [rl, wl, xl] = select.select([self.inp.fileno()], [], [], 0)
        if rl:
            assert(rl[0] == self.inp.fileno())
            return True
        else:
            return None

    def ok(self):
        self.write('\nok\n')

    def drain_and_check_ok(self):
        self.outp.flush()
        rl = ''
        for rl in linereader(self.inp):
            #log('%d got line: %r\n' % (os.getpid(), rl))
            if not rl:  # empty line
                continue
            elif rl == 'ok':
                return True
            else:
                pass # ignore line
        # NOTREACHED

    def check_ok(self):
        self.outp.flush()
        rl = ''
        for rl in linereader(self.inp):
            #log('%d got line: %r\n' % (os.getpid(), rl))
            if not rl:  # empty line
                continue
            elif rl == 'ok':
                return True
            else:
                raise Exception('expected "ok", got %r' % rl)
        raise Exception('server exited unexpectedly; see errors above')


def linereader(f):
    while 1:
        line = f.readline()
        if not line:
            break
        yield line[:-1]


def chunkyreader(f, count = None):
    if count != None:
        while count > 0:
            b = f.read(min(count, 65536))
            if not b:
                raise IOError('EOF with %d bytes remaining' % count)
            yield b
            count -= len(b)
    else:
        while 1:
            b = f.read(65536)
            if not b: break
            yield b


def slashappend(s):
    if s and not s.endswith('/'):
        return s + '/'
    else:
        return s

