TEST_SRCS = miniutf.cpp miniutf_collation.cpp test.cpp
DATA_HDRS = miniutfdata.h miniutfdata_collation.h

.PHONY: clean check

check: test
	./test

test: Makefile $(TEST_SRCS) $(DATA_HDRS)
	clang++ -g -Wall -Wextra -std=c++11 -stdlib=libc++ -pedantic $(TEST_SRCS) -o $@

miniutfdata.h: preprocess.py
	python preprocess.py > miniutfdata.h

miniutfdata_collation.h: preprocess.py
	python preprocess.py --collation > miniutfdata_collation.h

.PHONY: clean
clean:
	rm -rf test test test.dSYM $(DATA_HDRS)
