/* Copyright (c) 2013 Dropbox, Inc.
 *
 * Permission is hereby granted, free of charge, to any person obtaining a copy
 * of this software and associated documentation files (the "Software"), to deal
 * in the Software without restriction, including without limitation the rights
 * to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
 * copies of the Software, and to permit persons to whom the Software is
 * furnished to do so, subject to the following conditions:
 *
 * The above copyright notice and this permission notice shall be included in
 * all copies or substantial portions of the Software.
 *
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 * IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 * FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
 * AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 * LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
 * OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
 * THE SOFTWARE.
 */

#include "miniutf_collation.hpp"

#include <cassert>
#include <unordered_set>
#include <vector>

namespace miniutf {

#include "miniutfdata_collation.h"

// The highest possible codepoint is 0x10FFFF, so we need 21 bits to represent a codepoint.
#define UNICODE_CODE_SPACE_BITS 21

/* Return the hash of the given range.
 */
template <typename IterType>
static size_t hash_key(IterType begin, IterType end) {
    size_t hash = 0;
    while (begin != end) {
        hash = (hash * DUCET_HASH_MULTIPLIER + *begin) % DUCET_HASH_BUCKETS;
        ++begin;
    }
    return hash;
}

/* Look up a sequence of codepoints in the DUCET.
 *
 * This function takes its input as begin/end iterators; 'end' is one-past-the-end, as usual.
 *
 * The return value is the start and length of a sequence of collation elements, if found. If
 * the input is found, the returned pointer will always be non-null, though the length
 * may be 0 to indicate an empty mapping. If not found, the returned pointer will be null.
 */
static std::pair<const uint32_t *, int> find_elements(const char32_t * begin,
                                                      const char32_t * end) {
    size_t hash = hash_key(begin, end);

    const uint32_t * entry = std::begin(ducet_data) + ducet_bucket_indexes[hash];

    while (entry < std::end(ducet_data)) {
        uint32_t key_len = (entry[0] >> (DUCET_DATA_HIGH_BIT - DUCET_KEY_BITS))
                            & ~(~0ULL << DUCET_KEY_BITS);
        uint32_t value_len = (entry[0] >> (DUCET_DATA_HIGH_BIT - DUCET_KEY_BITS
                                                               - DUCET_VALUE_BITS))
                             & ~(~0ULL << DUCET_VALUE_BITS);
        uint32_t first_word = entry[0] & ~(~0ULL << UNICODE_CODE_SPACE_BITS);

        // If this entry matches [begin, end), then we're done.
        if (key_len == static_cast<uint32_t>(end - begin)
            && first_word == begin[0]
            && std::equal(entry + 1, entry + key_len, begin + 1)) {
            return { entry + key_len, value_len };
        }

        // Otherwise, see if we're at the end of this hash bucket
        if (entry[0] & (1 << DUCET_DATA_HIGH_BIT)) {
            return { nullptr, 0 };
        }

        // Move on to the next bucket.
        entry += key_len + value_len;
    }

    return { nullptr, 0 };
}

// in miniutf.cpp.
int32_t ccc(int32_t codepoint);

/*
 * Finds the DUCET collation elements at position i in a string, adds its length to i, and
 * appends the collation elements to the given vector. We only deal with level 1 here.
 */
void get_ducet_level1(std::u32string & str,
                      size_t & i,
                      std::vector<uint32_t> & elements) {

    assert(i < str.size());

    std::pair<const uint32_t *, int> best_key { nullptr, 0 };
    size_t best_length = 0;

    // S2.1: Find the longest initial substring S at each point that has a match in the table.

    for (size_t j = 1; j <= DUCET_LONGEST_KEY && i+j <= str.length(); j++) {
        auto itr = find_elements(str.data() + i, str.data() + i + j);
        if (itr.first) {
            best_key = itr;
            best_length = j;
        }
    }

    // S2.1.1. If there are any non-starters following S, process each non-starter C.

    std::unordered_set<int32_t> blocked_classes;

    if (best_key.first) {
        size_t j = best_length;
        while (i + j <= str.length()) {
            const char32_t C = str[i+j];
            const int32_t ccc_C = ccc(C);
            if (ccc_C == 0) {
                break;
            }

            // S2.1.2 If C is not blocked from S, find if S + C has a match in the table.
            // Note: A non-starter in a string is called blocked if there is another
            // non-starter of the same canonical combining class or zero between it and the
            // last character of canonical combining class 0.
            if (!blocked_classes.count(ccc_C)) {

                // TODO(j4cbo): Would be nice to eliminate this copy.
                std::u32string SC { str.data() + i, str.data() + i + best_length };
                SC += C;

                auto itr = find_elements(SC.data(), SC.data() + SC.size());

                // S2.1.3 If there is a match, replace S by S + C, and remove C.
                if (itr.first) {
                    std::copy_backward(str.begin() + i + best_length, str.begin() + i + j,
                                       str.begin() + i + j + 1);
                    str[i + best_length] = C;
                    best_key = itr;
                    best_length++;
                    break;
                }
            }

            blocked_classes.emplace(ccc_C);
            j++;
        }
    }

    // S2.2 Fetch the corresponding collation element(s) from the table if there is a match.
    // If there is no match, synthesize a weight as described in Section 7.1,
    // Derived Collation Elements.

    if (best_key.first) {
        elements.insert(elements.end(), best_key.first, best_key.first + best_key.second);
        i += best_length;
        return;
    }

    // http://www.unicode.org/reports/tr10/#Derived_Collation_Elements
    char32_t pt = str[i];
    char32_t base = 0xfbc0;
    ++i;

    // ftp://ftp.unicode.org/Public/6.3.0/ucd/PropList.txt says the Unified_Ideograph
    // characters are:
    // 3400..4DB5 [ CJK Unified Ideographs Extension A ]
    // 4E00..9FCC [ CJK Unified Ideographs ]
    // FA0E..FA0F, FA11, FA13..FA14, FA1F, FA21, FA23..FA24, FA27..FA29
    //     [ CJK Compatibility Ideographs ]
    // 20000..2A6D6 [ CJK Unified Ideographs Extension B ]
    // 2A700..2B734 [ CJK Unified Ideographs Extension C ]
    // 2B740..2B81D [ CJK Unified Ideographs Extension D ]
    //

    if ((0x4e00 <= pt && pt <= 0x9fcc) || (0xfa0e <= pt && pt <= 0xfa0f) || pt == 0xfa11
        || pt == 0xfa13 || pt == 0xfa14 || pt == 0xfa1f || pt == 0xfa21 || pt == 0xfa23
        || pt == 0xfa24 || pt == 0xfa27 || pt == 0xfa28 || pt == 0xfa29) {
        base = 0xfb40;
    } else if ((0x3400 <= pt && pt <= 0x4db5)         // CJK Unified Ideographs Extension A
               || (0x20000 <= pt && pt <= 0x2a6d6)    // CJK Unified Ideographs Extension B
               || (0x2a700 <= pt && pt <= 0x2b734)    // CJK Unified Ideographs Extension C
               || (0x2b740 <= pt && pt <= 0x2b81d)) { // CJK Unified Ideographs Extension D
        base = 0xfb80;
    }

    char32_t aaaa = base + (pt >> 15);
    char32_t bbbb = (pt & 0x7fff) | 0x8000;

    elements.push_back(aaaa);
    elements.push_back(bbbb);
}

std::vector<uint32_t> match_key(const std::string & in) {

    // S1.1 Use the Unicode canonical algorithm to decompose characters according to the
    // canonical mappings. That is, put the string into Normalization Form D (see [UAX15]).
    std::u32string codepoints = normalize32(in, false, nullptr);

    std::vector<uint32_t> key;
    key.reserve(codepoints.size());

    for (size_t i = 0; i < codepoints.size(); ) {
        get_ducet_level1(codepoints,i,key);
    }

    return key;
}

} // namespace miniutf
