#!/usr/bin/python

# Copyright (c) 2013 Dropbox, Inc.
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.

from collections import defaultdict, namedtuple
import itertools
import textwrap
import sys
import os
import re

# Helper for flattening nested lists
flatten = itertools.chain.from_iterable

CodepointInfo = namedtuple("CodepointInfo",
    [ "codepoint", "name", "category", "ccc", "bidi_category", "decomposition",
      "decimal_value", "digit_value", "numeric_value", "mirrored", "old_name", "comment",
      "uppercase", "lowercase", "titlecase" ])

Decomposition = namedtuple("Decomposition", [ "type", "mapping" ])

# The highest possible codepoint is 0x10FFFF, so we need 21 bits to represent a codepoint.
UNICODE_CODE_SPACE_BITS = 21

def from_hex(s):
    """Parse a hex string.
    """
    return int(s, 16) if s else None


def file_lines(*path_components):
    """Helper for reading all lines out of a file, ignoring comments.
    """
    with open(os.path.join(*path_components)) as f:
        for line in f.readlines():
            line = line.strip().split("#", 1)[0]
            if line and line[0] != '@':
                yield line


def parse_data(base_path):
    """Parse the Unicode character data and composition exclusion files.
    """

    codepoints = {}
    for line in file_lines(base_path, "UnicodeData.txt"):
        fields = line.strip().split(";")

        if fields[5]:
            decomp_fields = fields[5].split(" ")
            if decomp_fields[0].startswith("<"):
                decomp = Decomposition(decomp_fields[0], map(from_hex, decomp_fields[1:]))
            else:
                decomp = Decomposition("canonical", map(from_hex, decomp_fields))
        else:
            decomp = Decomposition("none", None)

        info = CodepointInfo(
            from_hex(fields[0]), fields[1], fields[2], int(fields[3]), fields[4], decomp,
            fields[6], fields[7], fields[8], fields[9], fields[10], fields[11],
            from_hex(fields[12]), from_hex(fields[13]), from_hex(fields[14]))

        codepoints[info.codepoint] = info

    exclusions = set(map(from_hex, file_lines(base_path, "CompositionExclusions.txt")))

    return codepoints, exclusions


def parse_collation(base_path):
    """Parse the DUCET file allkeys.txt
    """
    collation_elements = {}
    def parse_element(el_string):
        # we treat * variable weight as non-ignorable because this is not actually used for sorting
        return map(from_hex, re.split('\.|\*',el_string))
    for line in file_lines(base_path, "allkeys.txt"):
        fields = line.strip().split(";");
        if fields[0]:
            codepoints = tuple(map(from_hex, fields[0].strip().split()))
            fields = re.split('\]\[(?:\.|\*)', fields[1].strip(' []*.'))
            collation_elements[codepoints] = map(parse_element, fields)
    return collation_elements


def recursive_decompose(data, pt):
    """Return the full decomposition for codepoint pt.
    """
    info = data.get(pt, None)
    if info and info.decomposition.type == "canonical":
        return flatten(recursive_decompose(data, pt) for pt in info.decomposition.mapping)
    else:
        return (pt, )


def bytes_needed(data):
    """Find an appropriate type to represent all values in data.
    """
    if any(d < 0 for d in data):
        prefix, nbits = "", max(max(data).bit_length(), (-1 - min(data)).bit_length()) + 1
    else:
        prefix, nbits = "u", max(data).bit_length()

    return prefix, next(v for v in (1, 2, 4) if v * 8 >= nbits)


def try_split(arr, shift):
    """Try splitting arr into a 2-level trie with chunks of size 2**shift.

    Return the two levels of the tree as dicts, as well as shift.
    """
    table1, table2 = [], []
    size = 2 ** shift
    chunks = {}

    for i in range(0, len(arr), size):
        this_chunk = tuple(arr[i:i+size])
        if this_chunk not in chunks:
            chunks[this_chunk] = len(table2) >> shift
            table2.extend(this_chunk)

        table1.append(chunks[this_chunk])

    return table1, table2, shift


def split_array(arr):
    """Split arr into a 2-level trie.
    """
    return min(
        ( try_split(arr, shift) for shift in xrange(len(arr).bit_length()) ),
        key = lambda (t1, t2, shift): bytes_needed(t1)[1] * len(t1)
                                    + bytes_needed(t2)[1] * len(t2)
    )


def dump_table(name, data):
    """Dump data as a C array called 'name'.
    """
    prefix, nbytes = bytes_needed(data)
    typ = "%sint%s_t" % (prefix, nbytes * 8)
    return len(data) * nbytes, "static const %s %s[] = {\n    %s\n};\n" % (
        typ, name, "\n    ".join(textwrap.wrap(", ".join(map(str, data)))))



def sublist_index(haystack, needle):
    n = len(needle)
    for i in xrange(len(haystack) - n + 1):
        if haystack[i:i+n] == needle:
            return i

def make_translation_map(name, translation_func):
    translation_map = [ 0 ] * 0x110000
    value_table = []
    value_index_cache = {}

    for codepoint, info in data.iteritems():
        value = translation_func(info)

        if value not in value_index_cache:
            value_index_cache[value] = len(value_table)
            value_table.append(value)

        translation_map[codepoint] = value_index_cache[value]

    # End the table at the highest non-zero value
    translation_map = translation_map[:max(i for i, v in enumerate(translation_map) if v) + 1]

    index1, index2, shift = split_array(translation_map)

    vb, v = dump_table(name + "_values", value_table)
    t1b, t1 = dump_table(name + "_t1", index1)
    t2b, t2 = dump_table(name + "_t2", index2)

    out = "%s\n%s\n%s\n" % (v, t1, t2)
    out += """int32_t %s(int32_t codepoint) {
        int offset_index;
    if (codepoint >= %d) return 0;
    offset_index = %s_t2[(%s_t1[codepoint >> %d] << %d) + (codepoint & %d)];
    return %s_values[offset_index];
}""" % (name, len(translation_map), name, name, shift, shift, (1 << shift) - 1, name)

    return vb + t1b + t2b, out

def make_direct_map(name, func):
    out_map = [ func(data[codepoint]) if codepoint in data else 0
                for codepoint in xrange(0x110000) ]

    # End the table at the highest non-zero value
    out_map = out_map[:max(i for i, v in enumerate(out_map) if v) + 1]

    index1, index2, shift = split_array(out_map)

    t1b, t1 = dump_table(name + "_t1", index1)
    t2b, t2 = dump_table(name + "_t2", index2)

    out = "%s\n%s\n" % (t1, t2)
    out += """int32_t %s(int32_t codepoint) {
    if (codepoint >= %d) return 0;
    return %s_t2[(%s_t1[codepoint >> %d] << %d) + (codepoint & %d)];
}""" % (name, len(out_map), name, name, shift, shift, (1 << shift) - 1)

    return t1b + t2b, out


def make_collation_element_table(collation_elements):

    # The Default Unicode Collation Element Table (DUCET) is a mapping from sequences of
    # codepoints to sequences of collation elements. We only implement "level 1" (see
    # Unicode TR10 for more detail), so a collation element is the same as a "weight",
    # a 16-bit integer. We use 32-bit integers throughout to represent weights.
    #
    # This function produces a hash table mapping sequences of codepoints to sequences of
    # collation elements. The actual collation algorithm is implmented in
    # minutf_collation.cpp; it takes an input string and performs a number of lookups in the
    # hash table to produce a sort key. We use a simple hash function, defined below and
    # also in C++, to hash sequences of codepoints into buckets.
    #
    # The DUCET is serialized as a sequence of records, of variable length. Each record is
    # simply a key (nonempty sequence of codepoints) followed by a value (sequence of
    # weights; values may be empty). These records are variable-length, so the high-order
    # bits of the first word of the key contain metadata:
    #
    # Bit 31        Set if this is the *last* record in its bucket
    # Bits 30:29    Length of key
    # Bits 28:24    Length of value
    # Bits 21:0:    First codepoint in key
    #
    # These records are serialized into an array called "ducet_data". A second array called
    # ducet_bucket_indexes maps hash buckets to the index in ducet_data of the first record
    # for that bucket. So, the lookup algorithm is:
    #
    # - Given a sequence of codepoint, hash them to find which bucket any mappings for that
    #   key would be in.
    # - Read ducet_bucket_indexes[bucket] to find where in ducet_data to start reading
    # - Process variable-length records starting at ducet_data[ducet_bucket_indexes[bucket]]
    #   and see if any key matches the input. Stop when a record indicating that it's the last
    #   is found.

    def get_level_1_elements(elements):
        return [el[0] for el in elements if el[0] != 0]

    level1_elements = { key: get_level_1_elements(all_levels)
                        for key, all_levels
                        in collation_elements.iteritems() }

    # How many bits do we need to store key and value lengths?
    longest_key = max(len(key) for key in level1_elements.iterkeys())
    longest_value = max(len(value) for value in level1_elements.itervalues())

    KEY_BITS = longest_key.bit_length()
    VALUE_BITS = longest_value.bit_length()
    BUCKETS = len(level1_elements)
    HASH_MULTIPLIER = 1031
    DUCET_DATA_HIGH_BIT = 31

    bucket_to_data = defaultdict(list)

    def bucket(seq):
        out = 0
        for i in seq:
            out = (out * HASH_MULTIPLIER + i) % BUCKETS
        return out # % BUCKETS

    for key, value in sorted(level1_elements.iteritems()):
        header_word = (len(key) << (DUCET_DATA_HIGH_BIT - KEY_BITS)) \
                    | (len(value) << (DUCET_DATA_HIGH_BIT - KEY_BITS - VALUE_BITS))
        assert (header_word & ~(~0 << UNICODE_CODE_SPACE_BITS)) == 0
        data = [ header_word | key[0] ] + list(key[1:]) + list(value)
        bucket_to_data[bucket(key)].append(data)

    # First, figure out what the total length of data_array should be, so we know where
    # to point empty buckets.
    data_array_len = 0
    for b in range(BUCKETS):
        if b in bucket_to_data:
            for d in bucket_to_data[b]:
                data_array_len += len(d)

    bucket_to_offset = []

    data_array = []

    collision_count = defaultdict(int)

    for b in range(BUCKETS):
        if b in bucket_to_data:
            bucket_to_offset.append(len(data_array))

            collision_count[len(bucket_to_data[b])] += 1

            # Set the high bit of the first word of the last record in this bucket.
            bucket_to_data[b][-1][0] |= (1 << DUCET_DATA_HIGH_BIT)

            for d in bucket_to_data[b]:
                data_array.extend(d)

        else:
            bucket_to_offset.append(data_array_len)

    assert len(data_array) == data_array_len

    header = "// %r\n" % (collision_count, )

    dd_bytes, dd = dump_table("ducet_data", data_array)
    off_bytes, off = dump_table("ducet_bucket_indexes", bucket_to_offset)
    footer = "#define DUCET_HASH_BUCKETS %d\n" % (BUCKETS, )
    footer += "#define DUCET_HASH_MULTIPLIER %d\n" % (HASH_MULTIPLIER, )
    footer += "#define DUCET_LONGEST_KEY %d\n" % (longest_key, )
    footer += "#define DUCET_KEY_BITS %d\n" % (KEY_BITS, )
    footer += "#define DUCET_VALUE_BITS %d\n" % (VALUE_BITS, )
    footer += "#define DUCET_DATA_HIGH_BIT %d\n" % (DUCET_DATA_HIGH_BIT, )

    return dd_bytes + off_bytes, header + dd + off + footer


data, exclusions = parse_data("data-6.3.0")
collation_elements = parse_collation("data-6.3.0")

ccc = { codepoint: info.ccc for (codepoint, info) in data.iteritems() }

# Recursively calculate decomposition mappings and reorder combining characters
decomposition_map = {
    pt: sorted(recursive_decompose(data, pt), key = lambda pt: ccc.get(pt, 0))
    for pt, info in data.iteritems()
    if info.decomposition.type == "canonical"
}

composition_map = {
    tuple(info.decomposition.mapping): codepoint
    for codepoint, info in data.items()
    if codepoint not in exclusions
        and info.decomposition.type == "canonical"
        and len(info.decomposition.mapping) == 2
        and info.ccc == 0
        and ccc.get(info.decomposition.mapping[0], 0) == 0
}

# Make a shorter list of all interesting codepoints
interesting_codepoints = [0] + sorted(
      set(flatten([ cp ] + dc for cp, dc in decomposition_map.iteritems()))
    | set(flatten((k1, k2, v) for ((k1, k2), v) in composition_map.iteritems()))
)
interesting_codepoint_map = { pt: idx for idx, pt in enumerate(interesting_codepoints) }

# Assemble decomposition sequences
decomposition_sequences = [ 0 ]
decomposition_starts = {}
for codepoint, decomposition in decomposition_map.iteritems():
    decomposition = [ interesting_codepoint_map[cp] for cp in decomposition ]
    idx = sublist_index(decomposition_sequences, decomposition)
    if idx is None:
        idx = len(decomposition_sequences)
        decomposition_sequences.extend(decomposition)

    assert len(decomposition) in (1, 2, 3, 4)
    assert idx < (1 << 14)

    decomposition_starts[codepoint] = idx | ((len(decomposition) - 1) << 14)

k2map = defaultdict(set)
for (k1, k2), v in composition_map.iteritems():
    k2map[k1].add((k2, v))

comp_seqs = []
comp_map = {}

for k1, k2vs in k2map.iteritems():
    comp_map[k1] = len(comp_seqs) / 2
    last_k2, last_v = k2vs.pop()
    for k2, v in k2vs:
        comp_seqs.append(interesting_codepoint_map[k2])
        comp_seqs.append(interesting_codepoint_map[v])

    comp_seqs.append(interesting_codepoint_map[last_k2] | 0x8000)
    comp_seqs.append(interesting_codepoint_map[last_v])

if len(sys.argv) >= 2 and sys.argv[1] == "--collation":
    out = {
        "ducet_level1": make_collation_element_table(collation_elements)
    }
else:
    out = {
        "lower_offset": make_translation_map("lowercase_offset", lambda info: info.lowercase - info.codepoint if info.lowercase else 0),
    #     "upper_offset": make_translation_map("uppercase_offset", lambda info: info.uppercase - info.codepoint if info.uppercase else 0),
        "ccc": make_direct_map("ccc", lambda info: info.ccc),
        "xref": dump_table("xref", interesting_codepoints),
        "decomp_seq": dump_table("decomp_seq", decomposition_sequences),
        "decomp_idx": make_direct_map("decomp_idx", lambda info: decomposition_starts.get(info.codepoint, 0)),
        "comp_seq": dump_table("comp_seq", comp_seqs),
        "comp_idx": make_direct_map("comp_idx", lambda info: comp_map.get(info.codepoint, 0)),
    }

# for k in sorted(out.keys()):
#     (nbytes, defs) = out[k]
for k, (nbytes, defs) in out.iteritems():
    print defs
    print >>sys.stderr, "%s: %d" % (k, nbytes)

print >>sys.stderr, "total: %s" % sum(nbytes for nbytes, defs in out.values())
