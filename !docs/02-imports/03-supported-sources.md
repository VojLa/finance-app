# Supported Sources

| API source value | Current parser | Meaning of support |
| --- | --- | --- |
| `raiffeisenbank` | Generic strict CSV | Upload, preserve rows, and generic normalization |
| `trading212` | Generic strict CSV | Upload, preserve rows, and generic normalization |
| `anycoin` | Generic strict CSV | Upload, preserve rows, and generic normalization |
| `manual` | Generic strict CSV | Upload, preserve rows, and generic normalization |

The source label selects a parser registry entry, but the Python backend does
not yet contain broker- or bank-specific CSV mappings, grouped trade parsers, or
posting rules. Existing TypeScript parsers in the Next.js application are legacy
code paths and are not called by this FastAPI import pipeline.

Adding a source requires an `ImportSource` schema migration and enum update,
registration in the parser registry, a deterministic parser with fixtures, and
normalization/posting semantics before it can be described as end-to-end support.
