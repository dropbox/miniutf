miniutf
=======

miniutf is a C++ implementation of several basic Unicode manipulation functions.

Features
--------

### UTF-8, UTF-16, UTF-32 (UCS-4)

miniutf can convert between UTF-8 (`std::string`), UTF-16 (`std::u16string`), and
UTF-32 / UCS-4 (`std::u32string`). The C++11 standard library provides UTF-8 and -16 encoders
and decoders (`codecvt_utf8` / `codecvt_utf16`), but as of late 2013, libstdc++ doesn't
implement them. Miniutf's conversion functions also provide validity checking and can insert
replacement characters if invalid input is found.

### NFC, NFD

miniutf implements conversion to NFC and NFD as defined in Unicode TR15. It does not implement
NFKC or NFKD.

### Collation

miniutf implements collation as defined by the Default Unicode Collation Element Table,
level 1 (Unicode TR10). This requires a large data table, which adds to binary size, so it's
in a separate source and header file. The collation function can be used for case- and
accent-insensitive searching and sorting.

### Lowercase

Unicode defines a one-to-one lowercase translation for each codepoint. (This is needed for
Dropbox's internal use, but should be avoided otherwise. One-to-one lowercasing does not
always match the lowercase rules of a given language, e.g. German eszett, Turkish dotless i.)

System Requirements
-------------------

miniutf requires a recent C++11 compiler and standard library, such as Clang 3.3+ or GCC 4.8+.

License
-------

MIT (see LICENSE.txt)
