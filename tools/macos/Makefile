CC = xcrun clang
CFLAGS = -std=c11 -O2 -Wall -Wextra -Werror -mmacosx-version-min=12.0

.PHONY: all test clean
all: build/libtb16aux.dylib

build/libtb16aux.dylib: aux.c iodp.c thunderbolt.c
	mkdir -p build
	$(CC) $(CFLAGS) -dynamiclib -framework IOKit -framework CoreFoundation $^ -o $@

build/test_aux: tests/test_aux.c aux.c
	mkdir -p build
	$(CC) $(CFLAGS) -framework IOKit -framework CoreFoundation $< -o $@

build/test_thunderbolt: tests/test_thunderbolt.c thunderbolt.c
	mkdir -p build
	$(CC) $(CFLAGS) -framework IOKit -framework CoreFoundation $< -o $@

build/test_nvm_header: tests/test_nvm_header.c thunderbolt.c
	mkdir -p build
	$(CC) $(CFLAGS) -framework IOKit -framework CoreFoundation $< -o $@

build/test_nvm_update: tests/test_nvm_update.c thunderbolt.c
	mkdir -p build
	$(CC) $(CFLAGS) -framework IOKit -framework CoreFoundation $< -o $@

test: all build/test_aux build/test_thunderbolt build/test_nvm_header build/test_nvm_update
	./build/test_aux
	./build/test_thunderbolt
	./build/test_nvm_header
	./build/test_nvm_update
	python3 -m unittest discover -s tests -v

clean:
	rm -rf build
