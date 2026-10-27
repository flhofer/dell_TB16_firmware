CC = xcrun clang
CFLAGS = -std=c11 -O2 -Wall -Wextra -Werror -mmacosx-version-min=12.0

.PHONY: all test clean
all: build/libtb16aux.dylib

build/libtb16aux.dylib: aux.c iodp.c
	mkdir -p build
	$(CC) $(CFLAGS) -dynamiclib -framework IOKit -framework CoreFoundation $^ -o $@

build/test_aux: tests/test_aux.c aux.c
	mkdir -p build
	$(CC) $(CFLAGS) -framework IOKit -framework CoreFoundation $< -o $@

test: all build/test_aux
	./build/test_aux
	python3 -m unittest discover -s tests -v

clean:
	rm -rf build
