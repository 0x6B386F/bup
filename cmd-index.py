#!/usr/bin/env python2.5
import sys, re, errno, stat, tempfile, struct, mmap, time
import options, git
from helpers import *

EMPTY_SHA = '\0'*20
FAKE_SHA = '\x01'*20
INDEX_HDR = 'BUPI\0\0\0\1'
INDEX_SIG = '!IIIIIQ20sH'
ENTLEN = struct.calcsize(INDEX_SIG)

IX_EXISTS = 0x8000
IX_HASHVALID = 0x4000


class IndexError(Exception):
    pass


class OsFile:
    def __init__(self, path):
        self.fd = None
        self.fd = os.open(path, os.O_RDONLY|os.O_LARGEFILE|os.O_NOFOLLOW)
        #self.st = os.fstat(self.fd)
        
    def __del__(self):
        if self.fd:
            fd = self.fd
            self.fd = None
            os.close(fd)

    def fchdir(self):
        os.fchdir(self.fd)


class IxEntry:
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
            

class IndexReader:
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
                raise IndexError('%s: header: expected %r, got %r'
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
            yield IxEntry(buffer(self.m, ofs, eon-ofs),
                          self.m, eon+1, tstart = tstart)
            ofs = eon + 1 + ENTLEN

    def save(self):
        if self.writable:
            self.m.flush()


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


def ix_encode(st, sha, flags):
    return struct.pack(INDEX_SIG, st.st_dev, int(st.st_ctime),
                       int(st.st_mtime), st.st_uid, st.st_gid,
                       st.st_size, sha, flags)


class IndexWriter:
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
        data = name + '\0' + ix_encode(st, sha, flags)
        self._write(data)

    def add_ixentry(self, e):
        if self.lastfile and self.lastfile <= e.name:
            raise IndexError('%r must come before %r' 
                             % (e.name, self.lastfile))
        self.lastfile = e.name
        data = e.name + '\0' + e.packed()
        self._write(data)

    def new_reader(self):
        self.f.flush()
        return IndexReader(self.tmpname)


saved_errors = []
def add_error(e):
    saved_errors.append(e)
    log('\n%s\n' % e)


# the use of fchdir() and lstat() are for two reasons:
#  - help out the kernel by not making it repeatedly look up the absolute path
#  - avoid race conditions caused by doing listdir() on a changing symlink
def handle_path(ri, wi, dir, name, pst, xdev, can_delete_siblings):
    hashgen = None
    if opt.fake_valid:
        def hashgen(name):
            return FAKE_SHA
    
    dirty = 0
    path = dir + name
    #log('handle_path(%r,%r)\n' % (dir, name))
    if stat.S_ISDIR(pst.st_mode):
        if opt.verbose == 1: # log dirs only
            sys.stdout.write('%s\n' % path)
            sys.stdout.flush()
        try:
            OsFile(name).fchdir()
        except OSError, e:
            add_error(Exception('in %s: %s' % (dir, str(e))))
            return 0
        try:
            try:
                ld = os.listdir('.')
                #log('* %r: %r\n' % (name, ld))
            except OSError, e:
                add_error(Exception('in %s: %s' % (path, str(e))))
                return 0
            lds = []
            for p in ld:
                try:
                    st = os.lstat(p)
                except OSError, e:
                    add_error(Exception('in %s: %s' % (path, str(e))))
                    continue
                if xdev != None and st.st_dev != xdev:
                    log('Skipping %r: different filesystem.\n' 
                        % os.path.realpath(p))
                    continue
                if stat.S_ISDIR(st.st_mode):
                    p = _slashappend(p)
                lds.append((p, st))
            for p,st in reversed(sorted(lds)):
                dirty += handle_path(ri, wi, path, p, st, xdev,
                                     can_delete_siblings = True)
        finally:
            os.chdir('..')
    #log('endloop: ri.cur:%r path:%r\n' % (ri.cur.name, path))
    while ri.cur and ri.cur.name > path:
        #log('ricur:%r path:%r\n' % (ri.cur, path))
        if can_delete_siblings and dir and ri.cur.name.startswith(dir):
            #log('    --- deleting\n')
            ri.cur.flags &= ~(IX_EXISTS | IX_HASHVALID)
            ri.cur.repack()
            dirty += 1
        ri.next()
    if ri.cur and ri.cur.name == path:
        dirty += ri.cur.from_stat(pst)
        if dirty or not (ri.cur.flags & IX_HASHVALID):
            #log('   --- updating %r\n' % path)
            if hashgen:
                ri.cur.sha = hashgen(name)
                ri.cur.flags |= IX_HASHVALID
            ri.cur.repack()
        ri.next()
    else:
        wi.add(path, pst, hashgen = hashgen)
        dirty += 1
    if opt.verbose > 1:  # all files, not just dirs
        sys.stdout.write('%s\n' % path)
        sys.stdout.flush()
    return dirty


def merge_indexes(out, r1, r2):
    log('bup: merging indexes.\n')
    for e in _last_writer_wins_iter([r1, r2]):
        #if e.flags & IX_EXISTS:
            out.add_ixentry(e)


class MergeGetter:
    def __init__(self, l):
        self.i = iter(l)
        self.cur = None
        self.next()

    def next(self):
        try:
            self.cur = self.i.next()
        except StopIteration:
            self.cur = None
        return self.cur


def _slashappend(s):
    if s and not s.endswith('/'):
        return s + '/'
    else:
        return s

def update_index(path):
    ri = IndexReader(indexfile)
    wi = IndexWriter(indexfile)
    rig = MergeGetter(ri)
    
    rpath = os.path.realpath(path)
    st = os.lstat(rpath)
    if opt.xdev:
        xdev = st.st_dev
    else:
        xdev = None
    f = OsFile('.')
    if rpath[-1] == '/':
        rpath = rpath[:-1]
    (dir, name) = os.path.split(rpath)
    dir = _slashappend(dir)
    if stat.S_ISDIR(st.st_mode) and (not rpath or rpath[-1] != '/'):
        name += '/'
        can_delete_siblings = True
    else:
        can_delete_siblings = False
    OsFile(dir or '/').fchdir()
    dirty = handle_path(rig, wi, dir, name, st, xdev, can_delete_siblings)

    # make sure all the parents of the updated path exist and are invalidated
    # if appropriate.
    while 1:
        (rpath, junk) = os.path.split(rpath)
        if not rpath:
            break
        elif rpath == '/':
            p = rpath
        else:
            p = rpath + '/'
        while rig.cur and rig.cur.name > p:
            #log('FINISHING: %r path=%r d=%r\n' % (rig.cur.name, p, dirty))
            rig.next()
        if rig.cur and rig.cur.name == p:
            if dirty:
                rig.cur.flags &= ~IX_HASHVALID
                rig.cur.repack()
        else:
            wi.add(p, os.lstat(p))
        if p == '/':
            break
    
    f.fchdir()
    ri.save()
    if wi.count:
        mi = IndexWriter(indexfile)
        merge_indexes(mi, ri, wi.new_reader())
        mi.close()
    wi.abort()


optspec = """
bup index <-p|s|m|u> [options...] <filenames...>
--
p,print    print the index entries for the given names (also works with -u)
m,modified print only added/deleted/modified files (implies -p)
s,status   print each filename with a status char (A/M/D) (implies -p)
u,update   (recursively) update the index entries for the given filenames
x,xdev,one-file-system  don't cross filesystem boundaries
fake-valid    mark all index entries as up-to-date even if they aren't
f,indexfile=  the name of the index file (default 'index')
v,verbose  increase log output (can be used more than once)
"""
o = options.Options('bup index', optspec)
(opt, flags, extra) = o.parse(sys.argv[1:])

if not (opt.modified or opt['print'] or opt.status or opt.update):
    log('bup index: you must supply one or more of -p, -s, -m, or -u\n')
    exit(97)
if opt.fake_valid and not opt.update:
    log('bup index: --fake-valid is meaningless without -u\n')
    exit(96)

git.check_repo_or_die()
indexfile = opt.indexfile or git.repo('bupindex')

xpaths = []
for path in extra:
    rp = os.path.realpath(path)
    st = os.lstat(rp)
    if stat.S_ISDIR(st.st_mode):
        rp = _slashappend(rp)
        path = _slashappend(path)
    xpaths.append((rp, path))

paths = []
for (rp, path) in reversed(sorted(xpaths)):
    if paths and rp.endswith('/') and paths[-1][0].startswith(rp):
        paths[-1] = (rp, path)
    else:
        paths.append((rp, path))

if opt.update:
    if not paths:
        log('bup index: update (-u) requested but no paths given\n')
        exit(96)
    for (rp, path) in paths:
        update_index(rp)

if opt['print'] or opt.status or opt.modified:
    pi = iter(paths or [(_slashappend(os.path.realpath('.')), '')])
    (rpin, pin) = pi.next()
    for ent in IndexReader(indexfile):
        if ent.name < rpin:
            try:
                (rpin, pin) = pi.next()
            except StopIteration:
                break  # no more files can possibly match
        elif not ent.name.startswith(rpin):
            continue   # not interested
        if opt.modified and ent.flags & IX_HASHVALID:
            continue
        name = pin + ent.name[len(rpin):]
        if not name:
            name = '.'
        if opt.status:
            if not ent.flags & IX_EXISTS:
                print 'D ' + name
            elif not ent.flags & IX_HASHVALID:
                if ent.sha == EMPTY_SHA:
                    print 'A ' + name
                else:
                    print 'M ' + name
            else:
                print '  ' + name
        else:
            print name
        #print repr(ent)

if saved_errors:
    log('WARNING: %d errors encountered.\n' % len(saved_errors))
    exit(1)
