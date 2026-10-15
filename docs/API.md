# API notes

These notes describe the endpoints used by `typan`. They come from static
analysis of the Tongji Yunpan web assets, the AnyShare REST API documentation
shipped with the server, and network captures of the login and share flows.

The server can change these endpoints without notice.

## Login flow

1. `GET /anyshare/oauth2/login?lang=zh-cn&redirect=/anyshare/zh-cn/homepage`
   redirects to `/oauth2/auth` and then to `/oauth2/signin`.
2. `GET /oauth2/signin?login_challenge=...` returns an HTML page. The page
   contains `challenge` and `csrftoken` in `__NEXT_DATA__`.
3. Encrypt the password with the login page RSA public key. Use PKCS#1 v1.5,
   then Base64.
4. `POST /oauth2/signin` with JSON:

   ```json
   {
     "_csrf": "<csrftoken>",
     "challenge": "<challenge>",
     "account": "<account>",
     "password": "<base64-rsa-ciphertext>",
     "vcode": {"id": "", "content": ""},
     "dualfactorauthinfo": {
       "validcode": {"vcode": ""},
       "OTP": {"OTP": ""}
     },
     "remember": false,
     "device": {"name": "", "description": "", "client_type": "web", "udids": []}
   }
   ```

5. The response contains `redirect`. Follow it through the consent flow.
6. `GET /anyshare/oauth2/login/callback?...` sets these cookies:
   - `client.oauth2_token`
   - `client.oauth2_refresh_token`
   - `id_token`

Use `client.oauth2_token` as a Bearer token for API requests.

Refresh the token with `GET /anyshare/oauth2/login/refreshToken`.

## API conventions

All JSON API calls below use this prefix and header:

```text
https://yunpan.tongji.edu.cn/api
Authorization: Bearer <client.oauth2_token>
Content-Type: application/json
```

## Browsing

| Endpoint | Purpose |
|---|---|
| `GET /efast/v1/entry-doc-lib` | List document libraries. |
| `POST /efast/v1/file/getinfobypath` | Resolve `{"namepath": "..."}` to a GNS id. |
| `POST /efast/v1/dir/list` | List a directory by `{"docid": "..."}`. |
| `POST /efast/v1/dir/create` | Create a directory. |

## Upload

Small files use a single PUT:

1. Optionally call `POST /efast/v1/file/predupload`.
2. If `match` is true, call `POST /efast/v1/file/dupload`.
3. Otherwise call `POST /efast/v1/file/osbeginupload` with the parent GNS id,
   file name, length, and conflict policy.
4. The response contains `authrequest`: method, URL, and headers. Send the file
   bytes to that URL with those headers.
5. Call `POST /efast/v1/file/osendupload` with the returned `docid` and `rev`.

Files larger than 5 GiB need the multipart flow
(`osinitmultiupload`, `osuploadpart`, `oscompleteupload`, `osendupload`).
This project does not implement that flow yet.

## Download

`POST /efast/v1/file/osdownload` with:

```json
{
  "docid": "gns://...",
  "rev": "<optional revision>",
  "authtype": "QUERY_STRING",
  "savename": "download.bin"
}
```

The response contains `authrequest[1]`: a signed object-storage URL. The URL
expires in about 15 minutes.

## Share links

Anonymous share links live under `/link/<link_id>`.

| Endpoint | Purpose |
|---|---|
| `POST /shared-link/v1/document/anonymous` | Create an anonymous share link. |
| `GET /shared-link/v1/document/{item_type}/{docid}?type=anonymous` | List links for one item. |
| `PUT /shared-link/v1/document/anonymous/{link_id}` | Update a link. |
| `DELETE /shared-link/v1/document/anonymous/{link_id}` | Delete a link. |
| `GET /shared-link/v1/links/{link_id}` | Read link metadata without a logged-in account. |

Create body:

```json
{
  "item": {
    "id": "gns://...",
    "type": "file",
    "allow": ["display", "preview", "download"]
  },
  "title": "file.bin",
  "expires_at": "2099-12-31T23:59:59+08:00",
  "password": "",
  "limited_times": -1
}
```

Permission values are strings. The common set is `display`, `preview`, and
`download`. Numeric permission bits used by the web client are:

| Permission | Value |
|---|---:|
| display | 1 |
| preview | 2 |
| download | 4 |
| create | 8 |
| modify | 16 |
| delete | 32 |
| cache | 64 |

### Resolve a share link without login

1. `GET /link/<link_id>` returns HTTP 302 and sets a cookie named
   `link_token:<link_id>`.
2. Use that cookie value as a Bearer token.
3. `GET /api/shared-link/v1/links/<link_id>` reads the link metadata.
4. `GET /api/efast/v1/entry-item` returns the shared file entry, including its
   GNS id.
5. `POST /api/efast/v1/file/osdownload` returns a fresh signed download URL.

This is the flow used by `typan share-url` and `typan share-download`.
