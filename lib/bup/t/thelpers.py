import os
from bup.helpers import *
from wvtest import *

@wvtest
def test_parse_num():
    pn = parse_num
    WVPASSEQ(pn('1'), 1)
    WVPASSEQ(pn('0'), 0)
    WVPASSEQ(pn('1.5k'), 1536)
    WVPASSEQ(pn('2 gb'), 2*1024*1024*1024)
    WVPASSEQ(pn('1e+9 k'), 1000000000 * 1024)
    WVPASSEQ(pn('-3e-3mb'), int(-0.003 * 1024 * 1024))

@wvtest
def test_strip_path():
    prefix = "/var/backup/daily.0/localhost"
    empty_prefix = ""
    non_matching_prefix = "/home"
    path = "/var/backup/daily.0/localhost/etc/"

    WVPASSEQ(strip_path(prefix, path), '/etc')
    WVPASSEQ(strip_path(empty_prefix, path), path)
    WVPASSEQ(strip_path(non_matching_prefix, path), path)
    WVEXCEPT(Exception, strip_path, None, path)

@wvtest
def test_strip_base_path():
    path = "/var/backup/daily.0/localhost/etc/"
    base_paths = ["/var", "/var/backup", "/var/backup/daily.0/localhost"]
    WVPASSEQ(strip_base_path(path, base_paths), '/etc')

@wvtest
def test_strip_symlinked_base_path():
    tmpdir = os.path.join(os.getcwd(),"test_strip_symlinked_base_path.tmp")
    symlink_src = os.path.join(tmpdir, "private", "var")
    symlink_dst = os.path.join(tmpdir, "var")
    path = os.path.join(symlink_dst, "a")

    os.mkdir(tmpdir)
    os.mkdir(os.path.join(tmpdir, "private"))
    os.mkdir(symlink_src)
    os.symlink(symlink_src, symlink_dst)

    result = strip_base_path(path, [symlink_dst])

    os.remove(symlink_dst)
    os.rmdir(symlink_src)
    os.rmdir(os.path.join(tmpdir, "private"))
    os.rmdir(tmpdir)

    WVPASSEQ(result, "/a")

