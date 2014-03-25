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

#include <vector>
#include <unordered_map>

namespace miniutf {

#include "miniutfdata_collation.h"

using ducet_level1_map = std::unordered_map<std::u32string, std::vector<uint32_t>>;

ducet_level1_map build_ducet_level1_map() {
    ducet_level1_map out;

    for (uint32_t c : ducet_data_empty) {
        out[{ c }] = {};
    }

    for (const uint32_t * it = std::begin(ducet_data_short);
                          it < std::end(ducet_data_short);
                          it += 2) {
        out[{ it[0] }] = { it[1] };
    }


    // declare outside the loop to minimize reallocations
    std::u32string str;
    std::vector<uint32_t> el;
    size_t i = 0;
    const size_t sz = std::end(ducet_data_variable) - std::begin(ducet_data_variable);

    while (i < sz) {
        while (ducet_data_variable[i] != 0) {
            str.push_back(ducet_data_variable[i++]);
        }
        ++i; // skip the zero
        while (ducet_data_variable[i] != 0) {
            el.push_back(ducet_data_variable[i++]);
        }
        ++i; // skip the zero
        out[str] = el;
        str.clear();
        el.clear();
    }

    return out;
}

/*
 * Finds the DUCET collation elements at position i in a string, adds its length to i, and
 * appends the collation elements to the given vector. We only deal with level 1 here.
 */
void get_ducet_level1(const std::u32string & str,
                      size_t & i,
                      std::vector<uint32_t> & elements) {

    // C++11 guarantees that this will be initialized in a thread-safe manner.
    static const ducet_level1_map ducet_level1 = build_ducet_level1_map();

    // Find longest key in ducet.
    size_t j = 1;
    std::u32string pts = str.substr(i, j);
    auto itr = ducet_level1.find(pts);
    std::vector<uint32_t> el;
    bool found_flag = false;
    while (itr != ducet_level1.end() && i+j <= str.length()) {
        el = itr->second;
        found_flag = true;
        pts = str.substr(i, ++j);
        itr = ducet_level1.find(pts);
    }

    if (found_flag) {
        i += j-1;
    } else {
        ++i;
        // http://www.unicode.org/reports/tr10/#Derived_Collation_Elements
        char32_t pt = str[i];
        char32_t base = 0xfbc0;
        // The following is completely wrong, but probably good enough.
        // (Should actually check if it is Unified_Ideograph.)
        if ((0x3300 < pt && pt < 0x33ff)                // CJK Compatibility
            || (0x4e00 < pt && pt < 0x9fff)) {          // CJK Unified Ideographs
            base = 0xfb40;
        } else if ((0x3400 < pt && pt < 0x4dbf)         // CJK Unified Ideographs Extension A
                   || (0x20000 < pt && pt < 0x2a6df)    // CJK Unified Ideographs Extension B
                   || (0x2a700 < pt && pt < 0x2b73f)    // CJK Unified Ideographs Extension C
                   || (0x2b740 < pt && pt < 0x2b81f)) { // CJK Unified Ideographs Extension D
            base = 0xfb80;
        }
        char32_t aaaa = base + (pt >> 15);
        char32_t bbbb = (pt & 0x7fff) | 0x8000;
        el = {aaaa,bbbb};
    }

    elements.insert(elements.end(), el.begin(), el.end());
}

std::vector<uint32_t> match_key(const std::string & in) {
    // http://www.unicode.org/reports/tr10/

    std::u32string codepoints = normalize32(in, false, nullptr);

    std::vector<uint32_t> key;
    key.reserve(codepoints.size());

    for (size_t i = 0; i < codepoints.size(); ) {
        get_ducet_level1(codepoints,i,key);
    }

    return key;
}

}
