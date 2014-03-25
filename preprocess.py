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
    out += """static int32_t %s(int32_t codepoint) {
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
    out += """static int32_t %s(int32_t codepoint) {
    if (codepoint >= %d) return 0;
    return %s_t2[(%s_t1[codepoint >> %d] << %d) + (codepoint & %d)];
}""" % (name, len(out_map), name, name, shift, shift, (1 << shift) - 1)

    return t1b + t2b, out


def make_collation_element_table(collation_elements):

    def make_line(codepoints, level1_elements):
        if codepoints[0] == 0:
            return None
        cp_string = ', '.join(["0x%08X" % pt for pt in list(codepoints)])
        level1_elements.append(0)
        level1_string = ', '.join(["0x%04X" % el for el in level1_elements])
        out = "    %s, 0x00000000, %s" % (cp_string, level1_string)
        return out

    def get_level_1_elements(elements):
        return [el[0] for el in elements if el[0] != 0]

    sorted_cp = sorted(collation_elements.keys())
    level1_elements = {}
    for cp in sorted_cp:
        level1_elements[cp] = get_level_1_elements(collation_elements[cp])

    def is_empty(cp, l1els):
        return len(list(cp)) == 1 and len(l1els) == 0
    def is_short(cp, l1els):
        return len(list(cp)) == 1 and len(l1els) == 1
    def is_variable(cp, l1els):
        return not is_empty(cp, l1els) and not is_short(cp, l1els)

    out = """/* Using ugly initialization because it takes too long to compile when written as a proper initializer.
 * Note that the variable-length data format uses 0 for field separators. This relies on assumptions
 * about data in the ducet that are not true for ducet beyond level 1.
 */
 """

    out += "static const uint32_t ducet_data_empty[] = {\n"
    lines = ["    0x%08X" % cp[0] for cp in sorted_cp if is_empty(cp, level1_elements[cp])]
    out += ",\n".join(lines)
    out += "\n};\n"

    out += "static const uint32_t ducet_data_short[] = {\n"
    lines = ["    0x%08X, 0x%04X" % (cp[0], level1_elements[cp][0]) for cp in sorted_cp if is_short(cp, level1_elements[cp])]
    out += ",\n".join(lines)
    out += "\n};\n"

    out += "static const uint32_t ducet_data_variable[] = {\n"
    lines = [make_line(cp, level1_elements[cp]) for cp in sorted_cp if is_variable(cp, level1_elements[cp])]
    out += ",\n".join(filter(None, lines))
    out += "\n};\n"
    return len(collation_elements), out


data, exclusions = parse_data("data-4.1.0")
collation_elements = parse_collation("data-4.1.0")

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
