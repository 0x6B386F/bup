#!/usr/bin/env python
import os, sys, stat, time
import options, git, index, drecurse
from helpers import *


def merge_indexes(out, r1, r2):
    for e in index.MergeIter([r1, r2]):
        # FIXME: shouldn't we remove deleted entries eventually?  When?
        out.add_ixentry(e)


class IterHelper:
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


def check_index(reader):
    try:
        log('check: checking forward iteration...\n')
        e = None
        d = {}
        for e in reader.forward_iter():
            if e.children_n:
                log('%08x+%-4d %r\n' % (e.children_ofs, e.children_n, e.name))
                assert(e.children_ofs)
                assert(e.name.endswith('/'))
                assert(not d.get(e.children_ofs))
                d[e.children_ofs] = 1
        assert(not e or e.name == '/')  # last entry is *always* /
        log('check: checking normal iteration...\n')
        last = None
        for e in reader:
            if last:
                assert(last > e.name)
            last = e.name
    except:
        log('index error! at %r\n' % e)
        raise
    log('check: passed.\n')


def update_index(top):
    ri = index.Reader(indexfile)
    wi = index.Writer(indexfile)
    rig = IterHelper(ri.iter(name=top))
    tstart = int(time.time())

    hashgen = None
    if opt.fake_valid:
        def hashgen(name):
            return (0100644, index.FAKE_SHA)

    total = 0
    for (path,pst) in drecurse.recursive_dirlist([top], xdev=opt.xdev):
        if opt.verbose>=2 or (opt.verbose==1 and stat.S_ISDIR(pst.st_mode)):
            sys.stdout.write('%-70s\n' % path)
            sys.stdout.flush()
            progress('Indexing: %d\r' % total)
        elif not (total % 128):
            progress('Indexing: %d\r' % total)
        total += 1
        while rig.cur and rig.cur.name > path:  # deleted paths
            if rig.cur.exists():
                rig.cur.set_deleted()
                rig.cur.repack()
            rig.next()
        if rig.cur and rig.cur.name == path:    # paths that already existed
            if pst:
                rig.cur.from_stat(pst, tstart)
            if not (rig.cur.flags & index.IX_HASHVALID):
                if hashgen:
                    (rig.cur.gitmode, rig.cur.sha) = hashgen(path)
                    rig.cur.flags |= index.IX_HASHVALID
            if opt.fake_invalid:
                rig.cur.invalidate()
            rig.cur.repack()
            rig.next()
        else:  # new paths
            wi.add(path, pst, hashgen = hashgen)
    progress('Indexing: %d, done.\n' % total)
    
    if ri.exists():
        ri.save()
        wi.flush()
        if wi.count:
            wr = wi.new_reader()
            if opt.check:
                log('check: before merging: oldfile\n')
                check_index(ri)
                log('check: before merging: newfile\n')
                check_index(wr)
            mi = index.Writer(indexfile)
            merge_indexes(mi, ri, wr)
            ri.close()
            mi.close()
        wi.abort()
    else:
        wi.close()


optspec = """
bup index <-p|m|u> [options...] <filenames...>
--
p,print    print the index entries for the given names (also works with -u)
m,modified print only added/deleted/modified files (implies -p)
s,status   print each filename with a status char (A/M/D) (implies -p)
H,hash     print the hash for each object next to its name (implies -p)
l,long     print more information about each file
u,update   (recursively) update the index entries for the given filenames
x,xdev,one-file-system  don't cross filesystem boundaries
fake-valid mark all index entries as up-to-date even if they aren't
fake-invalid mark all index entries as invalid
check      carefully check index file integrity
f,indexfile=  the name of the index file (default 'index')
v,verbose  increase log output (can be used more than once)
"""
o = options.Options('bup index', optspec)
(opt, flags, extra) = o.parse(sys.argv[1:])

if not (opt.modified or opt['print'] or opt.status or opt.update or opt.check):
    log('bup index: supply one or more of -p, -s, -m, -u, or --check\n')
    o.usage()
if (opt.fake_valid or opt.fake_invalid) and not opt.update:
    log('bup index: --fake-{in,}valid are meaningless without -u\n')
    o.usage()
if opt.fake_valid and opt.fake_invalid:
    log('bup index: --fake-valid is incompatible with --fake-invalid\n')
    o.usage()

git.check_repo_or_die()
indexfile = opt.indexfile or git.repo('bupindex')

if opt.check:
    log('check: starting initial check.\n')
    check_index(index.Reader(indexfile))

paths = index.reduce_paths(extra)

if opt.update:
    if not paths:
        log('bup index: update (-u) requested but no paths given\n')
        o.usage()
    for (rp,path) in paths:
        update_index(rp)

if opt['print'] or opt.status or opt.modified:
    for (name, ent) in index.Reader(indexfile).filter(extra or ['']):
        if (opt.modified 
            and (ent.is_valid() or ent.is_deleted() or not ent.mode)):
            continue
        line = ''
        if opt.status:
            if not ent.flags & index.IX_EXISTS:
                line += 'D '
            elif not ent.flags & index.IX_HASHVALID:
                if ent.sha == index.EMPTY_SHA:
                    line += 'A '
                else:
                    line += 'M '
            else:
                line += '  '
        if opt.long:
            line += "%7s %7s " % (oct(ent.mode), oct(ent.gitmode))
        if opt.hash:
            line += ent.sha.encode('hex') + ' '
        print line + (name or './')

if opt.check:
    log('check: starting final check.\n')
    check_index(index.Reader(indexfile))

if saved_errors:
    log('WARNING: %d errors encountered.\n' % len(saved_errors))
    sys.exit(1)
