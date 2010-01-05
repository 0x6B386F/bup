CFLAGS=-Wall -g -O2 -Werror `python2.5-config --includes` -g -fPIC

default: all

all: bup-split bup-join bup-save bup-init bup-server bup randomgen chashsplit.so

randomgen: randomgen.o

chashsplit.so: chashsplitmodule.o
	$(CC) -shared -o $@ $<
	
runtests: all
	./wvtest.py $(wildcard t/t*.py)
	
runtests-cmdline: all
	./test-sh
	
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
	rm -f *.o *.so *~ .*~ *.pyc */*.pyc */*~ \
		bup bup-* randomgen \
		out[12] out2[tc] tags[12] tags2[tc]
	rm -rf *.tmp
