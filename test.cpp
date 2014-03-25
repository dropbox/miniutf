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

#include <cstdio>
#include <fstream>
#include <sstream>

#include "miniutf.hpp"
#include "miniutf_collation.hpp"

using std::string;
using std::istringstream;
using std::printf;
using std::snprintf;

void dump(const string & str) {
    for (size_t i = 0; i < str.length(); )
        printf(i ? "%04X" : " %04X", miniutf::utf8_decode(str, i));
}

int check_eq(const char *test, const string & expected, const string & got) {
    if (expected == got)
        return 1;

    printf("%s: expected \"", test);
    dump(expected);
    printf("\", got \"");
    dump(got);
    printf("\"\n");
    return 0;
}

string decode_hex(const string &in) {
    istringstream ss(in);
    int ch;
    string out;
    while (ss >> std::hex >> ch)
        miniutf::utf8_encode(ch, out);
    return out;
}

int process_test_line(string &line) {
    if (line[0] == '#')
        return 0;

    if (line[0] == '@') {
        printf("%s\n", line.c_str());
        return 0;
    }

    istringstream ss(line);

    string s1, s2, s3, s4, s5;
    std::getline(ss, s1, ';');
    std::getline(ss, s2, ';');
    std::getline(ss, s3, ';');
    std::getline(ss, s4, ';');
    std::getline(ss, s5, ';');
    if (!ss) {
        printf("Bad line format - expected 5 fields\n");
        return 1;
    }

    /* Decode each string as UTF-8 */
    s1 = decode_hex(s1);
    s2 = decode_hex(s2);
    s3 = decode_hex(s3);
    s4 = decode_hex(s4);
    s5 = decode_hex(s5);

    if (!check_eq("NFD(c1)", s3, miniutf::nfd(s1))) return 1;
    if (!check_eq("NFD(c2)", s3, miniutf::nfd(s2))) return 1;
    if (!check_eq("NFD(c3)", s3, miniutf::nfd(s3))) return 1;
    if (!check_eq("NFD(c4)", s5, miniutf::nfd(s4))) return 1;
    if (!check_eq("NFD(c5)", s5, miniutf::nfd(s5))) return 1;
    if (!check_eq("NFC(c1)", s2, miniutf::nfc(s1))) return 1;
    if (!check_eq("NFC(c2)", s2, miniutf::nfc(s2))) return 1;
    if (!check_eq("NFC(c3)", s2, miniutf::nfc(s3))) return 1;
    if (!check_eq("NFC(c4)", s4, miniutf::nfc(s4))) return 1;
    if (!check_eq("NFC(c5)", s4, miniutf::nfc(s5))) return 1;
    return 0;
}

string match_key_as_hex(const std::vector<uint32_t> & key) {
    string out;
    for (uint32_t c : key) {
        char outc[10];
        snprintf(outc, 10, "%08X ", (unsigned int)c);
        out.append(outc);
    }
    return out.substr(0,out.size()-1);
}

template <class T> string string_as_hex(const T & s) {
    string out;
    for (size_t i = 0; i < s.size(); i++) {
        char outc[10];
        snprintf(outc, 10, "%02X ", (unsigned int)s[i]);
        out.append(outc);
    }
    return out.substr(0,out.size()-1);
}

bool check_match_key(const string & s1, const string & s2) {
    std::vector<uint32_t> k1 = miniutf::match_key(s1);
    std::vector<uint32_t> k2 = miniutf::match_key(s2);
    if (k1 != k2) {
        printf("match_key(%s,%s) test failed\n", string_as_hex(s1).c_str(), string_as_hex(s2).c_str());
        printf("  got %s, expected %s\n", match_key_as_hex(k1).c_str(), match_key_as_hex(k2).c_str());
        std::u32string codepoints = miniutf::normalize32(s1, false, nullptr);
        printf("  codepoints are %s\n", string_as_hex(codepoints).c_str());
        return false;
    }
    return true;
}

int main(void) {

    string utf8_test = { '\x61', '\x00', '\xF0', '\x9F', '\x92', '\xA9' };
    std::u16string utf16_test = { 0x61, 0, 0xD83D, 0xDCA9 };

    // We also have some tests of UTF-8 to UTF-16 conversion
    string utf8 = miniutf::to_utf8(utf16_test);
    if (!check_eq("16-to-8", utf8_test, utf8))
        return 1;

    std::u16string utf16 = miniutf::to_utf16(utf8_test);
    if (utf16 != utf16_test) {
        printf("utf8-to-utf16 test failed: got ");
        for (size_t i = 0; i < utf16.length(); i++) printf("%04x ", (uint16_t)utf16[i]);
        printf("\n");
        return 1;
    }

    // Test match_key function
    if (!check_match_key(u8"Øǣç",
                         u8"oaec")) { return 1; }
    if (!check_match_key(u8"ãäåèéêëüõñ",
                         u8"aaaeeeeuon")) { return 1; }

    std::ifstream file("data-4.1.0/NormalizationTest.txt");

    string line;
    while (std::getline(file, line))
        if (process_test_line(line))
            return 1;

    printf("OK\n");
    return 0;
}
