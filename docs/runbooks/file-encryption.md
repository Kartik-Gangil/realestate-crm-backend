# File encryption runbook

`private_media` stores ciphertext in the `CRMENC1` + nonce + AES-256-GCM format. `media` contains old plaintext originals until the owner confirms deletion.

Generate the URL-safe base64 key, store it in `.env`, and back it up separately (for example in a password manager). Use one key per environment.

To move existing files: take a database backup, run `encrypt_existing_files --dry-run`, check the counts, run `--apply`, check `missing` and `conflict` are expected, and test several downloads.

Delete originals only after owner confirmation with `--apply --delete-originals`; orphans are never deleted by the command.

Never serve `media` or `private_media` from a web server or reverse proxy. Back up the database and `private_media` together, and back up the key separately.

If a download returns 500 `The stored file could not be read`, the file was changed or encrypted with another key; check the key first.
