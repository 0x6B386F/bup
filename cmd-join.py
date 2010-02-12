#!/usr/bin/env python
import sys, time, struct
import hashsplit, git, options, client
from helpers import *
from subprocess import PIPE


optspec = """
bup join [-r host:path] [refs or hashes...]
--
r,remote=  remote repository path
"""
o = options.Options('bup join', optspec)
(opt, flags, extra) = o.parse(sys.argv[1:])

git.check_repo_or_die()

if not extra:
    extra = linereader(sys.stdin)

if opt.remote:
    cli = client.Client(opt.remote)
    for id in extra:
        for blob in cli.cat(id):
            sys.stdout.write(blob)
    cli.close()
else:
    cp = git.CatPipe()
    for id in extra:
        #log('id=%r\n' % id)
        for blob in cp.join(id):
            sys.stdout.write(blob)
