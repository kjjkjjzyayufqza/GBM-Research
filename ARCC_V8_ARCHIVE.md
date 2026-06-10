# ARCC v8 Archive Format

Last updated: 2026-06-07

Related docs:

- [README.md](README.md) - project entry point and key document index.
- [RESOURCE_FORMAT_CATALOG.md](RESOURCE_FORMAT_CATALOG.md) - broader format catalog and DLC archive directory meanings.
- [TOOLS_REFERENCE.md#toolsgbm_arc_extractpy](TOOLS_REFERENCE.md#toolsgbm_arc_extractpy) - extractor command reference.

## Summary

GBM DLC archives use an encrypted MT-style archive container:

```text
magic   = "ARCC"
version = 8
entry   = 0x90 bytes
```

The working extractor is `tools\gbm_arc_extract.py`.

## Header

```text
0x00  char[4]  "ARCC"
0x04  u16      version, observed 8
0x06  u16      file count
0x08  bytes    encrypted table of contents
```

The encrypted TOC length is:

```text
file_count * 0x90
```

## Decrypted TOC Entry

Each decrypted entry is 0x90 bytes:

```text
0x00  char[0x80]  resource path without extension
0x80  u32         type code
0x84  u32         compressed payload size
0x88  u32         uncompressed size plus flags
0x8c  u32         payload offset
```

The high flag bit `0x40000000` marks zlib-compressed payloads. The lower
`0x0fffffff` bits hold the uncompressed size.

## Encryption

The recovered key bytes used by the current extractor are:

```text
c6 c8 51 1e bd ca e0 97 fd b7 46 84 af 51 cf cd 83 5f e0
```

The transform is Blowfish ECB with 32-bit byte swapping around each encrypted
8-byte block. The same transform is used for the TOC and encrypted payloads.

## Payload Decoding

Payload handling is:

1. read `compressed_size` bytes at the entry offset;
2. decrypt with the same MT Blowfish block transform;
3. if `0x40000000` is set in `size_flags`, inflate with zlib;
4. infer the file extension from the decoded magic and write the output file.

## Sample Evidence

`com.bandainamcoent.gb_jp\files\dlc\archive\ch\320900.arc` has 279 entries.
The current sample output in `research_output\320900_first89_v2` contains the
model resources needed for static extraction:

```text
character\ma320900\mod\ma320900_BM.tex
character\ma320900\mod\ma320900_NM.tex
character\ma320900\mod\ma320900.mrl
character\ma320900\mod\ma320900.mod
motion\ma\ma320900\ma320900.lmt
```

For static model extraction, only the TEX, MRL, MOD, and global
`ShaderPackage.mfx` are required.
