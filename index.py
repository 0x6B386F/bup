import os, stat, time, struct, tempfile, mmap
from helpers import *

EMPTY_SHA = '\0'*20
FAKE_SHA = '\x01'*20
INDEX_HDR = 'BUPI\0\0\0\1'
INDEX_SIG = '!IIIIIQ20sH'
ENTLEN = struct.calcsize(INDEX_SIG)

IX_EXISTS = 0x8000
IX_HASHVALID = 0x4000

class Error(Exception):
    pass


class Entry:
    def __init__(self, name, m, ofs, tstart):
        self._m = m
        self._ofs = ofs
        self.name = str(name)
        self.tstart = tstart
        (self.dev, self.ctime, self.mtime, self.uid, self.gid,
         self.size, self.sha,
         self.flags) = struct.unpack(INDEX_SIG, buffer(m, ofs, ENTLEN))

    def __repr__(self):
        return ("(%s,0x%04x,%d,%d,%d,%d,%d,0x%04x)" 
                % (self.name, self.dev,
                   self.ctime, self.mtime, self.uid, self.gid,
                   self.size, self.flags))

    def packed(self):
        return struct.pack(INDEX_SIG, self.dev, self.ctime, self.mtime,
                           self.uid, self.gid, self.size, self.sha,
                           self.flags)

    def repack(self):
        self._m[self._ofs:self._ofs+ENTLEN] = self.packed()

    def from_stat(self, st):
        old = (self.dev, self.ctime, self.mtime,
               self.uid, self.gid, self.size, self.flags & IX_EXISTS)
        new = (st.st_dev, int(st.st_ctime), int(st.st_mtime),
               st.st_uid, st.st_gid, st.st_size, IX_EXISTS)
        self.dev = st.st_dev
        self.ctime = int(st.st_ctime)
        self.mtime = int(st.st_mtime)
        self.uid = st.st_uid
        self.gid = st.st_gid
        self.size = st.st_size
        self.flags |= IX_EXISTS
        if int(st.st_ctime) >= self.tstart or old != new:
            self.flags &= ~IX_HASHVALID
            return 1  # dirty
        else:
            return 0  # not dirty

    def __cmp__(a, b):
        return cmp(a.name, b.name)
            

class Reader:
    def __init__(self, filename):
        self.filename = filename
        self.m = ''
        self.writable = False
        f = None
        try:
            f = open(filename, 'r+')
        except IOError, e:
            if e.errno == errno.ENOENT:
                pass
            else:
                raise
        if f:
            b = f.read(len(INDEX_HDR))
            if b != INDEX_HDR:
                raise Error('%s: header: expected %r, got %r'
                                 % (filename, INDEX_HDR, b))
            st = os.fstat(f.fileno())
            if st.st_size:
                self.m = mmap.mmap(f.fileno(), 0,
                                   mmap.MAP_SHARED,
                                   mmap.PROT_READ|mmap.PROT_WRITE)
                f.close()  # map will persist beyond file close
                self.writable = True

    def __del__(self):
        self.save()

    def __iter__(self):
        tstart = int(time.time())
        ofs = len(INDEX_HDR)
        while ofs < len(self.m):
            eon = self.m.find('\0', ofs)
            assert(eon >= 0)
            yield Entry(buffer(self.m, ofs, eon-ofs),
                          self.m, eon+1, tstart = tstart)
            ofs = eon + 1 + ENTLEN

    def save(self):
        if self.writable:
            self.m.flush()

    def filter(self, prefixes):
        #log("filtering %r\n" % prefixes)
        paths = reduce_paths(prefixes)
        #log("filtering %r\n" % paths)
        pi = iter(paths)
        (rpin, pin) = pi.next()
        for ent in self:
            #log('checking %r vs %r\n' % (ent.name, rpin))
            while ent.name < rpin:
                try:
                    (rpin, pin) = pi.next()
                except StopIteration:
                    return  # no more files can possibly match
            if not ent.name.startswith(rpin):
                continue   # not interested
            else:
                name = pin + ent.name[len(rpin):]
                yield (name or './', ent)


# Read all the iters in order; when more than one iter has the same entry,
# the *later* iter in the list wins.  (ie. more recent iter entries replace
# older ones)
def _last_writer_wins_iter(iters):
    l = []
    for e in iters:
        it = iter(e)
        try:
            l.append([it.next(), it])
        except StopIteration:
            pass
    del iters  # to avoid accidents
    while l:
        l.sort()
        mv = l[0][0]
        mi = []
        for (i,(v,it)) in enumerate(l):
            #log('(%d) considering %d: %r\n' % (len(l), i, v))
            if v > mv:
                mv = v
                mi = [i]
            elif v == mv:
                mi.append(i)
        yield mv
        for i in mi:
            try:
                l[i][0] = l[i][1].next()
            except StopIteration:
                l[i] = None
        l = filter(None, l)


class Writer:
    def __init__(self, filename):
        self.f = None
        self.count = 0
        self.lastfile = None
        self.filename = None
        self.filename = filename = os.path.realpath(filename)
        (dir,name) = os.path.split(filename)
        (ffd,self.tmpname) = tempfile.mkstemp('.tmp', filename, dir)
        self.f = os.fdopen(ffd, 'wb', 65536)
        self.f.write(INDEX_HDR)

    def __del__(self):
        self.abort()

    def abort(self):
        f = self.f
        self.f = None
        if f:
            f.close()
            os.unlink(self.tmpname)

    def close(self):
        f = self.f
        self.f = None
        if f:
            f.close()
            os.rename(self.tmpname, self.filename)

    def _write(self, data):
        self.f.write(data)
        self.count += 1

    def add(self, name, st, hashgen=None):
        #log('ADDING %r\n' % name)
        if self.lastfile:
            assert(cmp(self.lastfile, name) > 0) # reverse order only
        self.lastfile = name
        flags = IX_EXISTS
        sha = None
        if hashgen:
            sha = hashgen(name)
            if sha:
                flags |= IX_HASHVALID
        else:
            sha = EMPTY_SHA
        data = name + '\0' + \
            struct.pack(INDEX_SIG, st.st_dev, int(st.st_ctime),
                        int(st.st_mtime), st.st_uid, st.st_gid,
                        st.st_size, sha, flags)
        self._write(data)

    def add_ixentry(self, e):
        if self.lastfile and self.lastfile <= e.name:
            raise Error('%r must come before %r' 
                             % (e.name, self.lastfile))
        self.lastfile = e.name
        data = e.name + '\0' + e.packed()
        self._write(data)

    def new_reader(self):
        self.f.flush()
        return Reader(self.tmpname)


def reduce_paths(paths):
    xpaths = []
    for p in paths:
        rp = os.path.realpath(p)
        st = os.lstat(rp)
        if stat.S_ISDIR(st.st_mode):
            rp = slashappend(rp)
            p = slashappend(p)
        xpaths.append((rp, p))
    xpaths.sort()

    paths = []
    prev = None
    for (rp, p) in xpaths:
        if prev and (prev == rp 
                     or (prev.endswith('/') and rp.startswith(prev))):
            continue # already superceded by previous path
        paths.append((rp, p))
        prev = rp
    paths.sort(reverse=True)
    return paths

