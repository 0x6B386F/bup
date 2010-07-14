OS:=$(shell uname | sed 's/[-_].*//')
CFLAGS=-Wall -g -O2 -Werror $(PYINCLUDE) -g
ifneq ($(OS),CYGWIN)
  CFLAGS += -fPIC
endif
SHARED=-shared
SOEXT:=.so

ifeq (${OS},Darwin)
  MACHINE:=$(shell arch)
  CFLAGS += -arch $(MACHINE)
  SHARED = -dynamiclib
endif
ifeq ($(OS),CYGWIN)
  LDFLAGS += -L/usr/bin
  EXT:=.exe
  SOEXT:=.dll
endif

default: all

all: bup Documentation/all

bup: lib/bup/_version.py lib/bup/_hashsplit$(SOEXT) cmds

Documentation/all: bup

INSTALL=install
PYTHON=python
MANDIR=$(DESTDIR)/usr/share/man
DOCDIR=$(DESTDIR)/usr/share/doc/bup
BINDIR=$(DESTDIR)/usr/bin
LIBDIR=$(DESTDIR)/usr/lib/bup
install: all
	$(INSTALL) -d $(MANDIR)/man1 $(DOCDIR) $(BINDIR) \
		$(LIBDIR)/bup $(LIBDIR)/cmd
	[ ! -e Documentation/.docs-available ] || \
	  $(INSTALL) -o 0 -g 0 -m 0644 \
		$(wildcard Documentation/*.1) \
		$(MANDIR)/man1
	[ ! -e Documentation/.docs-available ] || \
	  $(INSTALL) -o 0 -g 0 -m 0644 \
		$(wildcard Documentation/*.html) \
		$(DOCDIR)
	$(INSTALL) -o 0 -g 0 -m 0755 bup $(BINDIR)
	$(INSTALL) -o 0 -g 0 -m 0755 \
		$(wildcard cmd/bup-*) \
		$(LIBDIR)/cmd
	$(INSTALL) -o 0 -g 0 -m 0644 \
		$(wildcard lib/bup/*.so lib/bup/*.py) \
		$(LIBDIR)/bup
	
%/all:
	$(MAKE) -C $* all
	
%/clean:
	$(MAKE) -C $* clean

lib/bup/_hashsplit$(SOEXT): lib/bup/_hashsplit.c lib/bup/csetup.py
	@rm -f $@
	cd lib/bup && $(PYTHON) csetup.py build
	cp lib/bup/build/*/_hashsplit$(SOEXT) lib/bup/

.PHONY: lib/bup/_version.py
lib/bup/_version.py:
	rm -f $@ $@.new
	./format-subst.pl $@.pre >$@.new
	mv $@.new $@
	
runtests: all runtests-python runtests-cmdline

runtests-python:
	$(PYTHON) wvtest.py $(wildcard t/t*.py lib/*/t/t*.py)
	
runtests-cmdline: all
	t/test.sh
	
stupid:
	PATH=/bin:/usr/bin $(MAKE) test
	
test: all
	./wvtestrun $(MAKE) PYTHON=$(PYTHON) runtests

%: %.o
	$(CC) $(CFLAGS) (LDFLAGS) -o $@ $^ $(LIBS)
	
bup: main.py
	rm -f $@
	ln -s $< $@
	
cmds: $(patsubst cmd/%-cmd.py,cmd/bup-%,$(wildcard cmd/*-cmd.py))

cmd/bup-%: cmd/%-cmd.py
	rm -f $@
	ln -s $*-cmd.py $@
	
%: %.py
	rm -f $@
	ln -s $< $@
	
bup-%: cmd-%.sh
	rm -f $@
	ln -s $< $@
	
%.o: %.c
	gcc -c -o $@ $< $(CPPFLAGS) $(CFLAGS)

clean: Documentation/clean
	rm -f *.o *.so */*/*.so *.dll *.exe .*~ *~ */*~ */*/*~ \
		*.pyc */*.pyc */*/*.pyc \
		bup bup-* cmd/bup-* lib/bup/_version.py randomgen memtest \
		out[12] out2[tc] tags[12] tags2[tc]
	rm -rf *.tmp t/*.tmp build lib/bup/build
