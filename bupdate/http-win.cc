#include "wvcom.h"
#include "wvcomstatus.h"
#include "wvbuf.h"
#include "wvstringlist.h"
#include "wvstrutils.h"
#include "wvdiriter.h"
#include <unistd.h>


typedef void progfunc_t(const char *s);
typedef unsigned char  byte;

static void simple_print(const char *s)
{
    printf("%s", s);
    fflush(stdout);
}


// reassign this to change progress message printing function
progfunc_t *progfunc = simple_print;


void print(WvStringParm s)
{
    simple_print(s);
}


void print(WVSTRING_FORMAT_DECL)
{
    print(WvString(WVSTRING_FORMAT_CALL));
}


// FIXME: support multiple ranges in a single request?
WvError http_get(WvBuf &buf, WvStringParm url, int startbyte, int bytelen)
{
    print("Getting: %s\n", url);
    
    WvComStatus err("http");
    if (startbyte < 0)
	return err.set_both(EINVAL, "startbyte must be >= 0");
    if (!(bytelen > 0 || bytelen == -1))
	return err.set_both(EINVAL, "bytelen must be -1 or positive, not 0");

    bool wantrange = (startbyte > 0 || bytelen > 0);
    
    WvCom req("Microsoft.XMLHTTP");
    if (!err.isok())
	return err;
    req.call("Open", "GET", url, false);
    if (wantrange)
    {
	WvString rangestr;
	if (bytelen > 0)
	    rangestr = WvString("bytes=%s-%s", startbyte, startbyte+bytelen-1);
	else
	    rangestr = WvString("bytes=%s-", startbyte);
	req.call("setRequestHeader", "Range", rangestr);
    }
    
    req.call("Send", "");
    int status = req.get("Status");
    
    if (!err.isok())
	return err;
    
    int expected = wantrange ? 206 : 200;
    if (status != expected)
    {
	int nstatus = status ? status : -1;
	return err.set_both(nstatus,
			    "status code: %s (expected %s)",
			    status, expected);
    }

    byte *b = NULL;
    size_t len = 0;
    WvVariant v = req.get("responseBody");
    v.blob(&b, &len);
    
    if (wantrange && (int)len != bytelen)
    {
	delete[] b;
	return err.set("server sent %s bytes (expected %s)", len, bytelen);
    }
    buf.put(b, len);
    delete[] b;
    
    return err;
}


WvString http_get_str(WvStringParm url)
{
    WvComStatus err;
    WvDynBuf b;
    err.set(http_get(b, url, 0, -1));
    if (err.isok())
	return b.getstr();
    else
	return WvString::null;
}


bool is_url(WvStringParm s)
{
    return strstr(s, "://");
}


void targets_from_file(WvStringList &l, WvStringParm s)
{
    if (s.startswith("<"))
    {
	// it's HTML; pick out the anchors
	const char *cptr = s;
	while (cptr)
	{
	    cptr = strstr(cptr, "<a href=");
	    if (!cptr)
		break;
	    cptr += 8;
	    char quote = *cptr;
	    if (quote != '/' && quote != '\"')
		continue;
	    cptr++;
	    const char *eptr = strchr(cptr, quote);
	    if (!eptr)
		continue;
	    WvString ns;
	    size_t len = eptr-cptr;
	    ns.setsize(len+1);
	    char *optr = ns.edit();
	    strncpy(optr, cptr, len);
	    optr[len] = 0;
	    l.append(url_decode(ns));
	}
    }
    else
    {
	// it's not HTML; assume it's a one-per-line list of filenames
	l.split(s, "\n");
    }
}


WvString readfile(WvStringParm filename)
{
    byte buf[65536];
    WvDynBuf b;
    FILE *f = fopen(filename, "rb");
    if (!f)
	return WvString::null;
    size_t len;
    while ((len = fread(buf, 1, sizeof(buf), f)) >= 1)
	b.put(buf, len);
    fclose(f);
    return b.getstr();
}


int main(int argc, char **argv)
{
    if (argc != 2)
    {
	fprintf(stderr, "usage: %s <url>\n", argv[0]);
	return 1;
    }
    
    WvComStatus err;
    WvString baseurl(argv[1]);
    for (char *cptr = baseurl.edit(); cptr && *cptr; cptr++)
	if (*cptr == '\\')
	    *cptr = '/';
    
    WvStringList targets;
    if (baseurl.endswith(".fidx"))
    {
	// the baseurl is a particular fidx, not a file list, so just use
	// a file list of one.
	targets.append(getfilename(baseurl));
    }
    else if (is_url(baseurl))
    {
	// it's an actual URL; download it
	print("Downloading base: %s\n", baseurl);
	WvString s = http_get_str(baseurl);
	// FIXME: what if we got http redirected?  We should save the new url
	targets_from_file(targets, s);
    }
    else
    {
	// not an URL, so it's a disk file
	struct stat st;
	while (baseurl.endswith("/"))
	    *strrchr(baseurl.edit(), '/') = 0;
	if (stat(baseurl, &st) != 0)
	    err.set(errno);
	else if (S_ISDIR(st.st_mode))
	{
	    // a directory
	    print("it's a dir\n");
	    WvDirIter di(baseurl);
	    for (di.rewind(); di.next(); )
		targets.append(di->name);
	    if (!baseurl.endswith("/"))
		baseurl.append("/");
	}
	else
	{
	    // an index file
	    print("it's a file\n");
	    targets_from_file(targets, readfile(baseurl));
	}
	baseurl = WvString("file://%s", baseurl);
    }
    if (!baseurl.endswith("/"))
    {
	baseurl = getdirname(baseurl);
	if (!baseurl.endswith("/"))
	    baseurl.append("/");
    }
    
    {
	WvStringList::Iter i(targets);
	for (i.rewind(); i.next(); )
	{
	    *i = trim_string(i->edit());
	    if (!*i || i->startswith(".") || !i->endswith(".fidx"))
		i.xunlink();
	}
    }
    
    print("baseurl is: '%s'\n"
	  "Targets (%s):\n",
	  baseurl, targets.count());
    WvStringList::Iter i(targets);
    for (i.rewind(); i.next(); )
	print("  '%s'\n", *i);
#if 0    
    for (int i = 0; i < 10; i++)
    {
	WvDynBuf buf;
	WvError e = http_get(buf, baseurl, i, 10*i);
	if (!e.isok())
	    print("  ERROR: %s\n", e.str());
	else
	    print("  got %s bytes\n", buf.used());
    }
#endif
    
    if (!err.isok())
	print("error was: %s\n", err.str());
    return 0;
}
