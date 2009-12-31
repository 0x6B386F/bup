CFLAGS=-Wall -g -O2 -Werror -I/usr/include/python2.5 -g -fPIC

default: all

all: bup-split bup-join bup randomgen hashsplit.so

randomgen: randomgen.o

hashsplit.so: hashsplitmodule.o
	$(CC) -shared -o $@ $<
	
runtests: all
	./wvtest.py $(wildcard t/t*.py)
	
runtests-cmdline: all
	@echo "Testing \"$@\" in Makefile:"
	./bup split <testfile1 >tags1
	./bup split <testfile2 >tags2
	diff -u tags1 tags2 || true
	wc -c testfile1 testfile2
	wc -l tags1 tags2
	./bup join <tags1 >out1
	./bup join <tags2 >out2
	diff -u testfile1 out1
	diff -u testfile2 out2
	
test: all runtests-cmdline
	./wvtestrun $(MAKE) runtests

%: %.o
	gcc -o $@ $< $(LDFLAGS) $(LIBS)
	
bup: bup.py
	rm -f $@
	ln -s $^ $@
	
bup-%: cmd-%.py
	rm -f $@
	ln -s $^ $@
	
bup-%: cmd-%.sh
	rm -f $@
	ln -s $^ $@
	
%.o: %.c
	gcc -c -o $@ $^ $(CPPFLAGS) $(CFLAGS)

clean:
	rm -f *.o *.so *~ .*~ *.pyc \
		bup bup-split bup-join randomgen \
		out[12] tags[12]
