# Upload and document-container limits

Imports now reject more than 250 uploaded files and enforce an 80 MiB aggregate
read budget, in addition to the existing 40 MiB per-file limit. Reads request at
most the remaining/per-file allowance plus one byte, rejecting oversize data
before extraction. Folder imports also enforce the existing two-million-character
book limit across all files. HTTP 413 identifies these import-limit rejections;
temporary extraction directories are removed and no book rows are written.

ZIP, EPUB and DOCX containers now check all member count, aggregate uncompressed
size and maximum member size before member parsing. This extends the ZIP-only
checks to compressed document formats. Existing document extraction remains in
place; it is not a parser sandbox.

Verification: 25 offline tests (14 existing auth/archive tests; seven bounded
upload/route tests; four compressed-document regressions) and app/extract syntax
compilation. Upload tests execute actual route/helper ASTs with temporary storage,
real UploadFile objects and mocked extraction/database operations. No narration
provider is called. Archive tests use actual generated ZIP/EPUB containers.

Limits: multipart parsing occurs before the route, so a reverse proxy/ASGI ingress
body limit and disk quota are still needed for complete request admission control.
The new checks bound upload reads and advertised archive resources; they do not
prove PDF/Word/XML parser safety, CPU isolation, hosted authentication or production
readiness. No production configuration was changed.
