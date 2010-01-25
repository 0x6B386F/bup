#!/usr/bin/env python
import sys, math, struct, glob, sha
import options, git
from helpers import *

PAGE_SIZE=4096
SHA_PER_PAGE=PAGE_SIZE/200.


def next(it):
    try:
        return it.next()
    except StopIteration:
        return None
    
    
def merge(idxlist, total, bits, table):
    iters = [iter(i) for i in idxlist]
    iters = [[next(it), it] for it in iters]
    count = 0
    while iters:
        if (count % 10000) == 0:
            log('\rMerging: %.2f%% (%d/%d)'
                % (count*100.0/total, count, total))
        e = min(iters)  # FIXME: very slow for long lists; use smarter algo
        assert(e[0])
        yield e[0]
        count += 1
        prefix = git.extract_bits(e[0], bits)
        table[prefix] = count
        e[0] = next(e[1])
        iters = filter(lambda x: x[0], iters)
    log('\rMerging: done.                                    \n')


def do_midx(outdir, outfilename, infilenames):
    if not outfilename:
        assert(outdir)
        sum = sha.sha('\0'.join(infilenames)).hexdigest()
        outfilename = '%s/midx-%s.midx' % (outdir, sum)
    
    inp = []
    total = 0
    for name in infilenames:
        ix = git.PackIndex(name)
        inp.append(ix)
        total += len(ix)

    if not total:
        log('No new .idx files: nothing to do.\n')
        return

    log('Merging %d indexes (%d objects).\n' % (len(infilenames), total))
    pages = total/SHA_PER_PAGE
    bits = int(math.ceil(math.log(pages, 2)))
    entries = 2**bits
    log('table size: %d (%d bits)\n' % (entries*8, bits))
    
    table = [0]*entries

    try:
        os.unlink(outfilename)
    except OSError:
        pass
    f = open(outfilename + '.tmp', 'w+')
    f.write('MIDX\0\0\0\1')
    f.write(struct.pack('!I', bits))
    assert(f.tell() == 12)
    f.write('\0'*8*entries)
    
    for e in merge(inp, total, bits, table):
        f.write(e)
        
    f.write('\0'.join([os.path.basename(p) for p in infilenames]))

    f.seek(12)
    f.write(struct.pack('!%dQ' % entries, *table))
    f.close()

    # this is just for testing
    if 0:
        p = git.PackMidx(outfilename)
        assert(len(p.idxnames) == len(infilenames))
        print p.idxnames
        assert(len(p) == total)
        pi = iter(p)
        for i in merge(inp, total, bits, table):
            assert(i == pi.next())
            assert(p.exists(i))

    os.rename(outfilename + '.tmp', outfilename)
    print outfilename

optspec = """
bup midx [options...] <idxnames...>
--
o,output=  output midx filename (default: auto-generated)
a,auto     automatically create .midx from any unindexed .idx files
f,force    automatically create .midx from *all* .idx files
"""
o = options.Options('bup midx', optspec)
(opt, flags, extra) = o.parse(sys.argv[1:])

if extra and (opt.auto or opt.force):
    log("bup midx: you can't use -f/-a and also provide filenames\n")
    o.usage()

git.check_repo_or_die()

if extra:
    do_midx(git.repo('objects/pack'), opt.output, extra)
elif opt.auto or opt.force:
    paths = [git.repo('objects/pack')]
    paths += glob.glob(git.repo('index-cache/*/.'))
    if opt.force:
        for path in paths:
            do_midx(path, opt.output, glob.glob('%s/*.idx' % path))
    elif opt.auto:
        for path in paths:
            m = git.MultiPackIndex(path)
            needed = {}
            for pack in m.packs:  # only .idx files without a .midx are open
                if pack.name.endswith('.idx'):
                    needed[pack.name] = 1
            do_midx(path, opt.output, needed.keys())
else:
    log("bup midx: you must use -f or -a or provide input filenames\n")
    o.usage()
