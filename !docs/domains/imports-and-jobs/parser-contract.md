# Import parser contract

Type: module
Status: current
Owns: file parsing and normalization boundary
Code: `modules/imports/` source parsers and normalizers
Update when: supported shape, normalization schema or parse issue changes

Parsers are deterministic and database-free. They detect one supported file
shape, preserve physical row identity and report malformed/unsupported rows as
structured issues. Encoding, delimiter and header ambiguity fail safely without
echoing an entire untrusted file. Normalizers produce versioned JSON-safe
evidence with exact signed decimal strings and explicit currency.

Parser output does not classify, deduplicate, post or calculate portfolio data.
