# Password factor (M3)

Real implementation since week 4. Design and reasons: [`DESIGN.md`](DESIGN.md).

| File | What it does |
|---|---|
| `factor.py` | `PasswordFactor`: argon2id verify, enrollment (set password), leaked flag, hash upgrade |
| `policy.py` | Length rules: 8–128 characters, no composition rules (NIST SP 800-63B) |
| `leaked.py` | Local leaked-password list (Python set, nothing sent to outside services) |
| `storage.py` | Table `password_credentials` (argon2 hashes only) + SQL and in-memory stores |
| `mock.py` | Mock version (week 3), used when `FACTOR_MODE=mock` |

## Leaked-password list (download once, never commit)

UK NCSC "100k most used passwords" (from Have I Been Pwned), published in the SecLists project.
From the repository root (Git Bash):

```sh
mkdir -p datasets/leaked-passwords
curl -L -o datasets/leaked-passwords/top-100000.txt \
  https://raw.githubusercontent.com/danielmiessler/SecLists/master/Passwords/Common-Credentials/100k-most-used-passwords-NCSC.txt
```

`datasets/` is git-ignored. Docker mounts it read-only at `/datasets` (see `docker-compose.yml`).
Without the file the factor still works, but the leaked check is **off** (a warning is logged).

## Use the real factor

Set `FACTOR_MODE=real` in `.env` and restart (`docker compose up -d`). The platform then uses this real
password factor and mocks for the factors that are not real yet.

Try it (Git Bash, backend running):

```sh
API=http://localhost:8000
SESSION=$(curl -s -X POST $API/auth/register -H "Content-Type: application/json" \
  -d '{"username":"alice"}' | python -c "import sys,json;print(json.load(sys.stdin)['session'])")
curl -s -X POST $API/auth/enroll/password/finish -H "Authorization: Bearer $SESSION" \
  -H "Content-Type: application/json" -d '{"payload":{"password":"correct horse battery staple"}}'
# -> {"done":true,"remaining":0,"reason":null}
```

## Tests

```sh
cd backend
python -m pytest tests/factors/password -q
```
